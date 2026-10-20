"""What a capture becomes (Handbook §12), as pure functions.

A capture is first saved to the Inbox as it came (an Inbox note, its files in the attachments
folder); processing it later decides what is kept:

- :func:`is_inbox_file`: what counts as waiting in the Inbox;
- :func:`inbox_title`, :func:`attachment_name`, :func:`inbox_note`: the Inbox note for a capture,
  and :func:`email_note` for an email (its headers as properties, §12);
- :func:`keeps_source`: whether processing keeps a ``source`` note or the extracted notes cite
  the daily note (§12);
- :func:`source_title`, :func:`source_note`: the processed capture as a ``source`` note (§4.2,
  §5), linking the notes extracted from it (I-5); :func:`daily_logged`: the daily note logging
  what a short capture produced (§10).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.domain.names import sanitize_title
from notebook_assistant.domain.note import NOTE_SUFFIX, Note
from notebook_assistant.domain.rules import Rules

# Vocabulary (Handbook §4.2, `source` kinds): what a capture is.
TEXT, EMAIL, IMAGE, FILE = "text", "email", "image", "file"
KIND, CAPTURED, ORIGIN, PROCESSED = "kind", "captured", "origin", "processed"
SOURCE, DAILY, ARCHIVED = "source", "daily", "archived"
SUBJECT_WORDS = 8  # a source title's subject is the capture's first words


@dataclass(frozen=True)
class CapturedFile:
    name: str  # the file's own name, e.g. "Screenshot 0931.png"
    data: bytes


@dataclass(frozen=True)
class Email:
    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str  # YYYY-MM-DD
    body: str  # Markdown
    attachments: tuple[CapturedFile, ...]


def is_inbox_file(path: PurePosixPath, rules: Rules) -> bool:
    """A capture waiting in the Inbox: any file there (§10, §12), but not a dotfile such as the
    ``.keep`` that holds an empty folder."""
    return bool(path.parts) and path.parts[0] == rules.inbox and not path.name.startswith(".")


def inbox_title(now: datetime, taken: Callable[[str], bool]) -> str:
    """``YYYY-MM-DD HHMM``, numbered when a note already has that title."""
    base = now.strftime("%Y-%m-%d %H%M")
    title, n = base, 1
    while taken(title):
        n += 1
        title = f"{base} {n}"
    return title


def attachment_name(title: str, n: int, suffix: str) -> str:
    """``<note title> - <n>.<ext>`` (Handbook §5)."""
    return f"{title} - {n}{suffix.lower()}"


def _embeds(names: Iterable[str]) -> str:
    return "\n".join(f"![[{name}]]" for name in names)


def inbox_note(
    path: PurePosixPath,
    text: str,
    *,
    kind: str,
    origin: str,
    captured: str,
    embeds: Iterable[str] = (),
) -> Note:
    """The Inbox note holding a capture as it came: the text, then its files embedded."""
    parts = [p for p in (text.strip(), _embeds(embeds)) if p]
    note = Note(path=path, body="\n\n".join(parts) + "\n")
    fm = note.ensure_frontmatter()
    fm.set(KIND, kind)
    fm.set(ORIGIN, origin)
    fm.set(CAPTURED, captured)
    return note


def email_title(email: Email, rules: Rules) -> str:
    """``YYYY-MM-DD email <subject>`` (§12)."""
    subject = sanitize_title(email.subject or "no subject", rules.names)
    return f"{email.date} {EMAIL} {subject}"


def email_note(
    path: PurePosixPath, email: Email, *, origin: str, embeds: Iterable[str], original: str
) -> Note:
    """An email as a Markdown note: sender, recipients, date and subject as properties, the body
    as Markdown, then its attachments and the original file embedded (§12)."""
    note = inbox_note(
        path,
        email.body,
        kind=EMAIL,
        origin=origin,
        captured=email.date,
        embeds=[*embeds, original],
    )
    fm = note.ensure_frontmatter()
    fm.set("subject", email.subject)
    fm.set("sender", email.sender)
    fm.set("recipients", list(email.recipients))
    fm.set("date", email.date)
    return note


def keeps_source(kind: str, text: str, origin: str, rules: Rules) -> bool:
    """§12: a pasted AI answer never keeps a source note; anything else that isn't text, or text
    over the handbook's length, does; short typed text cites the daily note instead."""
    if origin == rules.capture.ai_origin:
        return False
    if kind != TEXT:
        return True
    return len(text.strip().splitlines()) > rules.capture.long_text_lines


