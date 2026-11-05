from pathlib import Path

import pytest

from harlequin.config import ConfigFile
from harlequin.connections import (
    delete_connection,
    list_connections,
    save_connection,
)

CONFIG = """\
# my connections
default_profile = "local"

[profiles.local]
adapter = "duckdb"
conn_str = [":memory:"]

# staging mysql
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


def test_list_connections_names_adapter_and_target(config_path: Path) -> None:
    connections = list_connections(config_path)

    assert [connection.name for connection in connections] == ["local", "staging"]
    local, staging = connections
    assert local.adapter == "duckdb"
    assert local.target == ":memory:"
    assert local.is_default
    assert staging.adapter == "mysql"
    assert staging.target == "db.stage.example.com:3306/bzdb"
    assert not staging.is_default
    assert staging.path == config_path


def test_list_connections_never_shows_a_password(tmp_path: Path) -> None:
    path = tmp_path / "harlequin.toml"
    path.write_text(
        '[profiles.pg]\nadapter = "postgres"\n'
        'conn_str = ["postgresql://me:s3cret@host:5432/db"]\n'
    )

    (connection,) = list_connections(path)

    assert "s3cret" not in connection.target
    assert "host" in connection.target


def test_list_connections_is_empty_without_profiles(tmp_path: Path) -> None:
    path = tmp_path / "harlequin.toml"
    path.write_text('theme = "nord"\n')

    assert list_connections(path) == []


def test_save_connection_adds_a_profile_and_keeps_comments(config_path: Path) -> None:
    save_connection(
        config_path,
        name="analytics",
        profile={"adapter": "postgres", "host": "pg.example.com", "port": 5432},
    )

    text = config_path.read_text()
    assert "# my connections" in text
    assert "# staging mysql" in text
    names = [connection.name for connection in list_connections(config_path)]
    assert names == ["analytics", "local", "staging"]
    assert ConfigFile(config_path).relevant_config["profiles"]["analytics"] == {
        "adapter": "postgres",
        "host": "pg.example.com",
        "port": 5432,
    }


def test_save_connection_edits_a_profile_in_place(config_path: Path) -> None:
    save_connection(
        config_path,
        name="staging",
        profile={"adapter": "mysql", "host": "new.example.com", "database": "bzdb"},
    )

    profiles = ConfigFile(config_path).relevant_config["profiles"]
    assert profiles["staging"]["host"] == "new.example.com"
    assert "password" not in profiles["staging"]
    assert profiles["local"]["adapter"] == "duckdb"


def test_save_connection_renames_and_moves_the_default(config_path: Path) -> None:
    save_connection(
        config_path,
        name="scratch",
        profile={"adapter": "duckdb", "conn_str": [":memory:"]},
        replacing="local",
    )

    config = ConfigFile(config_path).relevant_config
    assert "local" not in config["profiles"]
    assert "scratch" in config["profiles"]
    assert config["default_profile"] == "scratch"


def test_save_connection_creates_the_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "harlequin.toml"

    save_connection(path, name="first", profile={"adapter": "duckdb"})

    assert [connection.name for connection in list_connections(path)] == ["first"]


def test_delete_connection_removes_only_that_profile(config_path: Path) -> None:
    (staging,) = [c for c in list_connections(config_path) if c.name == "staging"]

    delete_connection(staging)

    assert [c.name for c in list_connections(config_path)] == ["local"]
    assert "# my connections" in config_path.read_text()


def test_delete_connection_clears_a_default_that_pointed_at_it(
    config_path: Path,
) -> None:
    (local,) = [c for c in list_connections(config_path) if c.name == "local"]

    delete_connection(local)

    config = ConfigFile(config_path).relevant_config
    assert "default_profile" not in config
    assert list(config["profiles"]) == ["staging"]


def test_edit_and_delete_use_the_file_that_defines_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    near = tmp_path / "harlequin.toml"
    near.write_text('[profiles.shared]\nadapter = "duckdb"\nconn_str = ["near.db"]\n')
    far_directory = tmp_path / "far"
    far_directory.mkdir()
    far = far_directory / "harlequin.toml"
    monkeypatch.setattr(
        "harlequin.config._search_directories",
        lambda: [(far_directory, ("harlequin.toml",))],
    )
    far.write_text(
        '[profiles.shared]\nadapter = "duckdb"\nconn_str = ["far.db"]\n'
        '[profiles.only_far]\nadapter = "duckdb"\n'
    )

    connections = {c.name: c for c in list_connections(near)}

    assert connections["shared"].path == near
    assert connections["only_far"].path == far
    delete_connection(connections["only_far"])
    assert "only_far" not in far.read_text()
    assert "shared" in near.read_text()
