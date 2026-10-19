"""Host profiles (docs/architecture.md §5.1): which OS family this install runs on.

:func:`detect_profile` is a pure function of :class:`HostFacts`, so every rule is tested on any
OS; :func:`host_facts` is the one place that reads the real host. A profile can be forced with
``--profile`` or ``NA_PROFILE`` (e.g. polling on a network drive), or in the per-machine config.
"""

from __future__ import annotations

import platform
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class Profile(StrEnum):
    WINDOWS = "windows"
    WSL_DRVFS = "wsl-drvfs"
    LINUX = "linux"
    MACOS = "macos"


class WatchMode(StrEnum):
    NATIVE = "native"  # the OS's change notifications, through watchfiles
    POLLING = "polling"  # mtime and hash, because notifications don't cross the WSL bridge


class ProfileError(ValueError):
    """An override names no known profile."""


@dataclass(frozen=True)
class HostFacts:
    sys_platform: str  # sys.platform
    kernel_release: str  # platform.release(); contains "microsoft" under WSL


_DRVFS = re.compile(r"^/mnt/[a-z]/", re.I)


def host_facts() -> HostFacts:
    return HostFacts(sys.platform, platform.release())


def parse_profile(name: str) -> Profile:
    try:
        return Profile(name.strip().lower())
    except ValueError:
        known = ", ".join(p.value for p in Profile)
        raise ProfileError(f"unknown profile {name!r}; expected one of {known}") from None


def is_wsl(facts: HostFacts) -> bool:
    return facts.sys_platform.startswith("linux") and "microsoft" in facts.kernel_release.lower()


def detect_profile(facts: HostFacts, vault: str | None, override: str | None = None) -> Profile:
    """The profile for this host and vault (§5.1); ``override`` wins when given."""
    if override:
        return parse_profile(override)
    if facts.sys_platform == "win32":
        return Profile.WINDOWS
    if facts.sys_platform == "darwin":
        return Profile.MACOS
    vault_on_windows_drive = vault is not None and bool(
        _DRVFS.match(PurePosixPath(vault).as_posix() + "/")
    )
    if is_wsl(facts) and vault_on_windows_drive:
        return Profile.WSL_DRVFS
    return Profile.LINUX


def watch_mode(profile: Profile) -> WatchMode:
    """How file changes are noticed: Windows programs' edits never reach inotify over drvfs."""
    return WatchMode.POLLING if profile is Profile.WSL_DRVFS else WatchMode.NATIVE


def bitwarden_command(profile: Profile) -> str:
    """The Bitwarden CLI's executable name on ``PATH``."""
    return "bw.exe" if profile is Profile.WINDOWS else "bw"
