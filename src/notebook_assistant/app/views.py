"""The Tasks and Incubator screens (design.html; Handbook §17, §18): what they show, and the
changes they make.

- :func:`tasks_view`, :func:`incubator_view`: the §17.5 views and the §18.4 board, over the
  live notes (nothing archived);
- :func:`set_status`: a task or idea moved to another status. The screen's one-line confirm is
  your approval (design.html, InlineConfirm), so it's applied at once as its own changeset;
- :func:`promote`: an idea becomes a project. That creates a note, so it's proposed as a pending
  changeset for the Review screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from notebook_assistant.app.browse import find_note
from notebook_assistant.app.clicks import ApplyRefusedError, Button, apply_click
from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain import tasks
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store


class ViewError(ValueError):
    """No such note, a status the rules don't allow, or apply refused the change."""


@dataclass(frozen=True)
class TasksView:
    views: list[tasks.TaskView]
    statuses: list[str]  # what a task can be set to, in lifecycle order


@dataclass(frozen=True)
class IncubatorView:
    columns: dict[str, list[tasks.IdeaCard]]


def _live_notes(index: VaultIndex, rules: Rules) -> list[Note]:
    return [
        n
        for n in index.notes.values()
        if not is_state_path(n.path) and n.path.parts[0] != rules.archive_root
    ]


def tasks_view(store: VaultStore, rules: Rules, today: date) -> TasksView:
    notes = _live_notes(VaultIndex.build(store), rules)
    statuses = [s for s in rules.types[tasks.TASK].lifecycle if s != tasks.ARCHIVED]
    return TasksView(tasks.task_views(notes, rules, today), statuses)


def incubator_view(store: VaultStore, rules: Rules) -> IncubatorView:
    return IncubatorView(tasks.board(_live_notes(VaultIndex.build(store), rules), rules))


def _note(index: VaultIndex, ref: str) -> Note:
    note = find_note(index, ref)
    if note is None:
        raise ViewError(f"no note {ref!r}")
    return note


def _write(index: VaultIndex, before: Note, after: Note, label: str) -> Operation:
    stored = index.text(before.path)
    assert stored is not None, "the note comes from the index"
    return Operation(
        "write", before.path, content=after.render(), base_hash=content_hash(stored), label=label
    )


def set_status(
    store: VaultStore,
    ref: str,
    status: str,
    *,
    rules: Rules,
    click: Button,
    produced: list[str] | None = None,
) -> str:
    """Apply the status change; returns the changeset id."""
    index = VaultIndex.build(store)
    note = _note(index, ref)
    try:
        after = tasks.with_status(note, status, rules, today=click.today, produced=produced)
    except tasks.StatusError as exc:
        raise ViewError(str(exc)) from exc
    cs = Changeset(
        reason=f"{note.title}: {note.prop('status')} → {status}",
        created_by="button:status",
        created=click.stamp,
        ops=[_write(index, note, after, f"status → {status}")],
    )
    try:
        return apply_click(store, cs, click)
    except ApplyRefusedError as exc:
        raise ViewError(str(exc)) from exc


def promote(store: VaultStore, ref: str, title: str, *, rules: Rules, now: datetime) -> str:
    """Propose the idea's promotion to a project titled ``title``; returns the pending id."""
    index = VaultIndex.build(store)
    idea = _note(index, ref)
    if any(name_key(n.title) == name_key(title) for n in index.notes.values()):
        raise ViewError(f"a note titled {title!r} already exists (Handbook §5: titles are unique)")
    try:
        marked, hub = tasks.promoted(idea, title, rules, today=now.date().isoformat())
    except tasks.StatusError as exc:
        raise ViewError(str(exc)) from exc
    cs = Changeset(
        reason=f"Promote {idea.title} to the project {title} (Handbook §18.4)",
        created_by="button:promote",
        created=now.isoformat(timespec="seconds"),
        ops=[
            Operation("create", hub.path, content=hub.render(), label="new project"),
            _write(index, idea, marked, "promoted"),
        ],
    )
    cs_store.save(store, cs)
    return cs.id
