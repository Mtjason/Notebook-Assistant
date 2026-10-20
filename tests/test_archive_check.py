"""The Archive check: §13 candidates as changesets, and the §17.6 / §18.4 review items."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.archive_check import (
    age_in_days,
    archive_candidates,
    archive_changeset,
    review_items,
)
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.tasks import live_statuses
from notebook_assistant.handbook import load_rules

P = PurePosixPath
RULES = load_rules()
TODAY = date(2027, 1, 10)
NOW = datetime(2027, 1, 10, 9, 0, tzinfo=UTC)
TASK = P("10-Tasks/Learn Kedro hooks.md")
PROJECT = P("20-Projects/Demo/Demo.md")


def set_props(store: MemoryVault, path: P, old: str, new: str) -> None:
    store.write_text(path, store.read_text(path).replace(old, new, 1))


def note(store: MemoryVault, path: P) -> Note:
    return Note.parse(path, store.read_text(path))


def test_age_counts_from_updated() -> None:
    assert age_in_days(Note.parse(P("a.md"), "---\nupdated: 2027-01-01\n---\n"), TODAY) == 9
    assert age_in_days(Note.parse(P("a.md"), "---\nupdated: soon\n---\n"), TODAY) is None
    assert age_in_days(Note(path=P("a.md"), body=""), TODAY) is None


def test_a_task_done_long_enough_is_archived_link_safely(memory_vault: MemoryVault) -> None:
    set_props(memory_vault, TASK, "status: todo", "status: done")
    index = VaultIndex.build(memory_vault)
    [candidate] = archive_candidates(index, RULES, TODAY)
    assert (candidate.title, candidate.status, candidate.days) == ("Learn Kedro hooks", "done", 106)
    assert archive_candidates(index, RULES, date(2026, 10, 1)) == []  # not 90 days yet
    cs = archive_changeset(index, candidate, RULES, now=NOW, created_by="sweep:archive")
    result = apply_changeset(memory_vault, cs, now=NOW, machine="t")
    assert result.ok, result.error
    archived = note(memory_vault, P("95-Archive") / TASK)
    assert archived.props["status"] == "archived" and archived.props["archived"] == "2027-01-10"
    assert archived.props["archive_reason"] == "done for 90+ days"
    assert archive_candidates(VaultIndex.build(memory_vault), RULES, TODAY) == []


def test_a_finished_project_moves_with_its_whole_container(memory_vault: MemoryVault) -> None:
    set_props(memory_vault, PROJECT, "status: active", "status: done")
    index = VaultIndex.build(memory_vault)
    [candidate] = archive_candidates(index, RULES, TODAY)
    cs = archive_changeset(index, candidate, RULES, now=NOW, created_by="t")
    assert sorted(op.dest.as_posix() for op in cs.ops if op.dest) == [
        "95-Archive/20-Projects/Demo/Demo.md",
        "95-Archive/20-Projects/Demo/README.md",
        "95-Archive/20-Projects/Demo/src/app.py",
    ]
    result = apply_changeset(memory_vault, cs, now=NOW, machine="t")
    assert result.ok, result.error
    assert (
        note(memory_vault, P("95-Archive/20-Projects/Demo/Demo.md")).props["status"] == "archived"
    )


@pytest.mark.parametrize(
    ("path", "old", "new", "kind"),
    [
        (TASK, "status: todo", "status: todo", "learn"),
        (TASK, "status: todo", "status: waiting\nwaiting_on: Amy", "nudge"),
    ],
)
def test_review_items_ask_about_stale_tasks(
    memory_vault: MemoryVault, path: P, old: str, new: str, kind: str
) -> None:
    set_props(memory_vault, path, old, new)
    [item] = review_items(VaultIndex.build(memory_vault), RULES, TODAY)
    assert (item.title, item.kind) == ("Learn Kedro hooks", kind)


def test_an_untouched_idea_is_asked_about(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(
        P("15-Incubator/Agent.md"),
        "---\ntype: idea\nscope: personal\nstatus: exploring\ncreated: 2026-01-01\n"
        "updated: 2026-01-01\nquestion: How?\n---\nx [[MOC - Software]]\n",
    )
    kinds = {i.title: i.kind for i in review_items(VaultIndex.build(memory_vault), RULES, TODAY)}
    assert kinds["Agent"] == "idea"
    assert review_items(VaultIndex.build(memory_vault), RULES, date(2026, 1, 5)) == []


def test_live_statuses_come_from_the_handbook() -> None:
    assert live_statuses(RULES, "task") == {"someday", "todo", "doing", "waiting"}
    assert live_statuses(RULES, "idea") == {"exploring", "shaping"}
