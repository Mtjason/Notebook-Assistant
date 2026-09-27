"""Both storage adapters must behave identically (docs/architecture.md §5.4 contract tests)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from notebook_assistant.adapters.fs_vault import TEMP_SUFFIX, FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.ports.vault import FileExistsInVaultError, VaultError

Store = FsVault | MemoryVault
P = PurePosixPath


def test_iter_files_skips_dot_folders(any_vault: Store) -> None:
    any_vault.write_text(P(".obsidian/app.json"), "{}")
    files = [p.as_posix() for p in any_vault.iter_files()]
    assert "60-Knowledge/Software/MOC - Software.md" in files
    assert not any(f.startswith(".obsidian") for f in files)


def test_utf8_and_line_endings_round_trip(any_vault: Store) -> None:
    text = "---\ntype: daily\n---\r\n條件句 As if\r\nemoji 🧪\n"
    any_vault.write_text(P("01-Daily/2026-09-28.md"), text)
    assert any_vault.read_text(P("01-Daily/2026-09-28.md")) == text
    daily = any_vault.read_bytes(P("01-Daily/2026-09-27.md"))
    assert b"\r\n" in daily  # the fixture's CRLF note is stored untouched


def test_case_insensitive_lookup_keeps_spelling(any_vault: Store) -> None:
    assert any_vault.exists(P("10-tasks/learn kedro HOOKS.md"))
    any_vault.write_text(P("10-tasks/learn kedro hooks.md"), "x")
    names = [
        p.as_posix()
        for p in any_vault.iter_files()
        if "Kedro" in p.as_posix() or "kedro" in p.as_posix()
    ]
    assert names == ["10-Tasks/Learn Kedro hooks.md"]


def test_move_and_refuse_overwrite(any_vault: Store) -> None:
    src, dest = P("30-SOPs/SOP - Install uv.md"), P("30-SOPs/SOP - Install uv on Linux.md")
    any_vault.move(src, dest)
    assert any_vault.exists(dest) and not any_vault.exists(src)
    with pytest.raises(FileExistsInVaultError):
        any_vault.move(dest, P("10-Tasks/Learn Kedro hooks.md"))


def test_case_only_move(any_vault: Store) -> None:
    src = P("60-Knowledge/Software/Python os.execv.md")
    any_vault.move(src, P("60-Knowledge/Software/python OS.execv.md"))
    listed = [p.name for p in any_vault.iter_files() if p.name.lower() == "python os.execv.md"]
    assert listed == ["python OS.execv.md"]


def test_delete_and_missing(any_vault: Store) -> None:
    path = P("20-Projects/Demo/src/app.py")
    any_vault.delete(path)
    assert not any_vault.exists(path)
    with pytest.raises(VaultError):
        any_vault.read_bytes(path)


def test_fs_specifics(fs_vault: FsVault) -> None:
    fs_vault.write_text(P("New/Deep/note.md"), "x")
    assert not list(fs_vault.root.rglob(f"*{TEMP_SUFFIX}"))
    fs_vault.delete(P("New/Deep/note.md"))
    assert not (fs_vault.root / "New").exists()  # emptied folders are pruned
    fs_vault.delete(P("20-Projects/Demo/src/app.py"))
    assert (fs_vault.root / "20-Projects/Demo").is_dir()
    assert not (fs_vault.root / "20-Projects/Demo/src").exists()
    with pytest.raises(VaultError):
        fs_vault.read_bytes(P("../outside.md"))


def test_missing_vault_folder(tmp_path: Path) -> None:
    with pytest.raises(VaultError):
        FsVault(tmp_path / "nope")
