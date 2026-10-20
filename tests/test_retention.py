"""Session retention: old sessions proposed for deletion once, by the PC holding the lease."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.retention import run_retention
from notebook_assistant.handbook import load_rules
from notebook_assistant.store import changesets as cs_store

RULES = load_rules()
NOW = datetime(2027, 3, 1, 3, 0, tzinfo=UTC)
OLD = PurePosixPath("99-System/Assistant/Sessions/2026/10/ses-old.md")
NEW = PurePosixPath("99-System/Assistant/Sessions/2027/02/ses-new.md")


def vault(store: MemoryVault) -> MemoryVault:
    store.write_text(OLD, "---\nid: ses-old\nstarted: 2026-10-01T09:00+08:00\n---\nold\n")
    store.write_text(NEW, "---\nid: ses-new\nstarted: 2027-02-20T09:00+08:00\n---\nnew\n")
    return store


def test_old_sessions_are_proposed_once_as_one_batch(memory_vault: MemoryVault) -> None:
    store = vault(memory_vault)
    cs_id = run_retention(store, RULES, now=NOW, machine="pc-a")
    assert cs_id is not None
    record = cs_store.find(store, cs_id)
    assert record is not None
    cs = cs_store.load(store, record)
    assert [op.path for op in cs.ops] == [OLD] and store.exists(OLD)  # only proposed
    assert run_retention(store, RULES, now=NOW + timedelta(days=1), machine="pc-a") is None
    assert apply_changeset(store, cs, now=NOW, machine="pc-a").ok
    assert not store.exists(OLD) and store.exists(NEW)
    assert run_retention(store, RULES, now=NOW + timedelta(days=2), machine="pc-a") is None


def test_the_other_pc_skips_while_the_lease_is_held(memory_vault: MemoryVault) -> None:
    store = vault(memory_vault)
    assert run_retention(store, RULES, now=NOW, machine="pc-a") is not None
    assert run_retention(store, RULES, now=NOW + timedelta(hours=1), machine="pc-b") is None
