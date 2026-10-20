"""Tasks and ideas as the Tasks and Incubator screens show them, and their status changes, as
pure functions (Handbook §17, §18).

- :func:`live_statuses`: a type's statuses before it's finished;
- :func:`task_row`, :func:`task_views`: the §17.5 views over task notes;
- :func:`idea_card`, :func:`board`: the Incubator board by status (§18.4);
- :func:`with_status`: a task or idea moved to another status; a ``question`` or ``learn`` task
  is done only with ``produced`` linking what it led to (§17.1);
- :func:`promoted`: an idea turned into a project hub (§18.4, Graduation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath

from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.note import NOTE_SUFFIX, Note
from notebook_assistant.domain.rules import Rules

# Vocabulary (Handbook §4.2, §4.3, §17, §18): types, kinds, statuses and properties read here.
TASK, IDEA, PROJECT = "task", "idea", "project"
ACTION, QUESTION, LEARN = "action", "question", "learn"
ARCHIVED, PARKED, PROMOTED = "archived", "parked", "promoted"
TODO, DOING, WAITING, DONE, SOMEDAY = "todo", "doing", "waiting", "done", "someday"
PRIORITY_ORDER = ("p1", "p2", "p3")  # §4.2: p1 first


class StatusError(ValueError):
    """The status isn't allowed for the note's type, or a closing condition is missing."""


def live_statuses(rules: Rules, type_name: str) -> frozenset[str]:
    """A type's statuses before it's finished: not the ones §13 archives, not ``archived``, and
    not a parked idea."""
    ending = rules.review.archive.get(type_name)
    done = (ending.statuses if ending else frozenset()) | {ARCHIVED, PARKED}
    return rules.types[type_name].statuses - done


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _link_title(value: object) -> str | None:
    links = find_links(str(value)) if value else []
    return links[0].target.split("/")[-1].removesuffix(NOTE_SUFFIX) if links else None


@dataclass(frozen=True)
class TaskRow:
    path: str
    title: str
    kind: str
    status: str
    priority: str | None
    due: str | None
    topic: str | None  # the MOC's title, without brackets
    waiting_on: str | None
    produced: list[str]  # titles of the notes it led to
    updated: str | None


def task_row(note: Note) -> TaskRow:
    fm = note.frontmatter
    produced = fm.get_list("produced") if fm else []
    due, updated = _date(note.prop("due")), _date(note.prop("updated"))
    return TaskRow(
        path=note.path.as_posix(),
        title=note.title,
        kind=str(note.prop("kind") or ""),
        status=str(note.prop("status") or ""),
        priority=str(note.prop("priority")) if note.prop("priority") else None,
        due=due.isoformat() if due else None,
        topic=_link_title(note.prop("topic")),
        waiting_on=str(note.prop("waiting_on")) if note.prop("waiting_on") else None,
        produced=[t for p in produced if (t := _link_title(p))],
        updated=updated.isoformat() if updated else None,
    )


@dataclass(frozen=True)
class Group:
    label: str
    tasks: list[TaskRow]


@dataclass(frozen=True)
class TaskView:
    name: str
    groups: list[Group]


def _by_priority(row: TaskRow) -> tuple[int, str]:
    rank = PRIORITY_ORDER.index(row.priority) if row.priority in PRIORITY_ORDER else 1
    return rank, row.due or "9999-12-31"


def _today(rows: list[TaskRow], live: frozenset[str], today: date) -> list[Group]:
    iso = today.isoformat()
    open_rows = [r for r in rows if r.status in live]
    return [
        Group("Overdue", sorted((r for r in open_rows if r.due and r.due < iso), key=_by_priority)),
        Group("Due today", [r for r in open_rows if r.due == iso]),
        Group(
            "Doing",
            [
                r
                for r in open_rows
                if r.status == DOING and r.due != iso and not (r.due and r.due < iso)
            ],
        ),
    ]


def _learning(rows: list[TaskRow], live: frozenset[str]) -> list[Group]:
    learning = [r for r in rows if r.kind in (LEARN, QUESTION) and r.status in live - {SOMEDAY}]
    topics = sorted({r.topic or "No topic" for r in learning})
    return [Group(t, [r for r in learning if (r.topic or "No topic") == t]) for t in topics]


def task_views(notes: list[Note], rules: Rules, today: date) -> list[TaskView]:
    """The §17.5 views, in the handbook's order. A view the code doesn't know fails loudly, so a
    handbook edit can't silently drop one."""
    rows = sorted((task_row(n) for n in notes if n.type == TASK), key=lambda r: r.title.casefold())
    live = live_statuses(rules, TASK)
    since = (today - timedelta(days=rules.task_views.recent_days)).isoformat()
    builders = {
        "Today": lambda: _today(rows, live, today),
        "Next": lambda: [
            Group("To do", sorted((r for r in rows if r.status == TODO), key=_by_priority))
        ],
        "Waiting": lambda: [
            Group(
                "Waiting",
                sorted((r for r in rows if r.status == WAITING), key=lambda r: r.updated or ""),
            )
        ],
        "Learning queue": lambda: _learning(rows, live),
        "Recently learned": lambda: [
            Group(
                "Done",
                [
                    r
                    for r in rows
                    if r.kind in (LEARN, QUESTION)
                    and r.status == DONE
                    and (r.updated or "") >= since
                ],
            )
        ],
        "Someday": lambda: [Group("Someday", [r for r in rows if r.status == SOMEDAY])],
    }
    views: list[TaskView] = []
    for name in rules.task_views.names:
        if name not in builders:
            raise ValueError(f"Handbook §17.5 view {name!r} has no implementation")
        views.append(TaskView(name, builders[name]()))
    return views


