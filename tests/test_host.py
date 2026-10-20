"""Resolving this install: machine config plus profile, in the §5.1 order of precedence."""

from __future__ import annotations

import pytest

from notebook_assistant import host as host_module
from notebook_assistant.host import current_host
from notebook_assistant.machine import load_machine_config, save_machine_config
from notebook_assistant.platform.profiles import HostFacts, Profile, ProfileError, WatchMode

WSL = HostFacts("linux", "6.18.33.2-microsoft-standard-WSL2")
VAULT_ON_C = "/mnt/c/Users/user/Vault"


@pytest.fixture(autouse=True)
def _wsl_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_module, "host_facts", lambda: WSL)
    monkeypatch.delenv("NA_PROFILE", raising=False)


def test_detection_from_the_vault_location() -> None:
    host = current_host(VAULT_ON_C)
    assert host.profile is Profile.WSL_DRVFS and host.watch is WatchMode.POLLING
    assert host.machine.name.endswith("-wsl-drvfs")
    assert current_host("/home/user/vault").profile is Profile.LINUX


def test_the_configured_vault_is_used_when_none_is_given() -> None:
    machine = load_machine_config(profile=Profile.LINUX, bitwarden_found=False)
    save_machine_config(type(machine)(machine.machine_id, machine.name, vault=VAULT_ON_C))
    assert current_host(None).profile is Profile.WSL_DRVFS


def test_flag_beats_environment_beats_config_beats_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = load_machine_config(profile=Profile.LINUX, bitwarden_found=False)
    save_machine_config(type(machine)(machine.machine_id, machine.name, profile=Profile.MACOS))
    assert current_host(VAULT_ON_C).profile is Profile.MACOS
    monkeypatch.setenv("NA_PROFILE", "linux")
    assert current_host(VAULT_ON_C).profile is Profile.LINUX
    assert current_host(VAULT_ON_C, profile_flag="windows").profile is Profile.WINDOWS
    with pytest.raises(ProfileError):
        current_host(VAULT_ON_C, profile_flag="dos")


def test_bitwarden_is_found_on_path_or_reported_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    found = current_host(VAULT_ON_C)
    assert found.bitwarden_path == "/usr/bin/bw" and found.machine.bitwarden
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert current_host(VAULT_ON_C).bitwarden_path is None
