"""This installation's own settings: ``config.yaml`` in the OS config directory
(docs/architecture.md §4.1.1, §5.3). They never sync; the vault's ``Config.md`` holds what does.

On first run the file is created with a new ``machine_id`` (a UUID, never derived from the
hostname, so a WSL and a Windows install on one PC are two machines) and a friendly ``name`` you
may edit. Loading is strict, like ``Config.md``: an unknown key or a wrong type stops with
:class:`MachineConfigError` naming it. ``NA_CONFIG_DIR`` moves the folder, e.g. for tests.
"""

from __future__ import annotations

import os
import re
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import platformdirs
import yaml

from notebook_assistant.domain.frontmatter import load_yaml
from notebook_assistant.platform.profiles import Profile, ProfileError, parse_profile

APP_NAME = "notebook-assistant"
FILE_NAME = "config.yaml"
SEARCH_OPTIONS = ("keyword",)  # the per-PC search backends that exist (embeddings: branch 11)
DEFAULT_PORT = 8765


class MachineConfigError(ValueError):
    """``config.yaml`` has an unknown key or a value of the wrong type."""


@dataclass(frozen=True)
class MachineConfig:
    machine_id: str
    name: str  # friendly name shown in the UI and recorded on changesets
    vault: str | None = None  # the vault this install serves by default
    profile: Profile | None = None  # overrides detection (§5.1)
    bitwarden: bool = False  # features.bitwarden: whether credential cards may use `bw`
    search: str = SEARCH_OPTIONS[0]
    port: int = DEFAULT_PORT  # `serve` listens on 127.0.0.1 at this port


def config_dir() -> Path:
    override = os.environ.get("NA_CONFIG_DIR")
    return Path(override) if override else Path(platformdirs.user_config_dir(APP_NAME, False))


def config_path() -> Path:
    return config_dir() / FILE_NAME


def default_name(profile: Profile) -> str:
    """A readable machine name: the hostname and the profile, e.g. ``laptop-wsl-drvfs``."""
    host = re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()).strip("-") or "pc"
    return f"{host}-{profile.value}"


def _value(data: dict[str, Any], key: str, kind: type, where: str = "") -> Any:
    """``data[key]`` if it has type ``kind`` (``True`` is not an int here), None if absent."""
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) is not (kind is bool) or not isinstance(value, kind):
        raise MachineConfigError(
            f"config.yaml: {where}{key} must be {kind.__name__}, not {value!r}"
        )
    return value


def parse_machine_config(text: str) -> MachineConfig:
    try:
        data = load_yaml(text) or {}
    except yaml.YAMLError as exc:
        raise MachineConfigError(f"config.yaml: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise MachineConfigError("config.yaml must be a mapping")
    unknown = sorted(
        set(data) - {"machine_id", "name", "vault", "profile", "features", "search", "port"}
    )
    if unknown:
        raise MachineConfigError(f"config.yaml: unknown setting(s): {', '.join(unknown)}")
    features = data.get("features") or {}
    if not isinstance(features, dict) or set(features) - {"bitwarden"}:
        raise MachineConfigError("config.yaml: features may hold only bitwarden")
    machine_id = _value(data, "machine_id", str)
    name = _value(data, "name", str)
    if not machine_id or not name:
        raise MachineConfigError("config.yaml: machine_id and name are required")
    profile = _value(data, "profile", str)
    search = _value(data, "search", str) or SEARCH_OPTIONS[0]
    if search not in SEARCH_OPTIONS:
        raise MachineConfigError(f"config.yaml: search must be one of {', '.join(SEARCH_OPTIONS)}")
    try:
        parsed_profile = parse_profile(profile) if profile else None
    except ProfileError as exc:
        raise MachineConfigError(f"config.yaml: {exc}") from None
    port = _value(data, "port", int) or DEFAULT_PORT
    if not 1024 <= port <= 65535:
        raise MachineConfigError(f"config.yaml: port must be between 1024 and 65535, not {port}")
    return MachineConfig(
        machine_id=machine_id,
        name=name,
        vault=_value(data, "vault", str),
        profile=parsed_profile,
        bitwarden=bool(_value(features, "bitwarden", bool, "features.")),
        search=search,
        port=port,
    )


def render_machine_config(config: MachineConfig) -> str:
    data = {
        "machine_id": config.machine_id,
        "name": config.name,
        "vault": config.vault,
        "profile": config.profile.value if config.profile else None,
        "features": {"bitwarden": config.bitwarden},
        "search": config.search,
        "port": config.port,
    }
    header = (
        "# This PC's notebook-assistant settings (docs/architecture.md §4.1.1). Never synced.\n"
        "# profile: leave empty to detect it (§5.1); vault: the vault `serve` opens by default.\n"
    )
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def load_machine_config(*, profile: Profile, bitwarden_found: bool) -> MachineConfig:
    """This install's config, creating it on first run (a new ``machine_id``; ``bitwarden`` on
    when ``bw`` is on ``PATH``)."""
    path = config_path()
    if path.is_file():
        return parse_machine_config(path.read_text(encoding="utf-8"))
    config = MachineConfig(
        machine_id=str(uuid.uuid4()), name=default_name(profile), bitwarden=bitwarden_found
    )
    save_machine_config(config)
    return config


def save_machine_config(config: MachineConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_machine_config(config), encoding="utf-8")