@dataclass(frozen=True)
class IdeaCard:
    path: str
    title: str
    status: str
    question: str | None
    next_step: str | None
    updated: str | None


def idea_card(note: Note) -> IdeaCard:
    updated = _date(note.prop("updated"))
    return IdeaCard(
        path=note.path.as_posix(),
        title=note.title,
        status=str(note.prop("status") or ""),
        question=str(note.prop("question")) if note.prop("question") else None,
        next_step=str(note.prop("next_step")) if note.prop("next_step") else None,
        updated=updated.isoformat() if updated else None,
    )


def board(notes: list[Note], rules: Rules) -> dict[str, list[IdeaCard]]:
    """Ideas by status, columns in lifecycle order, oldest first (§18.4 view); archived ideas
    aren't on the board."""
    cards = [idea_card(n) for n in notes if n.type == IDEA]
    columns = [s for s in rules.types[IDEA].lifecycle if s != ARCHIVED]
    return {
        s: sorted((c for c in cards if c.status == s), key=lambda c: c.updated or "")
        for s in columns
    }


def with_status(
    note: Note, status: str, rules: Rules, *, today: str, produced: list[str] | None = None
) -> Note:
    """``note`` moved to ``status`` with ``updated`` today; :class:`StatusError` when the type
    doesn't allow it, or a question or learn task would be done without ``produced`` (§17.1)."""
    rule = rules.types.get(note.type or "")
    if rule is None or status not in rule.statuses or status == ARCHIVED:
        allowed = sorted((rule.statuses - {ARCHIVED}) if rule else ())
        raise StatusError(f"{note.title}: {status!r} isn't a status here; one of {allowed}")
    copy = Note.parse(note.path, note.render())
    fm = copy.ensure_frontmatter()
    if note.type == TASK and status == DONE and note.prop("kind") in (QUESTION, LEARN):
        links = [f"[[{t}]]" for t in produced or []] or list(fm.get_list(rules.digestion.produced))
        if not links:
            raise StatusError(
                f"{note.title}: a {note.prop('kind')} task is done only with `produced` "
                "linking the knowledge note it led to (Handbook §17.1)"
            )
        fm.set(rules.digestion.produced, links)
    fm.set("status", status)
    fm.set("updated", today)
    return copy


def promoted(idea: Note, title: str, rules: Rules, *, today: str) -> tuple[Note, Note]:
    """(the idea marked promoted with ``promoted_to``, the new project hub titled ``title``)
    (§18.4, §2.1). Titles are unique (I-4), so the project is named, not copied from the idea."""
    root = rules.types[PROJECT].hub_of
    if idea.type != IDEA or root is None:
        raise StatusError(f"{idea.title} isn't an idea")
    if not idea.prop("scope"):
        raise StatusError(f"{idea.title} has no scope to give the project")
    hub = Note(path=PurePosixPath(root) / title / f"{title}{NOTE_SUFFIX}", body="")
    question = idea.prop("question")
    hub.body = (
        f"## Goal\n\n{question or 'State the goal and the done condition.'}\n\n"
        f"Promoted from [[{idea.title}]].\n"
    )
    fm = hub.ensure_frontmatter()
    for key, value in (
        ("type", PROJECT),
        ("scope", idea.prop("scope")),
        ("status", rules.types[PROJECT].lifecycle[0]),
        ("created", today),
        ("updated", today),
        ("started", today),
        ("aliases", list(idea.frontmatter.get_list("aliases")) if idea.frontmatter else []),
    ):
        fm.set(key, value)
    marked = with_status(idea, PROMOTED, rules, today=today)
    marked.ensure_frontmatter().set("promoted_to", f"[[{title}]]")
    return marked, hub
