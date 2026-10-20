"""The four maintenance buttons, each returning one report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app import maintenance
from notebook_assistant.config import load_default_config
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.ports.llm import LLMError
from notebook_assistant.store import changesets as cs_store
from notebook_assistant.store import runs

P = PurePosixPath
NOW = datetime(2027, 1, 10, 9, 0, tzinfo=UTC)


def ctx(store: MemoryVault, answers: list[object] | None = None) -> maintenance.Context:
    model = ScriptedModel(answers or [])  # type: ignore[arg-type]
    return maintenance.Context(
        store, load_default_config(), load_rules(), handbook_text(), NOW, "test-pc", lambda: model
    )


@pytest.fixture
def store(memory_vault: MemoryVault) -> MemoryVault:
    memory_vault.clock = lambda: NOW - timedelta(days=1)
    task = P("10-Tasks/Learn Kedro hooks.md")
    memory_vault.write_text(
        task, memory_vault.read_text(task).replace("status: todo", "status: done")
    )
    return memory_vault


def test_lint_saves_one_batch_and_reports(store: MemoryVault) -> None:
    report = maintenance.run("lint", ctx(store))
    assert report.kind == "lint" and report.summary.startswith("13 notes, 0 finding(s)")
    [cs_id] = report.changesets
    assert cs_store.find(store, cs_id) is not None
    assert "lint" in store.read_text(runs.runs_path(NOW))


def test_archive_proposes_and_reviews(store: MemoryVault) -> None:
    report = maintenance.run("archive", ctx(store))
    assert report.summary == "1 to archive, 0 to review"
    assert report.rows[0].label == "archive" and len(report.changesets) == 1


def test_deep_pass_reports_without_changesets(store: MemoryVault) -> None:
    report = maintenance.run("deep", ctx(store))
    assert report.changesets == [] and "duplicate" in report.summary


def test_sweep_changes_reports_each_raw_note(store: MemoryVault) -> None:
    steps: list[str] = []
    report = maintenance.run("changes", ctx(store, [LLMError("offline")]), steps.append)
    assert report.rows == [maintenance.Row("00-Inbox/raw capture.md", "failed", "offline")]
    assert steps[0] == "Found 1 raw note(s) to plan"


def test_an_unknown_run_is_refused(store: MemoryVault) -> None:
    with pytest.raises(ValueError, match="unknown maintenance run"):
        maintenance.run("everything", ctx(store))
