"""Turn planned notes into the notes they produce (docs/maintenance-job.md, Extraction).

- A **created** note gets the plan's properties plus the ones the assistant owns: ``id`` (Handbook
  §4.1, §5.2), and :data:`DATES` set to today (§9.2). These win over anything the plan says.
- A **patched** note changes only by addition, so your wording is never rewritten (Handbook §16.4
  rule 2): the plan's properties are set through ``Frontmatter.set`` (minimal diff), ``updated``
  becomes today, content goes at the end of the named ``##`` section (a new section if it's
  missing), and history lines go under ``## History`` (Handbook §9.1).

A plan that sets a property the assistant manages is rejected by :mod:`plan_checks`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from notebook_assistant.domain.frontmatter import Frontmatter
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import NOTE_SUFFIX, Note
from notebook_assistant.domain.split_plan import NoteOp, PlannedNote, SplitPlan

DATES = ("created", "updated")  # set by the assistant when it writes a note (Handbook §9.2)
HISTORY = "History"


def note_path(planned: PlannedNote) -> PurePosixPath:
    """Where a created note goes: its folder and title."""
    return PurePosixPath(planned.folder) / f"{planned.title}{NOTE_SUFFIX}"


def _heading(title: str) -> re.Pattern[str]:
    return re.compile(rf"^##[ \t]+{re.escape(title.strip())}[ \t]*$", re.M)


_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _continues(last_line: str, first_line: str) -> bool:
    """Whether ``first_line`` continues the table or list that ``last_line`` ends."""
    table = last_line.lstrip().startswith("|") and first_line.lstrip().startswith("|")
    listed = bool(_LIST_ITEM.match(last_line) and _LIST_ITEM.match(first_line))
    return table or listed


def add_to_section(body: str, heading: str, content: str) -> str:
    """``content`` appended at the end of the ``## heading`` section, which is created (before
    ``## History``, else at the end) when the body has none. Rows added under a table, or items
    under a list, extend it instead of starting a new one."""
    content = content.strip("\n")
    head = _heading(heading).search(body)
    if head is None:
        block = f"## {heading.strip()}\n\n{content}\n"
        history = _heading(HISTORY).search(body) if heading.strip() != HISTORY else None
        if history is not None:
            return f"{body[: history.start()]}{block}\n{body[history.start() :]}"
        kept = body.rstrip("\n")
        return f"{kept}\n\n{block}" if kept.strip() else block
    nxt = re.compile(r"^#{1,2}[ \t]", re.M).search(body, head.end())
    end = nxt.start() if nxt else len(body)
    section = body[head.end() : end].rstrip("\n")
    rest = body[end:]
    if not section.strip():
        joined = f"\n\n{content}"
    else:
        gap = "\n" if _continues(section.split("\n")[-1], content.split("\n")[0]) else "\n\n"
        joined = f"{section}{gap}{content}"
    return f"{body[: head.end()]}{joined}\n" + (f"\n{rest}" if rest else "")


def add_history(body: str, lines: tuple[str, ...], today: str) -> str:
    """Dated ``## History`` lines (Handbook §9.1), in order."""
    if not lines:
        return body
    entries = "\n".join(f"- {today}: {line.strip()}" for line in lines)
    return add_to_section(body, HISTORY, entries)


def created_note(planned: PlannedNote, *, today: str, note_id: str) -> Note:
    fm = Frontmatter.from_dict(
        {**dict(planned.properties), "id": note_id, **dict.fromkeys(DATES, today)}
    )
    body = planned.body.strip("\n") + "\n"
    return Note(note_path(planned), add_history(body, planned.history, today), fm)


def patched_note(existing: Note, planned: PlannedNote, *, today: str, note_id: str) -> Note:
    """``existing`` with the plan's additions; ``note_id`` is used only if it has no ``id``."""
    note = Note.parse(existing.path, existing.render())
    fm = note.ensure_frontmatter()
    for key, value in planned.properties:
        fm.set(key, value)
    if fm.get("id") is None:
        fm.set("id", note_id)
    fm.set("updated", today)
    body = note.body
    for section in planned.sections:
        body = add_to_section(body, section.heading, section.content)
    note.body = add_history(body, planned.history, today)
    return note


def added_text(before: Note | None, after: Note) -> str:
    """What the plan wrote: a created note's whole text, or a patched note's new lines."""
    if before is None:
        return after.render()
    old = before.render().replace("\r\n", "\n").split("\n")
    new = after.render().replace("\r\n", "\n").split("\n")
    remaining = list(old)
    added: list[str] = []
    for line in new:
        if line in remaining:
            remaining.remove(line)
        else:
            added.append(line)
    return "\n".join(added)


@dataclass(frozen=True)
class Outcome:
    """One planned note and the note it produces (``before`` is None for a created note)."""

    planned: PlannedNote
    before: Note | None
    after: Note

    @property
    def added(self) -> str:
        return added_text(self.before, self.after)


def build_outcomes(
    plan: SplitPlan,
    existing: Mapping[str, Note],
    *,
    today: str,
    new_id: Callable[[], str],
) -> tuple[dict[str, Outcome], list[str]]:
    """Every planned note's result, keyed by ``name_key(title)``, and the notes that can't be
    built: a patch of a note that doesn't exist, or a create of a title that already does (it
    must be patched instead, Handbook §15.3). ``existing`` maps ``name_key(title)`` to a note."""
    outcomes: dict[str, Outcome] = {}
    problems: list[str] = []
    for planned in plan.notes:
        key = name_key(planned.title)
        current = existing.get(key)
        if planned.op is NoteOp.PATCH:
            if current is None:
                problems.append(f"{planned.title}: patched, but no such note exists")
                continue
            after = patched_note(current, planned, today=today, note_id=new_id())
            outcomes[key] = Outcome(planned, current, after)
        else:
            if current is not None:
                problems.append(f"{planned.title}: already exists; patch it instead (§15.3)")
                continue
            outcomes[key] = Outcome(
                planned, None, created_note(planned, today=today, note_id=new_id())
            )
    return outcomes, problems
