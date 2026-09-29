from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset, undo_changeset
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.rename import PlanError, plan_move
from notebook_assistant.domain.changeset import Changeset, Operation, Status
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.invariants import check_note
from notebook_assistant.domain.note import Note
from tests.conftest import NOW

P = PurePosixPath
Store = FsVault | MemoryVault
POLARS = P("60-Knowledge/Software/Polars with_columns.md")


def plan(store: Store, src: P, dest: P) -> Changeset:
    return plan_move(VaultIndex.build(store), src, dest, reason="test", created_by="test", now=NOW)


def snapshot(store: Store) -> dict[str, bytes]:
    return {p.as_posix(): store.read_bytes(p) for p in store.iter_files()}


def test_rename_rewrites_every_reference(any_vault: Store) -> None:
    before = snapshot(any_vault)
    new = P("60-Knowledge/Software/Polars with_columns expressions.md")
    cs = plan(any_vault, POLARS, new)
    result = apply_changeset(any_vault, cs, now=NOW)
    assert result.ok, result.error

    moc = any_vault.read_text(P("60-Knowledge/Software/MOC - Software.md"))
    assert "- [[Polars with_columns expressions]] — adding columns" in moc
    assert "[[Polars with_columns expressions#Chaining|chaining columns]]" in moc
    assert "[[60-Knowledge/Software/Polars with_columns expressions\\|with_columns]]" in moc
    assert "[[Not a link]]" in moc and "`[[Also not a link]]`" in moc  # code untouched

    execv = any_vault.read_text(P("60-Knowledge/Software/Python os.execv.md"))
    assert "[[Polars with_columns expressions|polars]]" in execv

    daily = any_vault.read_bytes(P("01-Daily/2026-09-27.md"))
    assert b"[[Polars with_columns expressions#Chaining]]\r\n" in daily  # CRLF kept

    canvas = json.loads(any_vault.read_text(P("60-Knowledge/Software/Software map.canvas")))
    assert canvas["nodes"][0]["file"] == new.as_posix()
    assert canvas["nodes"][1]["text"] == "Start at [[Polars with_columns expressions]]"

    moved = Note.parse(new, any_vault.read_text(new))
    assert moved.prop("aliases") == ["with_columns", "Polars with_columns"]
    assert moved.prop("id") == "n-fixture-polars"  # existing id kept

    index = VaultIndex.build(any_vault)
    assert index.broken == []
    facts = index.facts()
    assert all(check_note(n, facts) == [] for n in index.notes.values())

    undone = undo_changeset(any_vault, cs, now=NOW)
    assert undone.ok and cs.status is Status.REVERTED
    assert snapshot(any_vault) == before


def test_move_to_other_folder_fixes_relative_links(any_vault: Store) -> None:
    dest = P("60-Knowledge/Data Science/Polars with_columns.md")
    cs = plan(any_vault, POLARS, dest)
    assert apply_changeset(any_vault, cs, now=NOW).ok
    text = any_vault.read_text(dest)
    # same depth, so the relative path to Attachments is unchanged
    assert "(../../Attachments/Polars%20with_columns%20-%201.png)" in text
    assert "aliases: [with_columns]" in text  # title unchanged → no alias added
    assert VaultIndex.build(any_vault).broken == []


def test_move_at_the_same_depth_keeps_the_relative_link(memory_vault: MemoryVault) -> None:
    """`../../Attachments/…` still resolves from 20-Projects/Demo/, so the note isn't rewritten."""
    cs = plan(memory_vault, POLARS, P("20-Projects/Demo/Polars with_columns.md"))
    moved = next(op for op in cs.ops if op.kind == "move")
    assert moved.content is None


def test_plan_rewrites_a_relative_link_when_the_note_moves_deeper(
    memory_vault: MemoryVault,
) -> None:
    cs = plan(memory_vault, POLARS, P("20-Projects/Demo/notes/Polars with_columns.md"))
    moved = next(op for op in cs.ops if op.kind == "move")
    assert moved.content is not None
    assert "(../../../Attachments/Polars%20with_columns%20-%201.png)" in moved.content


def test_apply_refuses_a_move_that_breaks_a_rule(memory_vault: MemoryVault) -> None:
    """A knowledge note doesn't belong in a project container (Handbook §2.1, I-2)."""
    before = snapshot(memory_vault)
    cs = plan(memory_vault, POLARS, P("20-Projects/Demo/Polars with_columns.md"))
    result = apply_changeset(memory_vault, cs, now=NOW)
    assert not result.ok and cs.status is Status.FAILED
    assert result.error is not None and "would break handbook rules, rolled back" in result.error
    assert "I-2 type 'knowledge' doesn't belong in 20-Projects/Demo" in result.error
    assert snapshot(memory_vault) == before


