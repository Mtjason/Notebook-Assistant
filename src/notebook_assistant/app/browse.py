"""Read-only views of the vault for the web app shell (``docs/design.html``, the app shell).

- :func:`counts`: the nav rail's live counts (Inbox, Digest, Review);
- :func:`summaries`: every note's title, type and aliases, for the search palette;
- :func:`find_note` and :func:`note_detail`: one note, by its ``id`` or its path, with backlinks,
  for the context panel's preview.

The assistant's own state (Handbook §0.1, Scope) is never listed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain.changeset import Status
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import load_rules
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store


@dataclass(frozen=True)
class Counts:
    inbox: int  # files waiting in the Inbox (Handbook §3 row 1)
    digest: int  # notes in the digestion queue (§19.1)
    review: int  # pending changesets


@dataclass(frozen=True)
class NoteSummary:
    path: str
    title: str
    type: str | None
    aliases: list[str]


@dataclass(frozen=True)
class NoteDetail:
    path: str
    title: str
    props: dict[str, Any]
    body: str
    backlinks: list[str]  # paths of the notes that link here


def counts(index: VaultIndex, store: VaultStore) -> Counts:
    rules = load_rules()
    inbox = sum(1 for p in index.files if p.parts and p.parts[0] == rules.inbox)
    queue = rules.digest_flow[0]
    digest = sum(1 for n in index.notes.values() if n.prop("digest") == queue)
    pending = sum(
        1
        for record in cs_store.list_records(store)
        if cs_store.load(store, record).status is Status.PENDING
    )
    return Counts(inbox=inbox, digest=digest, review=pending)


def _listed(index: VaultIndex) -> list[Note]:
    notes = (n for n in index.notes.values() if not is_state_path(n.path))
    return sorted(notes, key=lambda n: n.path.as_posix())


def summaries(index: VaultIndex) -> list[NoteSummary]:
    return [
        NoteSummary(
            path=n.path.as_posix(),
            title=n.title,
            type=n.type,
            aliases=[str(a) for a in (n.frontmatter.get_list("aliases") if n.frontmatter else [])],
        )
        for n in _listed(index)
    ]


def find_note(index: VaultIndex, ref: str) -> Note | None:
    """A note by its ``id`` property or its vault-relative path (case-insensitive)."""
    by_path = index.note(PurePosixPath(ref))
    if by_path is not None and not is_state_path(by_path.path):
        return by_path
    key = name_key(ref)
    return next((n for n in _listed(index) if n.note_id and name_key(n.note_id) == key), None)


def note_detail(index: VaultIndex, note: Note) -> NoteDetail:
    backlinks = sorted(
        {ref.source.as_posix() for ref in index.backlinks(note.path) if ref.source != note.path}
    )
    return NoteDetail(
        path=note.path.as_posix(),
        title=note.title,
        props=note.props,
        body=note.body,
        backlinks=backlinks,
    )
