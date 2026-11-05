from pathlib import Path

import pytest

from harlequin import cli
from harlequin.connections_app import ConnectionsApp, ConnectionsResult

PROFILES = """\
[profiles.local]
adapter = "duckdb"
conn_str = [":memory:"]

[profiles.staging]
adapter = "mysql"
host = "db.stage.example.com"
"""


@pytest.fixture
def config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "harlequin.config._search_directories",
        lambda: [(tmp_path, ("harlequin.toml",))],
    )
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    return tmp_path


def picks(
    monkeypatch: pytest.MonkeyPatch, result: ConnectionsResult | None
) -> list[int]:
    calls: list[int] = []

    def run(self: ConnectionsApp, *args: object, **kwargs: object) -> object:
        calls.append(1)
        return result

    monkeypatch.setattr(ConnectionsApp, "run", run)
    return calls


def test_arguments_skip_the_picker(
    config_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (config_directory / "harlequin.toml").write_text(PROFILES)
    calls = picks(monkeypatch, ConnectionsResult(action="quit"))

    assert cli.choose_connection(["-P", "local"]) == ["-P", "local"]
    assert cli.choose_connection([":memory:"]) == [":memory:"]
    assert calls == []


def test_no_profiles_skips_the_picker(
    config_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = picks(monkeypatch, ConnectionsResult(action="quit"))

    assert cli.choose_connection([]) == []
    assert calls == []


def test_a_default_profile_skips_the_picker(
    config_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (config_directory / "harlequin.toml").write_text(
        'default_profile = "local"\n' + PROFILES
    )
    calls = picks(monkeypatch, ConnectionsResult(action="quit"))

    assert cli.choose_connection([]) == []
    assert calls == []


def test_not_a_terminal_skips_the_picker(
    config_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (config_directory / "harlequin.toml").write_text(PROFILES)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    calls = picks(monkeypatch, ConnectionsResult(action="quit"))

    assert cli.choose_connection([]) == []
    assert calls == []


def test_choosing_a_connection_selects_its_profile(
    config_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (config_directory / "harlequin.toml").write_text(PROFILES)
    picks(monkeypatch, ConnectionsResult(action="connect", profile="staging"))

    assert cli.choose_connection([]) == ["-P", "staging"]


def test_default_session_launches_with_no_arguments(
    config_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (config_directory / "harlequin.toml").write_text(PROFILES)
    picks(monkeypatch, ConnectionsResult(action="default"))

    assert cli.choose_connection([]) == []


@pytest.mark.parametrize("result", [ConnectionsResult(action="quit"), None])
def test_quitting_the_picker_exits(
    config_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: ConnectionsResult | None,
) -> None:
    (config_directory / "harlequin.toml").write_text(PROFILES)
    picks(monkeypatch, result)

    with pytest.raises(SystemExit) as exit_info:
        cli.choose_connection([])

    assert exit_info.value.code == 0
