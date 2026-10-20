"""The overlay used for dry runs: it behaves like a vault (contract tests) and never changes
the vault underneath."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.adapters.overlay_vault import OverlayVault
from notebook_assistant.ports.vault import VaultError

P = PurePosixPath


def snapshot(store: FsVault) -> dict[str, bytes]:
    return {p.as_posix(): store.read_bytes(p) for p in store.iter_files()}


def test_writes_moves_and_deletes_stay_in_the_overlay(fs_vault: FsVault) -> None:
    before = snapshot(fs_vault)
    overlay = OverlayVault(fs_vault)
    overlay.write_text(P("10-Tasks/New.md"), "new")
    overlay.write_text(P("30-SOPs/SOP - Install uv (Linux).md"), "changed")
    overlay.move(P("10-Tasks/Learn Kedro hooks.md"), P("10-Tasks/Kedro hooks.md"))
    overlay.delete(P("01-Daily/2026-09-27.md"))
    assert overlay.read_text(P("30-SOPs/SOP - Install uv (Linux).md")) == "changed"
    assert not overlay.exists(P("01-Daily/2026-09-27.md"))
    listed = {p.as_posix() for p in overlay.iter_files()}
    assert {"10-Tasks/New.md", "10-Tasks/Kedro hooks.md"} <= listed
    assert "10-Tasks/Learn Kedro hooks.md" not in listed
    assert snapshot(fs_vault) == before  # the real vault is untouched


def test_deleted_files_read_as_missing(fs_vault: FsVault) -> None:
    overlay = OverlayVault(fs_vault)
    overlay.delete(P("01-Daily/2026-09-27.md"))
    with pytest.raises(VaultError):
        overlay.read_bytes(P("01-Daily/2026-09-27.md"))
    with pytest.raises(VaultError):
        overlay.delete(P("01-Daily/2026-09-27.md"))
    overlay.write_text(P("01-Daily/2026-09-27.md"), "back")
    assert overlay.read_text(P("01-Daily/2026-09-27.md")) == "back"
