"""The per-machine config.yaml: created on first run, strict when loaded (architecture §4.1.1)."""

from __future__ import annotations

import re
import uuid

import pytest

from notebook_assistant.machine import (
    MachineConfig,
    MachineConfigError,
    config_dir,
    config_path,
    default_name,
    load_machine_config,
    parse_machine_config,
    render_machine_config,
    save_machine_config,
)
from notebook_assistant.platform.profiles import Profile


def test_first_run_creates_the_file_with_a_new_machine_id() -> None:
    assert not config_path().exists()
    first = load_machine_config(profile=Profile.WSL_DRVFS, bitwarden_found=True)
    assert config_path().is_file() and config_path().parent == config_dir()
    assert uuid.UUID(first.machine_id) and first.name.endswith("-wsl-drvfs")
    assert first.bitwarden and first.vault is None and first.profile is None
    again = load_machine_config(profile=Profile.LINUX, bitwarden_found=False)
    assert again == first  # the file wins once it exists


def test_round_trip_through_the_file() -> None:
    config = MachineConfig("id-1", "work-pc", "/mnt/c/Vault", Profile.LINUX, False, "keyword")
    save_machine_config(config)
    text = config_path().read_text(encoding="utf-8")
    assert text.startswith("# This PC's notebook-assistant settings")
    assert (
        parse_machine_config(text) == config == parse_machine_config(render_machine_config(config))
    )


def test_default_name_is_the_hostname_and_profile() -> None:
    assert re.fullmatch(r"[a-z0-9-]+-macos", default_name(Profile.MACOS))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[1]", "must be a mapping"),
        ("machine_id: a\nname: b\ncolour: red\n", "unknown setting(s): colour"),
        ("name: b\n", "machine_id and name are required"),
        ("machine_id: a\nname: 3\n", "name must be str, not 3"),
        ("machine_id: a\nname: b\nprofile: wsl\n", "unknown profile 'wsl'"),
        ("machine_id: a\nname: b\nsearch: vectors\n", "search must be one of keyword"),
        ("machine_id: a\nname: b\nfeatures: {bitwarden: yes}\n", "bitwarden must be bool"),
        ("machine_id: a\nname: b\nfeatures: {clipboard: true}\n", "features may hold only"),
        ("machine_id: [\n", "invalid YAML"),
    ],
)
def test_mistakes_fail_loudly(text: str, message: str) -> None:
    with pytest.raises(MachineConfigError, match=re.escape(message)):
        parse_machine_config(text)
