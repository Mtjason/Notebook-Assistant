"""Chat sessions as notes (docs/architecture.md §4.1: one note per session in the folder Handbook
§8.4 names, append-only): listing them for the Sessions screen, newest first.

Searching them is :func:`app.search.search` with ``kind="session"``.
"""

from __future__ import annotations

from dataclasses import dataclass

from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.search import is_session
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.vault import VaultStore

PREVIEW = 160


@dataclass(frozen=True)
class SessionSummary:
    path: str
    id: str
    title: str
    started: str | None
    device: str | None
    changesets: int
    preview: str


def summary(note: Note) -> SessionSummary:
    fm = note.frontmatter
    started = note.prop("started")
    return SessionSummary(
        path=note.path.as_posix(),
        id=str(note.prop("id") or note.title),
        title=str(note.prop("title") or note.title),
        started=str(started) if started else None,
        device=str(note.prop("device")) if note.prop("device") else None,
        changesets=len(fm.get_list("changesets")) if fm else 0,
        preview=" ".join(note.body.split())[:PREVIEW],
    )


def list_sessions(store: VaultStore, rules: Rules) -> list[SessionSummary]:
    notes = VaultIndex.build(store).notes.values()
    found = [summary(n) for n in notes if is_session(n.path.as_posix(), rules)]
    return sorted(found, key=lambda s: s.started or "", reverse=True)
