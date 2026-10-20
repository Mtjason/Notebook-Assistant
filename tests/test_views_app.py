"""The Tasks and Incubator use cases on the fixture vault."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app import views
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.clicks import Button
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import load_rules
from notebook_assistant.store import changesets as cs_store

P = PurePosixPath
RULES = load_rules()
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
CLICK = Button("test-pc", NOW)
TASK = "10-Tasks/Learn Kedro hooks.md"
IDEA = P("15-Incubator/Agent.md")


@pytest.fixture
def store(memory_vault: MemoryVault) -> MemoryVault:
    memory_vault.write_text(
        IDEA,
        "---\ntype: idea\nscope: personal\nstatus: exploring\ncreated: 2026-09-01\n"
        "updated: 2026-09-01\nquestion: Can it heal?\n---\nmessy [[MOC - Software]]\n",
    )
    return memory_vault


def test_the_tasks_view_lists_the_fixture_task(store: MemoryVault) -> None:
    view = views.tasks_view(store, RULES, date(2026, 10, 21))
    queue = next(v for v in view.views if v.name == "Learning queue")
    assert [t.title for g in queue.groups for t in g.tasks] == ["Learn Kedro hooks"]
    assert view.statuses[0] == "someday" and "archived" not in view.statuses


def test_a_status_change_is_applied_and_recorded(store: MemoryVault) -> None:
    with pytest.raises(views.ViewError, match="produced"):
        views.set_status(store, TASK, "done", rules=RULES, click=CLICK)
    cs_id = views.set_status(store, TASK, "doing", rules=RULES, click=CLICK)
    note = Note.parse(P(TASK), store.read_text(P(TASK)))
    assert note.props["status"] == "doing" and cs_store.find(store, cs_id) is not None
    with pytest.raises(views.ViewError, match="no note"):
        views.set_status(store, "nowhere.md", "doing", rules=RULES, click=CLICK)


def test_a_refused_apply_is_a_view_error(
    store: MemoryVault, monkeypatch: pytest.MonkeyPatch
) -> None:
    from notebook_assistant.app.clicks import ApplyRefusedError

    def refuse(*args: object) -> str:
        raise ApplyRefusedError("changed")

    monkeypatch.setattr("notebook_assistant.app.views.apply_click", refuse)
    with pytest.raises(views.ViewError, match="changed"):
        views.set_status(store, TASK, "doing", rules=RULES, click=CLICK)


def test_the_board_and_promotion_to_a_project(store: MemoryVault) -> None:
    board = views.incubator_view(store, RULES).columns
    assert [c.title for c in board["exploring"]] == ["Agent"]
    cs_id = views.promote(store, IDEA.as_posix(), "Self-healing agent", rules=RULES, now=NOW)
    record = cs_store.find(store, cs_id)
    assert record is not None
    result = apply_changeset(store, cs_store.load(store, record), now=NOW, machine="t")
    assert result.ok, result.error
    hub = P("20-Projects/Self-healing agent/Self-healing agent.md")
    assert Note.parse(hub, store.read_text(hub)).props["type"] == "project"
    assert views.incubator_view(store, RULES).columns["promoted"][0].title == "Agent"
    with pytest.raises(views.ViewError, match="already exists"):
        views.promote(store, IDEA.as_posix(), "Self-healing agent", rules=RULES, now=NOW)
    with pytest.raises(views.ViewError, match="isn't an idea"):
        views.promote(store, TASK, "New project", rules=RULES, now=NOW)
