from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection, Sequence

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Switch

from harlequin.components.modal import HarlequinModal
from harlequin.config import Profile, sluggify_option_name
from harlequin.connections import ConnectionEntry
from harlequin.copy_widgets import NoFocusLabel
from harlequin.options import AbstractOption, ListOption
from harlequin.redact import option_is_secret

SECRET_TIP = "Tip: use ${ENV_VAR} instead of storing a secret in the config file."


@dataclass(frozen=True)
class ConnectionFormResult:
    name: str
    profile: Profile
    replacing: str | None


class ConnectionFormModal(HarlequinModal[ConnectionFormResult | None]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        adapter_names: Sequence[str],
        load_adapter_options: Callable[[str], Sequence[AbstractOption]],
        existing_names: Collection[str],
        target_path: Path,
        entry: ConnectionEntry | None = None,
    ) -> None:
        super().__init__()
        self.entry = entry
        self.target_path = target_path
        self.existing_names = set(existing_names)
        self.load_adapter_options = load_adapter_options
        self.adapter_names = list(adapter_names)
        if entry is not None and entry.adapter not in self.adapter_names:
            self.adapter_names.append(entry.adapter)
        self.current_options: Sequence[AbstractOption] = []
        self.original_profile: Profile = dict(entry.profile) if entry else {}

    @property
    def initial_adapter(self) -> str:
        if self.entry is not None:
            return self.entry.adapter
        return "duckdb" if "duckdb" in self.adapter_names else self.adapter_names[0]

    def compose(self) -> ComposeResult:
        title = "Edit connection" if self.entry else "Add connection"
        conn_str = self.original_profile.get("conn_str", [])
        if isinstance(conn_str, str):
            conn_str = [conn_str]
        with Vertical(id="connection_form"):
            yield Label(title, id="connection_form_title")
            with VerticalScroll(id="connection_fields"):
                yield Horizontal(
                    NoFocusLabel("Name:", classes="input_label"),
                    Input(
                        value=self.entry.name if self.entry else "",
                        placeholder="a short name",
                        id="connection_name",
                    ),
                    classes="option_row",
                )
                yield Horizontal(
                    NoFocusLabel("Adapter:", classes="select_label"),
                    Select(
                        [(name, name) for name in self.adapter_names],
                        value=self.initial_adapter,
                        allow_blank=False,
                        id="connection_adapter",
                    ),
                    classes="option_row",
                )
                yield Horizontal(
                    NoFocusLabel("Connection string:", classes="input_label"),
                    Input(
                        value=shlex.join(str(item) for item in conn_str),
                        placeholder="space separated; quote items with spaces",
                        id="connection_conn_str",
                    ),
                    classes="option_row",
                )
                yield Vertical(id="connection_options")
            yield Label("", id="connection_error")
            yield Label("", id="connection_hint")
            yield Label(f"Saving to {self.target_path}", id="connection_path")
            with Horizontal(id="button_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    async def on_mount(self) -> None:
        await self.show_options(self.initial_adapter)
        self.query_one("#connection_name", Input).focus()

    @on(Select.Changed, "#connection_adapter")
    async def adapter_changed(self, event: Select.Changed) -> None:
        event.stop()
        if isinstance(event.value, str):
            await self.show_options(event.value)

    async def show_options(self, adapter: str) -> None:
        try:
            self.current_options = list(self.load_adapter_options(adapter))
        except Exception:
            self.current_options = []
        container = self.query_one("#connection_options", Vertical)
        await container.remove_children()
        rows: list[Widget] = []
        for option in self.current_options:
            if isinstance(option, ListOption):
                widgets: list[Widget] = [
                    NoFocusLabel(f"{option.label}:", classes="input_label"),
                    Input(placeholder="space separated", id=option.name),
                ]
            else:
                widgets = list(option.to_widgets())
            rows.append(Horizontal(*widgets, classes="option_row"))
        await container.mount_all(rows)
        for option in self.current_options:
            self.prefill(option, adapter)

    def prefill(self, option: AbstractOption, adapter: str) -> None:
        widget = self.query_one(f"#{option.name}")
        if option_is_secret(option) and isinstance(widget, Input):
            widget.password = True
        key = sluggify_option_name(option.name)
        if self.entry is None or adapter != self.entry.adapter:
            return
        if key not in self.original_profile:
            return
        original = self.original_profile[key]
        if isinstance(widget, Switch):
            widget.value = bool(original)
        elif isinstance(widget, Select):
            widget.value = original
        elif isinstance(widget, Input):
            widget.value = (
                shlex.join(str(item) for item in original)
                if isinstance(original, (list, tuple))
                else str(original)
            )

    @on(Input.Changed)
    def show_secret_tip(self, event: Input.Changed) -> None:
        secret_names = {
            option.name for option in self.current_options if option_is_secret(option)
        }
        if event.input.id not in secret_names:
            return
        value = event.value.strip()
        hint = SECRET_TIP if value and not value.startswith("${") else ""
        self.query_one("#connection_hint", Label).update(hint)

    @on(Input.Submitted)
    def save_from_input(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    @on(Button.Pressed, "#save")
    def save_from_button(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def cancel_from_button(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        name = self.query_one("#connection_name", Input).value.strip()
        taken_names = self.existing_names - (
            {self.entry.name} if self.entry is not None else set()
        )
        error = ""
        if not name:
            error = "Give the connection a name."
        elif name in taken_names:
            error = f"A connection named '{name}' already exists."
        profile: Profile = {}
        if not error:
            try:
                profile = self.build_profile()
            except ValueError as e:
                error = f"Could not read a list value: {e}"
        self.query_one("#connection_error", Label).update(error)
        if error:
            return
        self.dismiss(
            ConnectionFormResult(
                name=name,
                profile=profile,
                replacing=self.entry.name if self.entry is not None else None,
            )
        )

    def build_profile(self) -> Profile:
        adapter = str(self.query_one("#connection_adapter", Select).value)
        profile: Profile = dict(self.original_profile)
        adapter_unchanged = self.entry is None or adapter == self.entry.adapter
        if self.entry is not None and not adapter_unchanged:
            try:
                previous_options = self.load_adapter_options(self.entry.adapter)
            except Exception:
                previous_options = []
            for option in previous_options:
                profile.pop(sluggify_option_name(option.name), None)
        profile["adapter"] = adapter

        conn_str = shlex.split(self.query_one("#connection_conn_str", Input).value)
        if conn_str:
            profile["conn_str"] = conn_str
        else:
            profile.pop("conn_str", None)

        for option in self.current_options:
            key = sluggify_option_name(option.name)
            original = profile.get(key) if adapter_unchanged else None
            value = self.read_option(option, original)
            if value is None:
                profile.pop(key, None)
            else:
                profile[key] = value
        return profile

    def read_option(self, option: AbstractOption, original: Any) -> Any:
        widget = self.query_one(f"#{option.name}")
        if isinstance(widget, Switch):
            default = bool(getattr(option, "default", False))
            return None if widget.value == default else widget.value
        if isinstance(widget, Select):
            return widget.value if isinstance(widget.value, str) else None
        if not isinstance(widget, Input):
            return None
        text = widget.value.strip()
        if not text:
            return None
        if isinstance(option, ListOption):
            return shlex.split(text)
        if original is not None and str(original) == text:
            return original
        return text