def test_attachment_rename(any_vault: Store) -> None:
    src = P("Attachments/Polars with_columns - 1.png")
    dest = P("Attachments/Polars columns - 1.png")
    cs = plan(any_vault, src, dest)
    assert apply_changeset(any_vault, cs, now=NOW).ok
    text = any_vault.read_text(POLARS)
    assert "![[Polars columns - 1.png]]" in text
    assert "(../../Attachments/Polars%20columns%20-%201.png)" in text
    assert any_vault.read_bytes(dest).startswith(b"\x89PNG")


def test_case_only_rename(any_vault: Store) -> None:
    dest = P("60-Knowledge/Software/polars with_columns.md")
    cs = plan(any_vault, POLARS, dest)
    assert apply_changeset(any_vault, cs, now=NOW).ok
    assert [p for p in any_vault.iter_files() if p.name == "polars with_columns.md"]
    assert VaultIndex.build(any_vault).broken == []


@pytest.mark.parametrize(
    ("dest", "message"),
    [
        ("60-Knowledge/Software/Python os.execv.md", "already exists"),
        ("60-Knowledge/ML/Python os.execv.md", "already used"),
        ("60-Knowledge/Software/What?.md", "invalid"),
        ("60-Knowledge/Software/Polars.txt", "extension"),
    ],
)
def test_plan_refuses(memory_vault: MemoryVault, dest: str, message: str) -> None:
    with pytest.raises(PlanError, match=message):
        plan(memory_vault, POLARS, P(dest))


def test_stale_changeset_is_refused(memory_vault: MemoryVault) -> None:
    cs = plan(memory_vault, POLARS, P("60-Knowledge/Software/Polars cols.md"))
    memory_vault.write_text(P("10-Tasks/Learn Kedro hooks.md"), "you edited this meanwhile")
    before = snapshot(memory_vault)
    result = apply_changeset(memory_vault, cs, now=NOW)
    assert not result.ok and "stale" in (result.error or "")
    assert snapshot(memory_vault) == before


class FailingVault(MemoryVault):
    """Fails on the n-th write, to prove rollback."""

    def __init__(self, base: MemoryVault, fail_on: int) -> None:
        super().__init__(base.snapshot())
        self.writes = 0
        self.fail_on = fail_on

    def write_bytes(self, path: PurePosixPath, data: bytes) -> None:
        self.writes += 1
        if self.writes == self.fail_on:
            raise OSError("disk full")
        super().write_bytes(path, data)


def test_failure_mid_apply_rolls_back(memory_vault: MemoryVault) -> None:
    vault = FailingVault(memory_vault, fail_on=3)
    before = vault.snapshot()
    cs = plan(vault, POLARS, P("60-Knowledge/Software/Polars cols.md"))
    result = apply_changeset(vault, cs, now=NOW)
    assert not result.ok and "rolled back" in (result.error or "")
    assert vault.snapshot() == before


def test_changeset_that_breaks_links_is_rolled_back(memory_vault: MemoryVault) -> None:
    text = memory_vault.read_text(POLARS)
    cs = Changeset(
        reason="delete a linked note",
        created_by="test",
        created=NOW.isoformat(),
        ops=[Operation("delete", POLARS, base_hash=content_hash(text))],
    )
    before = memory_vault.snapshot()
    result = apply_changeset(memory_vault, cs, now=NOW)
    assert not result.ok and "break links" in (result.error or "")
    assert memory_vault.snapshot() == before


def test_undo_refuses_after_later_edit(memory_vault: MemoryVault) -> None:
    new = P("60-Knowledge/Software/Polars cols.md")
    cs = plan(memory_vault, POLARS, new)
    assert apply_changeset(memory_vault, cs, now=NOW).ok
    memory_vault.write_text(new, memory_vault.read_text(new) + "\nmy later edit\n")
    result = undo_changeset(memory_vault, cs, now=NOW)
    assert not result.ok and "changed" in (result.error or "")


def test_only_pending_changesets_apply(memory_vault: MemoryVault) -> None:
    cs = plan(memory_vault, POLARS, P("60-Knowledge/Software/Polars cols.md"))
    cs.status = Status.REJECTED
    assert not apply_changeset(memory_vault, cs, now=NOW).ok


def test_delete_binary_and_undo_restores_bytes(memory_vault: MemoryVault) -> None:
    png = P("Attachments/Polars with_columns - 1.png")
    text = memory_vault.read_text(POLARS)
    unlinked = text.replace("![[Polars with_columns - 1.png]]\n", "").replace(
        "See the [diagram](../../Attachments/Polars%20with_columns%20-%201.png) and", "See"
    )
    data = memory_vault.read_bytes(png)
    cs = Changeset(
        reason="remove an image",
        created_by="test",
        created=NOW.isoformat(),
        ops=[
            Operation("write", POLARS, content=unlinked, base_hash=content_hash(text)),
            Operation("delete", png, base_hash=content_hash(data)),
        ],
    )
    assert apply_changeset(memory_vault, cs, now=NOW).ok, cs.error
    assert not memory_vault.exists(png)
    assert undo_changeset(memory_vault, cs, now=NOW).ok
    assert memory_vault.read_bytes(png) == data
