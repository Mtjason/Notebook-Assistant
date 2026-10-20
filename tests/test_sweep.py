"""Sweep changes: raw notes anywhere, after settle time, planned once each."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app import sweep
from notebook_assistant.config import load_default_config
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.ports.llm import LLMError
from notebook_assistant.store import runs
from tests.conftest import sequential_ids
from tests.test_inbox_app import SENTENCE, plan

P = PurePosixPath
RULES = load_rules()
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
RAW = P("60-Knowledge/Software/kedro note.md")  # written straight into a topic folder, no type


def vault(memory_vault: MemoryVault, written: datetime) -> MemoryVault:
    memory_vault.delete(P("00-Inbox/raw capture.md"))  # only the note under test is raw
    memory_vault.clock = lambda: written
    memory_vault.write_text(RAW, f"{SENTENCE}\n")
    memory_vault.write_text(P("00-Inbox/d.excalidraw.md"), "drawing")
    memory_vault.clock = lambda: NOW
    return memory_vault


def run(store: MemoryVault, answers: list[object]) -> sweep.SweepResult:
    steps: list[str] = []
    result = sweep.sweep_changes(
        store,
        ScriptedModel(answers),  # type: ignore[arg-type]
        config=load_default_config(),
        rules=RULES,
        handbook=handbook_text(),
        now=NOW,
        machine="test-pc",
        progress=steps.append,
        new_id=sequential_ids(),
    )
    assert steps[-1] == f"Done: {result.summary}"
    return result


def test_raw_notes_anywhere_are_found_and_settled_ones_planned(memory_vault: MemoryVault) -> None:
    store = vault(memory_vault, NOW - timedelta(hours=2))
    settled, unsettled = sweep.raw_notes(store, RULES, NOW)
    assert settled == ["00-Inbox/d.excalidraw.md", RAW.as_posix()] and unsettled == []
    result = run(store, [plan("[[2026-10-21]]")])
    assert list(result.proposed) == [RAW.as_posix()] and result.failed == {}
    assert "sweep" in store.read_text(runs.runs_path(NOW))
    again = run(store, [])  # a pending proposal isn't planned twice
    assert RAW.as_posix() in again.already_proposed and again.proposed == {}


def test_a_note_still_being_written_waits(memory_vault: MemoryVault) -> None:
    store = vault(memory_vault, NOW - timedelta(minutes=5))
    store.write_text(P("00-Inbox/new.md"), "typed a minute ago")
    store.clock = lambda: NOW - timedelta(days=1)
    store.write_text(P("00-Inbox/old.md"), "fails to plan")
    result = run(store, [LLMError("offline")])
    assert result.unsettled == ["00-Inbox/d.excalidraw.md", "00-Inbox/new.md", RAW.as_posix()]
    assert result.failed == {"00-Inbox/old.md": "offline"}
    assert result.summary == "0 proposed, 3 still being edited, 1 failed"


def test_skipped_and_drawing_notes_are_left_alone(memory_vault: MemoryVault) -> None:
    store = vault(memory_vault, NOW - timedelta(hours=2))
    store.write_text(RAW, "---\nassistant: skip\n---\nkeep as is\n")
    settled, _ = sweep.raw_notes(store, RULES, NOW)
    assert RAW.as_posix() not in settled
    result = run(store, [LLMError("offline")])
    assert "graduated as-is" in result.blocked["00-Inbox/d.excalidraw.md"]
