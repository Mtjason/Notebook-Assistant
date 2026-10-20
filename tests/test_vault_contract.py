"""Both storage adapters must behave identically (docs/architecture.md §5.4 contract tests)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import pytest

from notebook_assistant.adapters.fs_vault import TEMP_SUFFIX, FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.adapters.overlay_vault import OverlayVault
from notebook_assistant.ports.vault import FileExistsInVaultError, VaultError

Store = FsVault | MemoryVault | OverlayVault
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
    assert any_vault.read_text(P("10-Tasks/Learn Kedro hooks.md")) == "x"


def test_new_file_uses_existing_folder_spelling(any_vault: Store) -> None:
    any_vault.write_text(P("10-tasks/New task.md"), "x")
    any_vault.move(P("30-SOPs/SOP - Install uv (Linux).md"), P("10-TASKS/SOP moved.md"))
    tasks = sorted(p.as_posix() for p in any_vault.iter_files() if p.parts[0].lower() == "10-tasks")
    assert tasks == [
        "10-Tasks/Learn Kedro hooks.md",
        "10-Tasks/New task.md",
        "10-Tasks/SOP moved.md",
    ]


def test_move_and_refuse_overwrite(any_vault: Store) -> None:
    src, dest = P("30-SOPs/SOP - Install uv (Linux).md"), P("30-SOPs/SOP - Install uv on Linux.md")
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


def test_modified_is_when_the_content_was_last_written(any_vault: Store) -> None:
    path = P("00-Inbox/new.md")
    before = datetime.now(UTC) - timedelta(seconds=5)
    any_vault.write_text(path, "x")
    written = any_vault.modified(path)
    assert written.tzinfo is not None and written >= before
    any_vault.move(path, P("00-Inbox/moved.md"))  # a move keeps it
    assert abs((any_vault.modified(P("00-Inbox/moved.md")) - written).total_seconds()) < 1
    assert any_vault.modified(P("00-Inbox/raw capture.md")) <= datetime.now(UTC)
    with pytest.raises(VaultError):
        any_vault.modified(P("nowhere.md"))


def test_the_memory_clock_stamps_writes() -> None:
    when = datetime(2026, 1, 1, tzinfo=UTC)
    vault = MemoryVault({"a.md": "x"}, clock=lambda: when)
    assert vault.modified(P("a.md")) == when
    vault.delete(P("a.md"))
    assert not vault.exists(P("a.md"))
