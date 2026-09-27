from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def load_fixture_memory() -> MemoryVault:
    files: dict[str, str | bytes] = {}
    for path in FIXTURE_VAULT.rglob("*"):
        if path.is_file():
            files[path.relative_to(FIXTURE_VAULT).as_posix()] = path.read_bytes()
    return MemoryVault(files)


@pytest.fixture
def fs_vault(tmp_path: Path) -> FsVault:
    """A writable copy of the fixture vault on disk."""
    root = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, root)
    return FsVault(root)


@pytest.fixture
def memory_vault() -> MemoryVault:
    return load_fixture_memory()


@pytest.fixture(params=["fs", "memory"])
def any_vault(request: pytest.FixtureRequest, tmp_path: Path) -> FsVault | MemoryVault:
    """Both adapters, so every behaviour is checked on each (contract tests)."""
    if request.param == "memory":
        return load_fixture_memory()
    root = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, root)
    return FsVault(root)
