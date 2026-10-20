"""The Inbox (Handbook §3 row 1, §14: process it to zero): the notes waiting there, and
processing one through the extraction planner (docs/maintenance-job.md, Extraction).

- :func:`inbox_items`: every note in the Inbox, newest capture first;
- :func:`process`: plans the note's text (its embedded files read as screenshots) into a pending
  changeset for Review.
  §12 decides what the extracted notes cite: a ``source`` note the Inbox note becomes, or the
  capture date's daily note; filing the Inbox note is part of the same changeset
  (:mod:`app.filing`), so nothing changes until you apply it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app.browse import find_note
from notebook_assistant.app.extract import Capture, Extraction, plan_extraction
from notebook_assistant.app.images import embedded_images, screenshots
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain import capture
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.ids import new_note_id
from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.note import NOTE_SUFFIX, Note, is_note_path
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.llm import LanguageModel
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store

Progress = Callable[[str], None]
PREVIEW = 160  # characters of a note's text shown in the Inbox list


class InboxError(ValueError):
    """Not an Inbox note, one with no text to plan, or its source note's name is taken."""


@dataclass(frozen=True)
class InboxItem:
    path: str
    title: str
    kind: str  # a `source` kind (Handbook §4.2)
    origin: str
    captured: str | None
    preview: str
    files: list[str]  # vault paths of the files it embeds, in order
    gap: str | None  # `handbook_gap`, for a note waiting on the handbook (§0.3)


def _in_inbox(note: Note, rules: Rules) -> bool:
    return note.path.parts[0] == rules.inbox and is_note_path(note.path)


def embedded_files(index: VaultIndex, note: Note) -> list[str]:
    found: list[str] = []
    for link in find_links(note.body):
        target = index.resolver.resolve(link, note.path) if link.embed else None
        if target is not None and target.as_posix() not in found:
            found.append(target.as_posix())
    return found


def kind_of(index: VaultIndex, note: Note) -> str:
    """The note's ``kind`` as captured; a note you wrote in the Inbox yourself is ``image`` when
    it embeds images, else ``text``."""
    kind = note.prop(capture.KIND)
    if isinstance(kind, str):
        return kind
    return capture.IMAGE if embedded_images(index, note) else capture.TEXT


def captured_on(note: Note, today: str) -> str:
    """When it was captured (§17.3: dates count from the capture): ``captured``, else
    ``created``, else today."""
    return str(note.prop(capture.CAPTURED) or note.prop("created") or today)


def inbox_items(store: VaultStore, rules: Rules) -> list[InboxItem]:
    index = VaultIndex.build(store)
    items: list[InboxItem] = []
    for note in index.notes.values():
        if not _in_inbox(note, rules):
            continue
        text = " ".join(note.body.split())
        captured = note.prop(capture.CAPTURED) or note.prop("created")
        gap = note.prop("handbook_gap")
        items.append(
            InboxItem(
                path=note.path.as_posix(),
                title=note.title,
                kind=kind_of(index, note),
                origin=str(note.prop(capture.ORIGIN) or rules.default_origin),
                captured=str(captured) if captured else None,
                preview=text[:PREVIEW],
                files=embedded_files(index, note),
                gap=str(gap) if gap else None,
            )
        )
    items.sort(key=lambda i: (i.captured or "", i.title), reverse=True)
    return items


def cited_note(index: VaultIndex, note: Note, rules: Rules, *, today: str) -> PurePosixPath:
    """What the extracted notes cite (§12): the source note this one becomes, else the capture
    date's daily note."""
    kind = kind_of(index, note)
    origin = str(note.prop(capture.ORIGIN) or rules.default_origin)
    captured = captured_on(note, today)
    if not capture.keeps_source(kind, note.body, origin, rules):
        return PurePosixPath(rules.types[capture.DAILY].folders[0]) / f"{captured}{NOTE_SUFFIX}"
    pattern = rules.types[capture.SOURCE].title_pattern
    title = (
        note.title  # an email is already named as its source note (§12)
        if kind == capture.EMAIL and pattern is not None and pattern.match(note.title)
        else capture.source_title(captured, kind, capture.subject_of(note.body), rules)
    )
    path = PurePosixPath(rules.types[capture.SOURCE].folders[0]) / f"{title}{NOTE_SUFFIX}"
    if index.path_of(path) is not None:
        raise InboxError(f"a source note named {title!r} already exists")
    return path


def process(
    store: VaultStore,
    ref: str,
    model: LanguageModel,
    *,
    config: Config,
    rules: Rules,
    handbook: str,
    now: datetime,
    created_by: str,
    progress: Progress = lambda step: None,
    new_id: Callable[[], str] = new_note_id,
) -> Extraction:
    """Plan the Inbox note into a pending changeset and save it; raises ``ExtractionError`` or
    ``LLMError`` when no acceptable plan comes back."""
    index = VaultIndex.build(store)
    note = find_note(index, ref)
    if note is None or not _in_inbox(note, rules):
        raise InboxError(f"{ref} isn't a note in the Inbox")
    text = capture.without_embeds(note.body)
    if not text:
        raise InboxError(
            f"{note.title} has no text, only files; add a line saying what it is about"
        )
    cites = cited_note(index, note, rules, today=now.date().isoformat())
    images = screenshots(store, index, note)
    progress(f"Reading the capture and {len(images)} screenshot(s)")
    found = Capture(
        text,
        str(note.prop(capture.ORIGIN) or rules.default_origin),
        note.title,
        images=tuple(images),
        cites=cites,
        inbox=note.path,
    )
    progress("Planning the notes")
    result = plan_extraction(
        found,
        index,
        model,
        config=config,
        handbook=handbook,
        now=now,
        created_by=created_by,
        new_id=new_id,
    )
    cs_store.save(store, result.changeset)
    progress(f"Proposed {len(result.outcomes)} note(s) for review")
    return result
