"""Start the service at login, per host profile (docs/architecture.md §5.1, "Start at login").

:func:`plan` is pure: it says which file to write (if any) and which commands to run to install
or remove the entry. :func:`apply` carries a plan out. Keeping them apart means every profile's
entry is tested on any OS, and only :func:`apply` touches the system.

| Profile | Mechanism |
|---|---|
| windows | Task Scheduler task at logon (``schtasks``) |
| wsl-drvfs | Windows Task Scheduler running ``wsl.exe -d <distro> -- …`` |
| linux | systemd user unit, enabled for the login session |
| macos | launchd LaunchAgent with ``RunAtLoad`` |
"""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from notebook_assistant.platform.profiles import Profile

TASK_NAME = "notebook-assistant"
UNIT_NAME = "notebook-assistant.service"
AGENT_LABEL = "com.notebook-assistant.serve"


class AutostartError(RuntimeError):
    """The profile can't register a login entry here (e.g. WSL without a distro name)."""


@dataclass(frozen=True)
class Plan:
    profile: Profile
    file: Path | None = None  # written on install, deleted on remove
    content: str = ""
    install: list[list[str]] = field(default_factory=list)  # commands, run in order
    remove: list[list[str]] = field(default_factory=list)


def wsl_distro() -> str | None:
    """The WSL distro this runs in, which Windows' ``wsl.exe -d`` needs (None outside WSL)."""
    return os.environ.get("WSL_DISTRO_NAME")


def _windows_command(argv: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(argv))


def plan(profile: Profile, argv: Sequence[str], *, home: Path, distro: str | None) -> Plan:
    """The login entry that runs ``argv`` (the ``serve`` command line) on this profile."""
    if profile is Profile.WINDOWS:
        return Plan(
            profile,
            install=[
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    TASK_NAME,
                    "/SC",
                    "ONLOGON",
                    "/RL",
                    "LIMITED",
                    "/F",
                    "/TR",
                    _windows_command(argv),
                ]
            ],
            remove=[["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]],
        )
    if profile is Profile.WSL_DRVFS:
        if not distro:
            raise AutostartError("WSL_DISTRO_NAME isn't set; run this inside the WSL distro")
        command = _windows_command(["wsl.exe", "-d", distro, "--", *argv])
        return Plan(
            profile,
            install=[
                [
                    "schtasks.exe",
                    "/Create",
                    "/TN",
                    TASK_NAME,
                    "/SC",
                    "ONLOGON",
                    "/RL",
                    "LIMITED",
                    "/F",
                    "/TR",
                    command,
                ]
            ],
            remove=[["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"]],
        )
    if profile is Profile.LINUX:
        unit = (
            "[Unit]\nDescription=notebook-assistant (local service and web app)\n\n"
            f"[Service]\nExecStart={shlex.join(argv)}\nRestart=on-failure\n\n"
            "[Install]\nWantedBy=default.target\n"
        )
        systemctl = ["systemctl", "--user"]
        return Plan(
            profile,
            file=home / ".config" / "systemd" / "user" / UNIT_NAME,
            content=unit,
            install=[[*systemctl, "daemon-reload"], [*systemctl, "enable", "--now", UNIT_NAME]],
            remove=[[*systemctl, "disable", "--now", UNIT_NAME], [*systemctl, "daemon-reload"]],
        )
    agent = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
    content = plistlib.dumps(
        {"Label": AGENT_LABEL, "ProgramArguments": list(argv), "RunAtLoad": True}
    ).decode("utf-8")
    return Plan(
        profile,
        file=agent,
        content=content,
        install=[["launchctl", "load", "-w", str(agent)]],
        remove=[["launchctl", "unload", "-w", str(agent)]],
    )


Runner = Callable[[list[str]], None]


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def apply(entry: Plan, *, install: bool, run: Runner = run_command) -> None:
    """Install or remove the entry; a failing command raises ``CalledProcessError``."""
    if install and entry.file is not None:
        entry.file.parent.mkdir(parents=True, exist_ok=True)
        entry.file.write_text(entry.content, encoding="utf-8")
    for command in entry.install if install else entry.remove:
        run(command)
    if not install and entry.file is not None:
        entry.file.unlink(missing_ok=True)
