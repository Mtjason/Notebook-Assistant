"""serve: picks the vault and port, binds to 127.0.0.1 only, and refuses without a vault."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from notebook_assistant import cli
from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.api.server import default_web_dir
from notebook_assistant.machine import DEFAULT_PORT, load_machine_config, save_machine_config
from notebook_assistant.platform.profiles import Profile


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append({"app": app, **kw}))
    return calls


def test_serve_binds_locally_on_the_configured_port(
    fs_vault: FsVault, served: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve", "--vault", str(fs_vault.root)]) == 0
    [call] = served
    assert call["host"] == "127.0.0.1" and call["port"] == DEFAULT_PORT
    assert call["timeout_graceful_shutdown"] == cli.SHUTDOWN_SECONDS  # open tabs can't block a stop
    assert f"http://127.0.0.1:{DEFAULT_PORT}" in capsys.readouterr().out
    assert cli.main(["serve", "--vault", str(fs_vault.root), "--port", "9100"]) == 0
    assert served[-1]["port"] == 9100


def test_serve_uses_the_configured_vault(fs_vault: FsVault, served: list[dict[str, Any]]) -> None:
    machine = load_machine_config(profile=Profile.LINUX, bitwarden_found=False)
    save_machine_config(type(machine)(machine.machine_id, machine.name, vault=str(fs_vault.root)))
    assert cli.main(["serve"]) == 0 and len(served) == 1


def test_serve_refuses_without_a_vault(
    tmp_path: Path, served: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve"]) == 2 and "no vault" in capsys.readouterr().err
    assert cli.main(["serve", "--vault", str(tmp_path / "nope")]) == 2
    assert "no such vault folder" in capsys.readouterr().err
    assert cli.main(["serve", "--vault", str(tmp_path), "--profile", "dos"]) == 1
    assert served == []


def test_default_web_dir_is_none_or_holds_index_html() -> None:
    found = default_web_dir()
    assert found is None or (found / "index.html").is_file()
