"""doctor: each check, and the command's exit code (architecture §5.5)."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from notebook_assistant import cli
from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.doctor import (
    WRITE_TEST,
    Check,
    Status,
    check_bitwarden,
    check_claude_api,
    check_config,
    check_encoding,
    check_profile,
    check_search,
    check_vault,
    run_checks,
    worst,
)
from notebook_assistant.domain.config import ConfigError
from notebook_assistant.host import Host
from notebook_assistant.machine import MachineConfig
from notebook_assistant.platform.profiles import Profile
from notebook_assistant.ports.llm import LLMError
from notebook_assistant.ports.vault import VaultError

HOST = Host(MachineConfig("id", "test-pc"), Profile.WSL_DRVFS)


def test_profile_and_search_report_this_host() -> None:
    assert check_profile(HOST).detail == "wsl-drvfs · file changes: polling · machine: test-pc"
    assert check_search(HOST).status is Status.OK


def test_encoding_must_be_utf8() -> None:
    assert check_encoding(True, "cp950").status is Status.OK
    assert check_encoding(False, "UTF-8").status is Status.OK
    failed = check_encoding(False, "cp950")
    assert failed.status is Status.FAIL and "PYTHONUTF8=1" in failed.detail


def test_vault_write_test_cleans_up_and_reports_failures() -> None:
    store = MemoryVault()
    assert check_vault(store, "v").status is Status.OK and not store.exists(WRITE_TEST)
    assert check_vault(None, None).status is Status.FAIL

    class ReadOnly(MemoryVault):
        def write_text(self, path: PurePosixPath, text: str) -> None:
            raise VaultError("read-only")

    assert check_vault(ReadOnly(), "v").status is Status.FAIL


def test_config_and_api_failures_are_reported() -> None:
    assert check_config(lambda: None).status is Status.OK

    def broken() -> None:
        raise ConfigError("Config.md: unknown section(s): limts")

    assert "limts" in check_config(broken).detail
    assert check_claude_api(lambda: 13).detail.endswith("13 models")

    def offline() -> int:
        raise LLMError("can't reach the Claude API")

    assert check_claude_api(offline) == Check(
        "Claude API", Status.FAIL, "can't reach the Claude API"
    )


def test_bitwarden_off_found_or_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check_bitwarden(HOST).status is Status.OK  # disabled
    enabled = Host(MachineConfig("id", "pc", bitwarden=True), Profile.LINUX)
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert check_bitwarden(enabled).status is Status.WARN
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/bw")
    assert check_bitwarden(enabled).detail == "/usr/bin/bw"


def test_run_checks_skips_config_without_a_writable_vault_and_worst_wins() -> None:
    names = [
        c.name
        for c in run_checks(HOST, None, None, load_config=lambda: None, count_models=lambda: 1)
    ]
    assert "Config.md" not in names and "vault" in names
    checks = run_checks(HOST, MemoryVault(), "v", load_config=lambda: None, count_models=lambda: 1)
    assert "Config.md" in [c.name for c in checks]
    assert worst([Check("a", Status.OK, ""), Check("b", Status.WARN, "")]) is Status.WARN
    assert worst([]) is Status.OK


def test_the_command_exits_1_on_any_failure(
    fs_vault: FsVault, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "count_models", lambda: 13)
    assert cli.main(["doctor", "--vault", str(fs_vault.root)]) == 0
    assert "✓ vault" in capsys.readouterr().out
    assert cli.main(["doctor", "--vault", str(fs_vault.root / "missing")]) == 1
    assert "✗ vault" in capsys.readouterr().out
    assert cli.main(["doctor", "--profile", "dos"]) == 1
    assert "unknown profile 'dos'" in capsys.readouterr().err
