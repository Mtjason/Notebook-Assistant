"""Edit a split plan by hand: move one atom to another planned note, or drop it (the Review
screen, docs/architecture.md §5.4.1 branch 4). No model call: the atom's verbatim text is cut
from the notes it landed in and added to the new one, and the plan is checked again
(:mod:`plan_checks`) before it replaces the old one.

A dropped atom becomes filler: it leaves the notes and is listed as dropped, so the
nothing-lost check no longer expects it.
"""

from __future__ import annotations

import re
from dataclasses import replace

from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.split_plan import (
    Atom,
    NoteOp,
    PlannedNote,
    Role,
    Section,
    SplitPlan,
)

MOVED_HEADING = "From the capture"  # where a moved atom lands in a patch with no section


class PlanEditError(ValueError):
    """The edit can't be made (unknown atom or note, or the atom's text isn't in its note)."""


def _cut(text: str, piece: str) -> tuple[str, bool]:
    index = text.find(piece)
    if index < 0:
        return text, False
    rest = text[:index] + text[index + len(piece) :]
    return re.sub(r"\n{3,}", "\n\n", rest).strip("\n") + ("\n" if text.endswith("\n") else ""), True


def _without(note: PlannedNote, piece: str) -> tuple[PlannedNote, bool]:
    body, found = _cut(note.body, piece)
    if found:
        return replace(note, body=body), True
    for i, section in enumerate(note.sections):
        content, found = _cut(section.content, piece)
        if found:
            sections = (
                *note.sections[:i],
                replace(section, content=content),
                *note.sections[i + 1 :],
            )
            return replace(note, sections=sections), True
    return note, False


def _with(note: PlannedNote, piece: str) -> PlannedNote:
    if note.op is NoteOp.CREATE:
        return replace(note, body=f"{note.body.rstrip()}\n\n{piece}\n")
    if note.sections:
        last = note.sections[-1]
        moved = replace(last, content=f"{last.content.rstrip()}\n\n{piece}")
        return replace(note, sections=(*note.sections[:-1], moved))
    return replace(note, sections=(Section(MOVED_HEADING, piece),))


def move_atom(plan: SplitPlan, atom_id: str, to: str | None) -> SplitPlan:
    """``plan`` with atom ``atom_id`` moved to the planned note titled ``to``, or dropped."""
    atom = next((a for a in plan.atoms if a.id == atom_id), None)
    if atom is None:
        raise PlanEditError(f"the plan has no atom {atom_id!r}")
    target = plan.note(to) if to is not None else None
    if to is not None and target is None:
        raise PlanEditError(f"the plan has no note {to!r}")
    for other in plan.atoms:
        if (
            other.id != atom_id
            and other.notes
            and (atom.text in other.text or other.text in atom.text)
        ):
            raise PlanEditError(f"atom {atom_id} overlaps atom {other.id}; move or drop that one")
    notes = list(plan.notes)
    for title in atom.notes:
        index = next(i for i, n in enumerate(notes) if name_key(n.title) == name_key(title))
        edited, found = _without(notes[index], atom.text)
        if not found:
            raise PlanEditError(
                f"atom {atom_id}'s text isn't verbatim in {title}; edit that note after applying"
            )
        notes[index] = edited
    if target is not None:
        index = next(i for i, n in enumerate(notes) if name_key(n.title) == name_key(target.title))
        notes[index] = _with(notes[index], atom.text)
        role = Role.EXTRACTED if atom.role is Role.FILLER else atom.role
        moved: Atom = replace(atom, notes=(target.title,), role=role)
    else:
        moved = replace(atom, notes=(), role=Role.FILLER, citation="")
    atoms = tuple(moved if a.id == atom_id else a for a in plan.atoms)
    return replace(plan, atoms=atoms, notes=tuple(notes))
