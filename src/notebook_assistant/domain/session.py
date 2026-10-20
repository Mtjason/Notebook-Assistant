"""A chat session as a note (docs/architecture.md §4.1), as pure functions: created once, then
turns are only appended, so Obsidian Sync merges stay trivial when both PCs touch one.

- :func:`new_session`: the note, in ``<sessions folder>/YYYY/MM/<id>.md``;
- :func:`with_turn`: one more ``## HH:MM · You`` or ``## HH:MM · Assistant`` section, the
  assistant's tool calls folded below its text (``> [!tool]- search("polars dt")``);
- :func:`with_meta`: the notes it cited, the changesets it proposed and its token use, merged
  into the frontmatter;
- :func:`turns`: the sections read back, for the chat screen and the next model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from notebook_assistant.domain.note import NOTE_SUFFIX, Note

Role = Literal["You", "Assistant"]
YOU: Role = "You"
ASSISTANT: Role = "Assistant"
_HEAD = re.compile(r"^## (\d{2}:\d{2}) · (You|Assistant)$", re.M)
_TOOL = re.compile(r"^> \[!tool\]- (.+)$", re.M)


@dataclass(frozen=True)
class Turn:
    role: Role
    time: str  # HH:MM
    text: str
    tools: list[str]  # the tool calls, as `name(argument)`


def session_path(folder: str, session_id: str, started: datetime) -> PurePosixPath:
    return PurePosixPath(folder) / f"{started:%Y}" / f"{started:%m}" / f"{session_id}{NOTE_SUFFIX}"


def new_session(
    folder: str,
    session_id: str,
    *,
    title: str,
    started: datetime,
    device: str,
    model: str,
    scope: str,
) -> Note:
    note = Note(path=session_path(folder, session_id, started), body="")
    fm = note.ensure_frontmatter()
    for key, value in (
        ("id", session_id),
        ("title", title),
        ("started", started.isoformat(timespec="minutes")),
        ("device", device),
        ("model", model),
        ("scope", scope),
    ):
        fm.set(key, value)
    return note


def with_turn(
    note: Note, role: Role, when: datetime, text: str, tools: list[str] | None = None
) -> Note:
    copy = Note.parse(note.path, note.render())
    folded = "".join(f"\n> [!tool]- {t}" for t in tools or [])
    section = f"## {when:%H:%M} · {role}\n\n{text.strip()}\n{folded}\n".replace("\n\n\n", "\n\n")
    copy.body = f"{copy.body.rstrip()}\n\n{section}" if copy.body.strip() else section
    return copy


def _merged(existing: list[object], new: list[str]) -> list[str]:
    return list(dict.fromkeys([*(str(e) for e in existing), *new]))


def with_meta(
    note: Note, *, cited: list[str], changesets: list[str], tokens_in: int, tokens_out: int
) -> Note:
    copy = Note.parse(note.path, note.render())
    fm = copy.ensure_frontmatter()
    links = _merged(fm.get_list("notes_cited"), [f"[[{t}]]" for t in cited])
    if links:
        fm.set("notes_cited", links)
    proposed = _merged(fm.get_list("changesets"), changesets)
    if proposed:
        fm.set("changesets", proposed)
    used = fm.get("tokens")
    before = used if isinstance(used, dict) else {}
    fm.set(
        "tokens",
        {"in": int(before.get("in", 0)) + tokens_in, "out": int(before.get("out", 0)) + tokens_out},
    )
    return copy


def turns(note: Note) -> list[Turn]:
    heads = list(_HEAD.finditer(note.body))
    found: list[Turn] = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(note.body)
        chunk = note.body[head.end() : end]
        tools = _TOOL.findall(chunk)
        text = _TOOL.sub("", chunk).strip()
        role: Role = YOU if head.group(2) == YOU else ASSISTANT
        found.append(Turn(role, head.group(1), text, tools))
    return found
