from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harlequin.config import ConfigFile, Profile, discover_config_files
from harlequin.redact import redact_conn_str


@dataclass(frozen=True)
class ConnectionEntry:
    name: str
    adapter: str
    target: str
    path: Path
    is_default: bool
    profile: Profile


def describe_target(profile: Profile) -> str:
    conn_str = profile.get("conn_str")
    if conn_str:
        items = [conn_str] if isinstance(conn_str, str) else list(conn_str)
        return " ".join(redact_conn_str(items))
    host = profile.get("host")
    database = profile.get("database") or profile.get("dbname")
    if not host:
        return str(database) if database else ""
    port = profile.get("port")
    target = f"{host}:{port}" if port else str(host)
    return f"{target}/{database}" if database else target


def list_connections(config_path: Path | None = None) -> list[ConnectionEntry]:
    default_profile: str | None = None
    found: dict[str, tuple[Path, Profile]] = {}
    for path in discover_config_files(config_path):
        relevant_config = ConfigFile(path).relevant_config
        if default_profile is None:
            default_profile = relevant_config.get("default_profile")
        for name, profile in relevant_config.get("profiles", {}).items():
            found.setdefault(name, (path, profile))
    return [
        ConnectionEntry(
            name=name,
            adapter=str(profile.get("adapter", "duckdb")),
            target=describe_target(profile),
            path=path,
            is_default=name == default_profile,
            profile=profile,
        )
        for name, (path, profile) in sorted(found.items())
    ]


def save_connection(
    path: Path, name: str, profile: Profile, replacing: str | None = None
) -> None:
    config_file = ConfigFile(path)
    config = config_file.relevant_config
    profiles = config.setdefault("profiles", {})
    if replacing is not None and replacing != name:
        profiles.pop(replacing, None)
        if config.get("default_profile") == replacing:
            config["default_profile"] = name
    profiles[name] = dict(profile)
    config_file.update(config, whole_section=True)
    config_file.write()


def delete_connection(entry: ConnectionEntry) -> None:
    config_file = ConfigFile(entry.path)
    config = config_file.relevant_config
    config.get("profiles", {}).pop(entry.name, None)
    if config.get("default_profile") == entry.name:
        config.pop("default_profile")
    config_file.update(config, whole_section=True)
    config_file.write()
