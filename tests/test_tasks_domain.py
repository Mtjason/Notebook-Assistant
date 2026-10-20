"""Tasks and ideas: the §17.5 views, the §18.4 board, status changes, promotion."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import PurePosixPath

import pytest

from notebook_assistant.domain import tasks
from notebook_assistant.domain.invariants import VaultFacts, check_note
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import TaskViews
from notebook_assistant.handbook import load_rules

P = PurePosixPath
RULES = load_rules()
TODAY = date(2026, 10, 21)


def task(title: str, **props: str) -> Note:
    base = {
        "type": "task",
        "kind": "action",
        "scope": "personal",
        "status": "todo",
        "priority": "p2",
        "created": "2026-10-01",
        "updated": "2026-10-01",
    }
    base.update(props)
    fm = "\n".join(f"{k}: {v}" for k, v in base.items())
    return Note.parse(P(f"10-Tasks/{title}.md"), f"---\n{fm}\n---\nx\n")


NOTES = [
    task("Late", due="2026-10-01", priority="p1"),
    task("Today one", due="2026-10-21"),
    task("Busy", status="doing"),
    task("Next low", priority="p3"),
    task("Next high", priority="p1", due="2026-11-01"),
    task("Waiting on Amy", status="waiting", waiting_on="Amy", updated="2026-09-01"),
    task("Learn Kedro", kind="learn", topic='"[[MOC - Software]]"'),
    task("Why imports", kind="question"),
    task("Learned uv", kind="learn", status="done", updated="2026-10-15", produced='["[[uv]]"]'),
    task("Learned long ago", kind="learn", status="done", updated="2026-01-01"),
    task("Maybe", status="someday"),
]


def view(name: str) -> dict[str, list[str]]:
    [v] = [v for v in tasks.task_views(NOTES, RULES, TODAY) if v.name == name]
    return {g.label: [t.title for t in g.tasks] for g in v.groups}


def test_the_views_follow_section_17_5() -> None:
    assert [v.name for v in tasks.task_views(NOTES, RULES, TODAY)] == list(RULES.task_views.names)
    assert view("Today") == {"Overdue": ["Late"], "Due today": ["Today one"], "Doing": ["Busy"]}
    assert view("Next")["To do"][:2] == ["Late", "Next high"]  # p1 first, then by due date
    assert view("Next")["To do"][-1] == "Next low"
    assert view("Waiting") == {"Waiting": ["Waiting on Amy"]}
    assert view("Learning queue") == {
        "MOC - Software": ["Learn Kedro"],
        "No topic": ["Why imports"],
    }
    assert view("Recently learned") == {"Done": ["Learned uv"]}
    assert view("Someday") == {"Someday": ["Maybe"]}
    [row] = [tasks.task_row(n) for n in NOTES if n.title == "Learned uv"]
    assert row.produced == ["uv"]


def test_an_unknown_view_fails_loudly() -> None:
    rules = replace(RULES, task_views=TaskViews(("Tomorrow",), 30))
    with pytest.raises(ValueError, match="'Tomorrow' has no implementation"):
        tasks.task_views(NOTES, rules, TODAY)


def test_a_learn_task_is_done_only_with_produced() -> None:
    learn = task("Learn Kedro", kind="learn")
    with pytest.raises(tasks.StatusError, match=r"§17\.1"):
        tasks.with_status(learn, "done", RULES, today="2026-10-21")
    done = tasks.with_status(learn, "done", RULES, today="2026-10-21", produced=["Kedro hooks"])
    assert done.props["status"] == "done" and done.props["produced"] == ["[[Kedro hooks]]"]
    assert tasks.with_status(task("A"), "done", RULES, today="d").props["status"] == "done"
    with pytest.raises(tasks.StatusError, match="isn't a status here"):
        tasks.with_status(task("A"), "shaping", RULES, today="d")
    with pytest.raises(tasks.StatusError, match="isn't a status here"):
        tasks.with_status(task("A"), "archived", RULES, today="d")


IDEA = Note.parse(
    P("15-Incubator/Agent.md"),
    "---\ntype: idea\nscope: personal\nstatus: shaping\ncreated: 2026-09-01\n"
    "updated: 2026-09-01\nquestion: Can an agent heal itself?\naliases: [自癒代理]\n---\nmessy\n",
)


def test_the_board_has_lifecycle_columns() -> None:
    other = Note.parse(P("15-Incubator/B.md"), "---\ntype: idea\nstatus: parked\n---\n")
    columns = tasks.board([IDEA, other, task("A")], RULES)
    assert list(columns) == ["exploring", "shaping", "promoted", "parked", "dropped"]
    assert [c.title for c in columns["shaping"]] == ["Agent"]
    assert columns["shaping"][0].question == "Can an agent heal itself?"


def test_promoting_an_idea_creates_a_project_hub() -> None:
    idea, hub = tasks.promoted(IDEA, "Self-healing agent", RULES, today="2026-10-21")
    assert (
        idea.props["status"] == "promoted" and idea.props["promoted_to"] == "[[Self-healing agent]]"
    )
    assert hub.path == P("20-Projects/Self-healing agent/Self-healing agent.md")
    assert hub.props["status"] == "active" and "Can an agent heal itself?" in hub.body
    assert check_note(hub, VaultFacts(RULES)) == []
    with pytest.raises(tasks.StatusError, match="isn't an idea"):
        tasks.promoted(task("A"), "X", RULES, today="d")
    no_scope = Note.parse(P("15-Incubator/C.md"), "---\ntype: idea\nstatus: exploring\n---\n")
    with pytest.raises(tasks.StatusError, match="no scope"):
        tasks.promoted(no_scope, "X", RULES, today="d")