def without_embeds(text: str) -> str:
    """The capture's own words: its text without the files it embeds (the model reads those as
    screenshots, and the embeds stay in the source note)."""
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"!\[\[[^\]]*\]\]", "", text)).strip()


def subject_of(text: str) -> str:
    """The first words of the first line that has any, without Markdown punctuation."""
    for line in text.splitlines():
        words = re.sub(r"!?\[\[[^\]]*\]\]|[#>*`\[\]_-]+", " ", line).split()
        if words:
            return " ".join(words[:SUBJECT_WORDS])
    return ""


def source_title(captured: str, kind: str, subject: str, rules: Rules) -> str:
    """``YYYY-MM-DD <kind> <subject>`` (Handbook §5)."""
    return f"{captured} {kind} {sanitize_title(subject or kind, rules.names)}"


def live_status(rules: Rules, type_name: str) -> str:
    """The one status a ``source`` or ``daily`` note has before archiving (§4.3)."""
    live = sorted(rules.types[type_name].statuses - {ARCHIVED})
    if len(live) != 1:
        raise ValueError(f"§4.3 gives `{type_name}` {len(live)} live statuses; expected one")
    return live[0]


def source_note(
    inbox: Note,
    title: str,
    *,
    rules: Rules,
    scope: str,
    today: str,
    extracted: Iterable[str],
    renames: dict[str, str],
) -> Note:
    """The Inbox note as a ``source`` note in its folder (§3 row 15): the type's properties, its
    attachments under their new names, and links to the notes extracted from it."""
    body = inbox.body
    for old, new in renames.items():
        body = body.replace(f"[[{old}]]", f"[[{new}]]")
    links = "\n".join(f"- [[{t}]]" for t in extracted)
    folder = rules.types[SOURCE].folders[0]
    note = Note.parse(PurePosixPath(folder) / f"{title}{NOTE_SUFFIX}", inbox.render())
    note.body = f"{body.rstrip()}\n\n## Extracted\n\n{links}\n"
    fm = note.ensure_frontmatter()
    captured = str(inbox.prop(CAPTURED) or today)
    for key, value in (
        ("type", SOURCE),
        ("scope", scope),
        ("status", live_status(rules, SOURCE)),
        ("created", captured),
        ("updated", today),
        (CAPTURED, captured),
        (PROCESSED, today),
    ):
        fm.set(key, value)
    return note


def daily_logged(
    daily: Note | None,
    path: PurePosixPath,
    *,
    rules: Rules,
    scope: str,
    today: str,
    extracted: Iterable[str],
) -> Note:
    """The capture date's daily note (created if missing) with a line linking the notes a short
    capture produced: the daily note is the capture log and keeps a link to them (§10, §12)."""
    line = "- Captured " + ", ".join(f"[[{t}]]" for t in extracted)
    if daily is not None:
        note = Note.parse(daily.path, daily.render())
        note.body = f"{note.body.rstrip()}\n{line}\n" if note.body.strip() else f"{line}\n"
        note.ensure_frontmatter().set("updated", today)
        return note
    date = path.name.removesuffix(NOTE_SUFFIX)
    note = Note(path=path, body=f"{line}\n")
    fm = note.ensure_frontmatter()
    for key, value in (
        ("type", DAILY),
        ("scope", scope),
        ("status", live_status(rules, DAILY)),
        ("created", date),
        ("updated", today),
        ("date", date),
    ):
        fm.set(key, value)
    return note
