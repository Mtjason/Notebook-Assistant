"""Saving a capture to the Inbox from the web app (Handbook §12; §14: capture whenever).

The click is your approval (:mod:`app.clicks`): the Inbox note and its files are created in one
changeset applied at once. Nothing is classified yet; processing does that (:mod:`app.inbox`).

- Text (typed, pasted, or a ``.md``/``.txt`` file) and other files go in one Inbox note: the
  text, then each file saved to the attachments folder under the note's name and embedded.
- Each email (the formats §12 names) becomes its own note, ``YYYY-MM-DD email <subject>``, with
  its headers as properties, its attachments and the original file.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from notebook_assistant.app.clicks import ApplyRefusedError, Button, apply_click
from notebook_assistant.app.images import media_type
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain import capture
from notebook_assistant.domain.capture import CapturedFile
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import NOTE_SUFFIX, Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.email import EmailError, EmailReader
from notebook_assistant.ports.vault import VaultStore

TEXT_SUFFIXES = (".md", ".txt")  # files whose text is captured as typed text


class CaptureError(ValueError):
    """Nothing to capture, an unknown origin, an unreadable file, or apply refused."""


@dataclass(frozen=True)
class CaptureOutcome:
    paths: list[str]  # the Inbox notes created
    changeset: str


def _binary(path: PurePosixPath, data: bytes) -> Operation:
    return Operation(
        "create", path, content_b64=base64.b64encode(data).decode("ascii"), label="captured file"
    )


class _Names:
    """Titles and file names already used, so a capture never collides (compared like NTFS)."""

    def __init__(self, index: VaultIndex) -> None:
        self._used = {name_key(p.name.removesuffix(NOTE_SUFFIX)) for p in index.files}

    def take(self, name: str) -> bool:
        return name_key(name) in self._used

    def add(self, name: str) -> str:
        if self.take(name):
            raise CaptureError(f"{name} already exists")
        self._used.add(name_key(name))
        return name


def _kind(files: Sequence[CapturedFile]) -> str:
    if not files:
        return capture.TEXT
    if all(media_type(PurePosixPath(f.name)) for f in files):
        return capture.IMAGE
    return capture.FILE


def _note_ops(note: Note, files: Sequence[CapturedFile], folder: PurePosixPath) -> list[Operation]:
    return [
        *(_binary(folder / f.name, f.data) for f in files),
        Operation("create", note.path, content=note.render(), label="Inbox note"),
    ]


def _attach(title: str, files: Sequence[CapturedFile], names: _Names) -> list[CapturedFile]:
    """The files renamed ``<title> - <n>.<ext>`` (§5), numbered in order."""
    return [
        CapturedFile(
            names.add(capture.attachment_name(title, n, PurePosixPath(f.name).suffix)), f.data
        )
        for n, f in enumerate(files, start=1)
    ]


def capture_to_inbox(
    store: VaultStore,
    *,
    text: str,
    files: Sequence[CapturedFile],
    origin: str,
    rules: Rules,
    click: Button,
    read_email: EmailReader,
) -> CaptureOutcome:
    if origin not in rules.common_enums["origin"]:
        raise CaptureError(f"unknown origin {origin!r} (Handbook §4.1)")
    emails = [
        f for f in files if PurePosixPath(f.name).suffix.lower() in rules.capture.email_formats
    ]
    texts = [f for f in files if PurePosixPath(f.name).suffix.lower() in TEXT_SUFFIXES]
    others = [f for f in files if f not in emails and f not in texts]
    typed = "\n\n".join(
        [text.strip()] + [f.data.decode("utf-8", "replace").strip() for f in texts]
    ).strip()
    if not (typed or others or emails):
        raise CaptureError("nothing to capture")

    index = VaultIndex.build(store)
    names = _Names(index)
    inbox, folder = PurePosixPath(rules.inbox), PurePosixPath(rules.capture.attachments)
    ops: list[Operation] = []
    paths: list[str] = []
    if typed or others:
        title = names.add(capture.inbox_title(click.now, names.take))
        attached = _attach(title, others, names)
        note = capture.inbox_note(
            inbox / f"{title}{NOTE_SUFFIX}",
            typed,
            kind=_kind(others),
            origin=origin,
            captured=click.today,
            embeds=[f.name for f in attached],
        )
        ops += _note_ops(note, attached, folder)
        paths.append(note.path.as_posix())
    for file in emails:
        try:
            email = read_email(file.name, file.data)
        except EmailError as exc:
            raise CaptureError(f"{file.name}: {exc}") from exc
        title = names.add(capture.email_title(email, rules))
        *attached, original = _attach(title, [*email.attachments, file], names)
        note = capture.email_note(
            inbox / f"{title}{NOTE_SUFFIX}",
            email,
            origin=origin,
            embeds=[f.name for f in attached],
            original=original.name,
        )
        ops += _note_ops(note, [*attached, original], folder)
        paths.append(note.path.as_posix())

    cs = Changeset(
        reason=f"Capture to the Inbox: {', '.join(PurePosixPath(p).stem for p in paths)}",
        created_by="button:capture",
        created=click.stamp,
        ops=ops,
    )
    try:
        return CaptureOutcome(paths, apply_click(store, cs, click))
    except ApplyRefusedError as exc:
        raise CaptureError(str(exc)) from exc
