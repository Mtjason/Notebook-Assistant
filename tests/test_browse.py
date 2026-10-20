"""Read-only views for the app shell: counts, the note list, one note with backlinks."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.browse import counts, find_note, note_detail, summaries
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.rename import plan_move
from notebook_assistant.store import changesets as cs_store
from tests.conftest import NOW

P = PurePosixPath


def test_counts_inbox_digest_queue_and_pending_changesets(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    assert counts(index, memory_vault).review == 0
    inbox_files = sum(1 for p in index.files if p.parts[0] == "00-Inbox")
    assert counts(index, memory_vault).inbox == inbox_files >= 1
    memory_vault.write_text(PurePosixPath("00-Inbox/.keep"), "")  # holds the folder; no capture
    assert counts(VaultIndex.build(memory_vault), memory_vault).inbox == inbox_files
    memory_vault.write_text(
        P("60-Knowledge/Software/Draft.md"),
        "---\ntype: knowledge\ndigest: pending\n---\nstub\n",
    )
    src = P("60-Knowledge/Software/Polars with_columns.md")
    cs = plan_move(index, src, src.with_name("Polars cols.md"), reason="r", created_by="t", now=NOW)
    cs_store.save(memory_vault, cs)
    after = counts(VaultIndex.build(memory_vault), memory_vault)
    assert after.digest == 1 and after.review == 1


def test_summaries_list_notes_but_never_the_assistants_state(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(P("99-System/Assistant/Runs/2026-10.md"), "---\ntype: system\n---\n")
    listed = summaries(VaultIndex.build(memory_vault))
    paths = [s.path for s in listed]
    assert paths == sorted(paths) and not any(p.startswith("99-System/Assistant/") for p in paths)
    sop = next(s for s in listed if s.title == "SOP - Install uv (Linux)")
    assert sop.type == "sop" and sop.aliases == ["Install uv", "安裝 uv"]


def test_a_note_is_found_by_path_or_id_with_its_backlinks(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(
        P("60-Knowledge/Software/With id.md"),
        "---\nid: n-abc\ntype: knowledge\n---\nSee [[Polars with_columns]].\n",
    )
    index = VaultIndex.build(memory_vault)
    by_path = find_note(index, "60-knowledge/software/polars WITH_COLUMNS.md")
    assert by_path is not None and by_path.title == "Polars with_columns"
    by_id = find_note(index, "N-ABC")
    assert by_id is not None and by_id.title == "With id"
    assert find_note(index, "missing.md") is None
    detail = note_detail(index, by_path)
    assert "60-Knowledge/Software/With id.md" in detail.backlinks
    assert detail.path not in detail.backlinks and detail.props["type"] == "knowledge"
