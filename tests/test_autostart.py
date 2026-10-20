"""Start at login: the entry each profile registers, and installing and removing it."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from notebook_assistant import cli
from notebook_assistant.platform import autostart
from notebook_assistant.platform.autostart import AutostartError, Plan, apply, plan
from notebook_assistant.platform.profiles import Profile

ARGV = ["/opt/py/bin/python", "-m", "notebook_assistant", "serve", "--vault", "/mnt/c/My Vault"]


def test_windows_registers_a_logon_task(tmp_path: Path) -> None:
    entry = plan(Profile.WINDOWS, ARGV, home=tmp_path, distro=None)
    [create] = entry.install
    assert create[:2] == ["schtasks", "/Create"] and "ONLOGON" in create
    assert create[-1] == '/opt/py/bin/python -m notebook_assistant serve --vault "/mnt/c/My Vault"'
    assert entry.remove == [["schtasks", "/Delete", "/TN", "notebook-assistant", "/F"]]
    assert entry.file is None


def test_wsl_asks_windows_to_start_the_distro(tmp_path: Path) -> None:
    entry = plan(Profile.WSL_DRVFS, ARGV, home=tmp_path, distro="Ubuntu")
    command = entry.install[0][-1]
    assert entry.install[0][0] == "schtasks.exe"
    assert command.startswith("wsl.exe -d Ubuntu -- /opt/py/bin/python -m notebook_assistant")
    with pytest.raises(AutostartError, match="WSL_DISTRO_NAME"):
        plan(Profile.WSL_DRVFS, ARGV, home=tmp_path, distro=None)


def test_linux_writes_a_systemd_user_unit(tmp_path: Path) -> None:
    entry = plan(Profile.LINUX, ARGV, home=tmp_path, distro=None)
    assert entry.file == tmp_path / ".config/systemd/user/notebook-assistant.service"
    assert (
        "ExecStart=/opt/py/bin/python -m notebook_assistant serve --vault '/mnt/c/My Vault'"
        in entry.content
    )
    assert "WantedBy=default.target" in entry.content
    assert ["systemctl", "--user", "enable", "--now", "notebook-assistant.service"] in entry.install


def test_macos_writes_a_launch_agent(tmp_path: Path) -> None:
    entry = plan(Profile.MACOS, ARGV, home=tmp_path, distro=None)
    assert entry.file is not None and entry.file.parent == tmp_path / "Library/LaunchAgents"
    agent = plistlib.loads(entry.content.encode("utf-8"))
    assert agent["ProgramArguments"] == ARGV and agent["RunAtLoad"] is True
    assert entry.install == [["launchctl", "load", "-w", str(entry.file)]]


def test_apply_writes_then_runs_and_removes_then_deletes(tmp_path: Path) -> None:
    ran: list[list[str]] = []
    entry = Plan(Profile.LINUX, tmp_path / "a" / "unit", "content", [["on"]], [["off"]])
    apply(entry, install=True, run=ran.append)
    assert entry.file is not None and entry.file.read_text(encoding="utf-8") == "content"
    apply(entry, install=False, run=ran.append)
    assert ran == [["on"], ["off"]] and not entry.file.exists()

    def failing(command: list[str]) -> None:
        raise subprocess.CalledProcessError(1, command)

    with pytest.raises(subprocess.CalledProcessError):
        apply(Plan(Profile.WINDOWS, install=[["x"]]), install=True, run=failing)


def test_the_command_needs_a_vault_and_reports_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    applied: list[tuple[Plan, bool]] = []
    monkeypatch.setattr(autostart, "apply", lambda entry, install: applied.append((entry, install)))
    assert cli.main(["autostart", "install", "--profile", "linux"]) == 2  # no vault anywhere
    assert cli.main(["autostart", "install", "--vault", str(tmp_path), "--profile", "linux"]) == 0
    entry, install = applied[-1]
    assert install and entry.profile is Profile.LINUX and str(tmp_path) in entry.content
    assert sys.executable in entry.content
    assert cli.main(["autostart", "remove", "--profile", "linux"]) == 0 and not applied[-1][1]
    monkeypatch.setattr(autostart, "wsl_distro", lambda: None)
    assert (
        cli.main(["autostart", "install", "--vault", str(tmp_path), "--profile", "wsl-drvfs"]) == 1
    )
    assert "WSL_DISTRO_NAME" in capsys.readouterr().err


def test_python_dash_m_runs_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "notebook_assistant", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert result.stdout.strip()
