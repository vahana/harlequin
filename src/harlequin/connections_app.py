from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

from platformdirs import user_config_path
from textual.app import ComposeResult
from textual.binding import Binding
from textual.driver import Driver
from textual.widgets import DataTable, Footer, Static

from harlequin.app_base import AppBase
from harlequin.components.confirm_modal import ConfirmModal
from harlequin.components.connection_form import (
    ConnectionFormModal,
    ConnectionFormResult,
)
from harlequin.config import get_highest_priority_existing_config_file
from harlequin.connections import (
    ConnectionEntry,
    delete_connection,
    list_connections,
    save_connection,
)
from harlequin.exception import HarlequinConfigError
from harlequin.options import AbstractOption


@dataclass(frozen=True)
class ConnectionsResult:
    action: Literal["connect", "default", "quit"]
    profile: str | None = None


class DeleteConnectionModal(ConfirmModal):
    BINDINGS = [
        Binding("y", "continue", "Delete"),
        Binding("n,escape", "cancel", "Keep"),
    ]


def installed_adapter_names() -> list[str]:
    from harlequin.plugins import adapter_names

    return adapter_names()


def installed_adapter_options(name: str) -> Sequence[AbstractOption]:
    from harlequin.plugins import load_adapter

    try:
        return load_adapter(name).ADAPTER_OPTIONS or []
    except HarlequinConfigError:
        return []


class ConnectionsApp(AppBase):
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("n,escape", "default_session", "Default session"),
        Binding("q,ctrl+q", "quit_app", "Quit"),
    ]
    CSS_PATH = ["global.tcss", "app.tcss", "connections_app.tcss"]
    TITLE = "Harlequin connections"

    def __init__(
        self,
        *,
        theme: str | None = "harlequin",
        config_path: Path | None = None,
        adapter_names: Callable[[], list[str]] = installed_adapter_names,
        load_adapter_options: Callable[
            [str], Sequence[AbstractOption]
        ] = installed_adapter_options,
        driver_class: type[Driver] | None = None,
        watch_css: bool = False,
    ):
        super().__init__(theme=theme, driver_class=driver_class, watch_css=watch_css)
        self.config_path = config_path
        self.adapter_names = adapter_names
        self.load_adapter_options = load_adapter_options
        self.entries: list[ConnectionEntry] = []

    def compose(self) -> ComposeResult:
        yield Static("Enter to connect", id="connections_hint")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="connections")
        yield Static("No connections yet.", id="connections_empty")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "Adapter", "Target", "Default")
        self.reload_connections()
        table.focus()

    def reload_connections(self) -> None:
        table = self.query_one(DataTable)
        cursor_row = table.cursor_row
        table.clear()
        self.entries = list_connections(self.config_path)
        for entry in self.entries:
            table.add_row(
                entry.name,
                entry.adapter,
                entry.target,
                "✓" if entry.is_default else "",
                key=entry.name,
            )
        if self.entries:
            table.move_cursor(row=min(cursor_row, len(self.entries) - 1))
        self.query_one("#connections_empty").display = not self.entries

    def selected_entry(self) -> ConnectionEntry | None:
        if not self.entries:
            return None
        table = self.query_one(DataTable)
        return self.entries[table.cursor_row]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.row_key.value is not None:
            self.exit(ConnectionsResult(action="connect", profile=event.row_key.value))

    def action_default_session(self) -> None:
        self.exit(ConnectionsResult(action="default"))

    def action_quit_app(self) -> None:
        self.exit(ConnectionsResult(action="quit"))

    def action_delete(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return

        def delete_if_confirmed(confirmed: bool | None) -> None:
            if confirmed:
                delete_connection(entry)
                self.reload_connections()

        self.push_screen(
            DeleteConnectionModal(
                f"Delete connection '{entry.name}'?",
                confirm_label="Delete",
                cancel_label="Keep",
            ),
            delete_if_confirmed,
        )

    def new_connection_path(self) -> Path:
        return (
            self.config_path
            or get_highest_priority_existing_config_file()
            or user_config_path(appname="harlequin", appauthor=False) / "config.toml"
        )

    def action_add(self) -> None:
        self.open_form(entry=None)

    def action_edit(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            self.open_form(entry=entry)

    def open_form(self, entry: ConnectionEntry | None) -> None:
        path = entry.path if entry is not None else self.new_connection_path()

        def save_result(result: ConnectionFormResult | None) -> None:
            if result is None:
                return
            try:
                save_connection(
                    path, result.name, result.profile, replacing=result.replacing
                )
            except (OSError, HarlequinConfigError) as e:
                self.notify(
                    str(e), title="Could not save the connection", severity="error"
                )
                return
            self.reload_connections()
            self.select_connection(result.name)

        self.push_screen(
            ConnectionFormModal(
                adapter_names=self.adapter_names(),
                load_adapter_options=self.load_adapter_options,
                existing_names={e.name for e in self.entries},
                target_path=path,
                entry=entry,
            ),
            save_result,
        )

    def select_connection(self, name: str) -> None:
        for index, entry in enumerate(self.entries):
            if entry.name == name:
                self.query_one(DataTable).move_cursor(row=index)
