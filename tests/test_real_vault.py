"""Golden test against your real vault, run locally only.

Your notes never go into the repository. Point ``NA_REAL_VAULT`` at the vault (or a copy) to
run it, e.g. from WSL:

    NA_REAL_VAULT="/mnt/c/Users/user/Documents/Jason's Vault" uv run pytest tests/test_real_vault.py

It is read-only: it checks every note against the handbook and reports broken links.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.invariants import check_note

REAL = os.environ.get("NA_REAL_VAULT")
pytestmark = pytest.mark.skipif(not REAL, reason="set NA_REAL_VAULT to run against your vault")


def test_real_vault_is_compliant() -> None:
    assert REAL
    index = VaultIndex.build(FsVault(Path(REAL)))
    facts = index.facts()
    problems = {
        n.path.as_posix(): [f"{v.code} {v.message}" for v in check_note(n, facts)]
        for n in index.notes.values()
    }
    assert {p: v for p, v in problems.items() if v} == {}


def test_real_notes_render_back_byte_identical() -> None:
    """Parsing and re-rendering an untouched note must not change a single byte."""
    assert REAL
    index = VaultIndex.build(FsVault(Path(REAL)))
    changed = [n.path.as_posix() for n in index.notes.values() if n.render() != index.text(n.path)]
    assert changed == []
