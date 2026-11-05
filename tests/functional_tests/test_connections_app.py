from pathlib import Path

import pytest
from textual.geometry import Region
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import DataTable, Input, Label, Select, Switch

from harlequin.components.connection_form import ConnectionFormModal
from harlequin.config import ConfigFile
from harlequin.connections_app import ConnectionsApp, ConnectionsResult
from harlequin.options import AbstractOption, FlagOption, ListOption, TextOption
from tests.waiting import settle_app, wait_for

CONFIG = """\
default_profile = "local"

[profiles.local]
adapter = "duckdb"
conn_str = [":memory:"]

[profiles.staging]
adapter = "mysql"
host = "db.stage.example.com"
port = 3306
user = "reader"
password = "hunter2"
database = "bzdb"
"""


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "harlequin.toml"
    path.write_text(CONFIG)
    return path


def table_rows(app: ConnectionsApp) -> list[tuple[str, ...]]:
    table = app.query_one(DataTable)
    return [
        tuple(str(cell) for cell in table.get_row_at(index))
        for index in range(table.row_count)
    ]


@pytest.mark.asyncio
async def test_lists_profiles_without_secrets(config_path: Path) -> None:
    app = ConnectionsApp(config_path=config_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle_app(pilot)

        rows = table_rows(app)
        assert [row[0] for row in rows] == ["local", "staging"]
        assert rows[0][1] == "duckdb"
        assert rows[1][2] == "db.stage.example.com:3306/bzdb"
        assert "hunter2" not in " ".join(" ".join(row) for row in rows)


@pytest.mark.asyncio
async def test_enter_connects_with_the_highlighted_profile(config_path: Path) -> None:
    app = ConnectionsApp(config_path=config_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle_app(pilot)
        await pilot.press("down", "enter")
        await wait_for(
            pilot, lambda: app.return_value is not None, description="the app to exit"
        )

    assert app.return_value == ConnectionsResult(action="connect", profile="staging")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["escape", "n"])
async def test_escape_and_n_start_the_default_session(
    config_path: Path, key: str
) -> None:
    app = ConnectionsApp(config_path=config_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle_app(pilot)
        await pilot.press(key)
        await wait_for(
            pilot, lambda: app.return_value is not None, description="the app to exit"
        )

    assert app.return_value == ConnectionsResult(action="default")


@pytest.mark.asyncio
async def test_q_quits(config_path: Path) -> None:
    app = ConnectionsApp(config_path=config_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle_app(pilot)
        await pilot.press("q")
        await wait_for(
            pilot, lambda: app.return_value is not None, description="the app to exit"
        )

    assert app.return_value == ConnectionsResult(action="quit")


@pytest.mark.asyncio
async def test_delete_asks_first_and_removes_the_profile(config_path: Path) -> None:
    app = ConnectionsApp(config_path=config_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle_app(pilot)

        await pilot.press("down", "d")
        await settle_app(pilot)
        await pilot.press("n")
        await settle_app(pilot)
        assert "staging" in ConfigFile(config_path).relevant_config["profiles"]
        assert len(table_rows(app)) == 2

        await pilot.press("d")
        await settle_app(pilot)
        await pilot.press("y")
        await wait_for(
            pilot, lambda: len(table_rows(app)) == 1, description="the row to go"
        )

    assert list(ConfigFile(config_path).relevant_config["profiles"]) == ["local"]


FAKE_OPTIONS: dict[str, list[AbstractOption]] = {
    "duckdb": [
        TextOption("md_token", "token", secret=True),
        FlagOption("no-init", "skip init"),
        ListOption("extension", "extensions"),
    ],
    "mysql": [
        TextOption("host", "host"),
        TextOption("port", "port"),
        TextOption("database", "database"),
        TextOption("password", "password", secret=True),
    ],
}


def fake_app(config_path: Path) -> ConnectionsApp:
    return ConnectionsApp(
        config_path=config_path,
        adapter_names=lambda: ["duckdb", "mysql"],
        load_adapter_options=lambda name: FAKE_OPTIONS[name],
    )


def saved_profiles(config_path: Path) -> dict[str, dict[str, object]]:
    return dict(ConfigFile(config_path).relevant_config["profiles"])


async def open_form(pilot: Pilot, app: ConnectionsApp, key: str) -> Screen:
    await pilot.press(key)
    await wait_for(
        pilot,
        lambda: isinstance(app.screen, ConnectionFormModal),
        description="the connection form to open",
    )
    return app.screen


@pytest.mark.asyncio
async def test_add_saves_a_new_profile(config_path: Path) -> None:
    app = fake_app(config_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        form = await open_form(pilot, app, "a")

        form.query_one("#connection_name", Input).value = "scratch"
        form.query_one("#connection_adapter", Select).value = "mysql"
        await wait_for(
            pilot,
            lambda: bool(form.query("#host")),
            description="the mysql options to appear",
        )
        form.query_one("#host", Input).value = "h.example.com"
        form.query_one("#port", Input).value = "3306"
        form.query_one("#password", Input).value = "${DB_PASSWORD}"
        assert form.query_one("#password", Input).password

        await pilot.press("ctrl+s")
        await wait_for(
            pilot, lambda: len(table_rows(app)) == 3, description="the new row"
        )
        assert "scratch" in [row[0] for row in table_rows(app)]

    assert saved_profiles(config_path)["scratch"] == {
        "adapter": "mysql",
        "host": "h.example.com",
        "port": "3306",
        "password": "${DB_PASSWORD}",
    }


@pytest.mark.asyncio
async def test_add_skips_blank_fields_and_splits_lists(config_path: Path) -> None:
    app = fake_app(config_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        form = await open_form(pilot, app, "a")

        form.query_one("#connection_name", Input).value = "ducky"
        form.query_one("#connection_adapter", Select).value = "duckdb"
        await wait_for(
            pilot,
            lambda: bool(form.query("#extension")),
            description="the duckdb options to appear",
        )
        form.query_one("#connection_conn_str", Input).value = "a.db 'my file.db'"
        form.query_one("#extension", Input).value = "httpfs spatial"
        form.query_one("#no-init", Switch).value = True

        await pilot.press("ctrl+s")
        await wait_for(
            pilot, lambda: len(table_rows(app)) == 3, description="the new row"
        )

    assert saved_profiles(config_path)["ducky"] == {
        "adapter": "duckdb",
        "conn_str": ["a.db", "my file.db"],
        "extension": ["httpfs", "spatial"],
        "no_init": True,
    }


@pytest.mark.asyncio
async def test_edit_keeps_untouched_keys_and_their_types(tmp_path: Path) -> None:
    config_path = tmp_path / "harlequin.toml"
    config_path.write_text(
        CONFIG.replace('database = "bzdb"', 'database = "bzdb"\nlimit = 50')
    )
    app = fake_app(config_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        await pilot.press("down")
        form = await open_form(pilot, app, "e")
        await wait_for(
            pilot, lambda: bool(form.query("#host")), description="the options"
        )

        assert form.query_one("#connection_name", Input).value == "staging"
        assert form.query_one("#host", Input).value == "db.stage.example.com"
        form.query_one("#host", Input).value = "new.example.com"

        await pilot.press("ctrl+s")
        await wait_for(
            pilot,
            lambda: not isinstance(app.screen, ConnectionFormModal),
            description="the form to close",
        )

    staging = saved_profiles(config_path)["staging"]
    assert staging["host"] == "new.example.com"
    assert staging["port"] == 3306
    assert staging["password"] == "hunter2"
    assert staging["limit"] == 50
    assert staging["user"] == "reader"


@pytest.mark.asyncio
async def test_edit_can_rename_a_profile(config_path: Path) -> None:
    app = fake_app(config_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        form = await open_form(pilot, app, "e")
        form.query_one("#connection_name", Input).value = "scratch"

        await pilot.press("ctrl+s")
        await wait_for(
            pilot,
            lambda: not isinstance(app.screen, ConnectionFormModal),
            description="the form to close",
        )

    config = ConfigFile(config_path).relevant_config
    assert sorted(config["profiles"]) == ["scratch", "staging"]
    assert config["default_profile"] == "scratch"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["local", "  "])
async def test_a_taken_or_empty_name_is_refused(config_path: Path, name: str) -> None:
    before = config_path.read_text()
    app = fake_app(config_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        form = await open_form(pilot, app, "a")
        form.query_one("#connection_name", Input).value = name

        await pilot.press("ctrl+s")
        await settle_app(pilot)

        assert isinstance(app.screen, ConnectionFormModal)
        assert str(form.query_one("#connection_error", Label).content).strip()

    assert config_path.read_text() == before


@pytest.mark.asyncio
async def test_escape_cancels_the_form(config_path: Path) -> None:
    before = config_path.read_text()
    app = fake_app(config_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        form = await open_form(pilot, app, "a")
        form.query_one("#connection_name", Input).value = "scratch"

        await pilot.press("escape")
        await wait_for(
            pilot,
            lambda: not isinstance(app.screen, ConnectionFormModal),
            description="the form to close",
        )

        assert app.return_value is None

    assert config_path.read_text() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("height", [18, 24, 30, 40])
async def test_form_buttons_stay_on_screen_in_short_terminals(
    config_path: Path, height: int
) -> None:
    app = fake_app(config_path)
    async with app.run_test(size=(100, height)) as pilot:
        await settle_app(pilot)
        form = await open_form(pilot, app, "a")
        form.query_one("#connection_adapter", Select).value = "mysql"
        await wait_for(
            pilot, lambda: bool(form.query("#password")), description="the options"
        )
        await settle_app(pilot)

        screen_region = Region(0, 0, *app.size)
        for selector in ("#save", "#cancel", "#connection_path", "#connection_name"):
            widget_region = form.query_one(selector).region
            assert screen_region.contains_region(widget_region), (selector, height)

        form.query_one("#password", Input).focus()
        await settle_app(pilot)
        password_region = form.query_one("#password", Input).region
        fields_region = form.query_one("#connection_fields").region
        assert fields_region.contains_region(password_region), height


@pytest.mark.asyncio
async def test_form_masks_options_named_like_secrets_even_if_undeclared(
    config_path: Path,
) -> None:
    options: list[AbstractOption] = [
        TextOption("host", "host"),
        TextOption("password", "password"),
        TextOption("api_token", "token"),
    ]
    app = ConnectionsApp(
        config_path=config_path,
        adapter_names=lambda: ["mysql"],
        load_adapter_options=lambda name: options,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await settle_app(pilot)
        await pilot.press("down")
        form = await open_form(pilot, app, "e")
        await wait_for(
            pilot, lambda: bool(form.query("#password")), description="the options"
        )

        assert form.query_one("#password", Input).password
        assert form.query_one("#api_token", Input).password
        assert not form.query_one("#host", Input).password
        assert not form.query_one("#connection_name", Input).password
