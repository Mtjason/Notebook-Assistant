"""Host profile detection (docs/architecture.md §5.1), for every OS, on any OS."""

from __future__ import annotations

import pytest

from notebook_assistant.platform.profiles import (
    HostFacts,
    Profile,
    ProfileError,
    WatchMode,
    bitwarden_command,
    detect_profile,
    host_facts,
    is_wsl,
    parse_profile,
    watch_mode,
)

WINDOWS = HostFacts("win32", "10")
MAC = HostFacts("darwin", "23.4.0")
WSL = HostFacts("linux", "6.18.33.2-microsoft-standard-WSL2")
LINUX = HostFacts("linux", "6.8.0-45-generic")
VAULT_ON_C = "/mnt/c/Users/user/Documents/Jason's Vault"


@pytest.mark.parametrize(
    ("facts", "vault", "expected"),
    [
        (WINDOWS, r"C:\Users\user\Vault", Profile.WINDOWS),
        (MAC, "/Users/jason/Vault", Profile.MACOS),
        (WSL, VAULT_ON_C, Profile.WSL_DRVFS),
        (WSL, "/mnt/D/Vault", Profile.WSL_DRVFS),
        (WSL, "/home/user/vault", Profile.LINUX),  # a Linux filesystem inside WSL
        (WSL, "/mnt/wsl/shared", Profile.LINUX),  # not a drive letter
        (WSL, None, Profile.LINUX),
        (LINUX, "/mnt/c/vault", Profile.LINUX),  # not WSL: /mnt/c is just a folder
    ],
)
def test_profile_follows_the_host_and_where_the_vault_is(
    facts: HostFacts, vault: str | None, expected: Profile
) -> None:
    assert detect_profile(facts, vault) is expected


def test_an_override_wins_and_must_name_a_profile() -> None:
    assert detect_profile(WSL, VAULT_ON_C, override="linux") is Profile.LINUX
    assert parse_profile(" WSL-DRVFS ") is Profile.WSL_DRVFS
    with pytest.raises(ProfileError, match="unknown profile 'wsl'"):
        detect_profile(WSL, VAULT_ON_C, override="wsl")


def test_only_drvfs_polls_and_only_windows_uses_bw_exe() -> None:
    assert watch_mode(Profile.WSL_DRVFS) is WatchMode.POLLING
    assert {watch_mode(p) for p in Profile if p is not Profile.WSL_DRVFS} == {WatchMode.NATIVE}
    assert bitwarden_command(Profile.WINDOWS) == "bw.exe"
    assert bitwarden_command(Profile.MACOS) == "bw"


def test_host_facts_describe_this_host() -> None:
    facts = host_facts()
    assert facts.sys_platform and isinstance(facts.kernel_release, str)
    assert is_wsl(WSL) and not is_wsl(LINUX) and not is_wsl(WINDOWS)
