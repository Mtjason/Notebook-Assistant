"""The split plan: how one capture becomes notes (docs/maintenance-job.md, Extraction, step 5).

The model proposes the plan as JSON matching :data:`PLAN_SCHEMA`; :func:`parse_plan` turns it into
typed data and rejects anything malformed (:class:`PlanFormatError`). Whether the plan is *right*
(coverage, links, rules) is :mod:`notebook_assistant.domain.plan_checks`; turning it into notes is
:mod:`notebook_assistant.domain.plan_notes`.

- An **atom** is a verbatim excerpt of the capture, the smallest piece worth looking up on its
  own, with its role and the note(s) it lands in.
- A **planned note** either creates a note (folder, properties, body) or patches an existing one
  (properties to set, content added under ``##`` headings).
- Both kinds may add ``## History`` lines (Handbook §9.1); the date is added in code.
- A **topic proposal** drafts a new §2.3 topic when the capture fits none (Handbook §2.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from notebook_assistant.domain.jsontypes import JsonObject, JsonValue
from notebook_assistant.domain.names import name_key


class PlanFormatError(ValueError):
    """The model's plan doesn't have the shape of :data:`PLAN_SCHEMA`."""


class Role(StrEnum):
    INSTANCE = "instance"  # the concrete case (Handbook §3.1, instance vs. principle)
    PRINCIPLE = "principle"  # the general rule the case teaches
    EXTRACTED = "extracted"  # an item of another type pulled out on its own (§3.1)
    CORRECTION = "correction"  # a fix to the capture, backed by a cited source (step 6)
    FILLER = "filler"  # conversational filler, dropped and listed on the review card (§8.2)


class NoteOp(StrEnum):
    CREATE = "create"
    PATCH = "patch"


PropertyValue = str | bool | list[str]


@dataclass(frozen=True)
class Atom:
    id: str
    text: str
    role: Role
    notes: tuple[str, ...]  # titles of the notes it lands in
    citation: str  # the source a correction cites; "" otherwise


@dataclass(frozen=True)
class Section:
    heading: str  # an H2 heading, without the "## "
    content: str


@dataclass(frozen=True)
class PlannedNote:
    title: str
    op: NoteOp
    folder: str  # create: the vault folder; patch: ""
    properties: tuple[tuple[str, PropertyValue], ...]
    body: str  # create: the whole body; patch: ""
    sections: tuple[Section, ...]  # patch: content added under these headings
    history: tuple[str, ...]  # ## History lines, without the date


@dataclass(frozen=True)
class TopicProposal:
    """A draft row for the Handbook §2.3 table."""

    folder: str
    answers: str
    examples: str
    not_here: str


@dataclass(frozen=True)
class SplitPlan:
    atoms: tuple[Atom, ...]
    notes: tuple[PlannedNote, ...]
    topic_proposal: TopicProposal | None

    def note(self, title: str) -> PlannedNote | None:
        key = name_key(title)
        return next((n for n in self.notes if name_key(n.title) == key), None)

    def atoms_for(self, title: str) -> list[Atom]:
        key = name_key(title)
        return [a for a in self.atoms if any(name_key(t) == key for t in a.notes)]


def _string(**extra: JsonValue) -> JsonObject:
    return {"type": "string", **extra}


def _object(properties: JsonObject) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(items: JsonObject) -> JsonObject:
    return {"type": "array", "items": items}


PLAN_SCHEMA: JsonObject = _object(
    {
        "atoms": _array(
            _object(
                {
                    "id": _string(),
                    "text": _string(description="verbatim excerpt of the capture"),
                    "role": _string(enum=[r.value for r in Role]),
                    "notes": _array(_string(description="title of a note in `notes`")),
                    "citation": _string(description="URL a correction cites, else empty"),
                }
            )
        ),
        "notes": _array(
            _object(
                {
                    "title": _string(),
                    "op": _string(enum=[o.value for o in NoteOp]),
                    "folder": _string(description="create: vault folder; patch: empty"),
                    "properties": _array(
                        _object(
                            {
                                "key": _string(),
                                "value": {
                                    "anyOf": [
                                        {"type": "string"},
                                        {"type": "boolean"},
                                        _array(_string()),
                                    ]
                                },
                            }
                        )
                    ),
                    "body": _string(description="create: the note body; patch: empty"),
                    "sections": _array(_object({"heading": _string(), "content": _string()})),
                    "history": _array(_string(description="## History line, without the date")),
                }
            )
        ),
        "topic_proposal": {
            "anyOf": [
                {"type": "null"},
                _object(
                    {
                        "folder": _string(),
                        "answers": _string(),
                        "examples": _string(),
                        "not_here": _string(),
                    }
                ),
            ]
        },
    }
)


# --------------------------------------------------------------------------- parsing


def _field(obj: object, key: str, where: str) -> JsonValue:
    if not isinstance(obj, dict):
        raise PlanFormatError(f"{where} must be an object")
    if key not in obj:
        raise PlanFormatError(f"{where} has no {key!r}")
    value: JsonValue = obj[key]
    return value


def _text(obj: object, key: str, where: str) -> str:
    value = _field(obj, key, where)
    if not isinstance(value, str):
        raise PlanFormatError(f"{where}.{key} must be text")
    return value


def _texts(obj: object, key: str, where: str) -> tuple[str, ...]:
    value = _field(obj, key, where)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PlanFormatError(f"{where}.{key} must be a list of text")
    return tuple(str(v) for v in value)


def _items(obj: object, key: str, where: str) -> list[JsonValue]:
    value = _field(obj, key, where)
    if not isinstance(value, list):
        raise PlanFormatError(f"{where}.{key} must be a list")
    return value


_E = TypeVar("_E", bound=StrEnum)


def _choice(enum: type[_E], value: str, where: str) -> _E:
    try:
        return enum(value)
    except ValueError:
        allowed = ", ".join(e.value for e in enum)
        raise PlanFormatError(f"{where} is {value!r}; expected one of {allowed}") from None


def _property(item: JsonValue, where: str) -> tuple[str, PropertyValue]:
    key = _text(item, "key", where)
    value = _field(item, "value", where)
    if isinstance(value, bool | str):
        return key, value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return key, [str(v) for v in value]
    raise PlanFormatError(f"{where} ({key}) must be text, true/false or a list of text")


def _atom(item: JsonValue, where: str) -> Atom:
    return Atom(
        id=_text(item, "id", where),
        text=_text(item, "text", where),
        role=_choice(Role, _text(item, "role", where), f"{where}.role"),
        notes=_texts(item, "notes", where),
        citation=_text(item, "citation", where),
    )


def _note(item: JsonValue, where: str) -> PlannedNote:
    return PlannedNote(
        title=_text(item, "title", where),
        op=_choice(NoteOp, _text(item, "op", where), f"{where}.op"),
        folder=_text(item, "folder", where).strip("/"),
        properties=tuple(
            _property(p, f"{where}.properties[{i}]")
            for i, p in enumerate(_items(item, "properties", where))
        ),
        body=_text(item, "body", where),
        sections=tuple(
            Section(_text(s, "heading", w), _text(s, "content", w))
            for i, s in enumerate(_items(item, "sections", where))
            for w in [f"{where}.sections[{i}]"]
        ),
        history=_texts(item, "history", where),
    )


def _proposal(value: JsonValue) -> TopicProposal | None:
    if value is None:
        return None
    where = "topic_proposal"
    return TopicProposal(
        folder=_text(value, "folder", where).strip("/"),
        answers=_text(value, "answers", where),
        examples=_text(value, "examples", where),
        not_here=_text(value, "not_here", where),
    )


def _unique(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        key = name_key(value)
        if key in seen:
            raise PlanFormatError(f"two {what} are named {value!r}")
        seen.add(key)


def parse_plan(data: JsonObject) -> SplitPlan:
    """Typed plan from the model's JSON; :class:`PlanFormatError` on any shape problem."""
    atoms = tuple(_atom(a, f"atoms[{i}]") for i, a in enumerate(_items(data, "atoms", "plan")))
    notes = tuple(_note(n, f"notes[{i}]") for i, n in enumerate(_items(data, "notes", "plan")))
    _unique([a.id for a in atoms], "atoms")
    _unique([n.title for n in notes], "notes")
    return SplitPlan(atoms, notes, _proposal(_field(data, "topic_proposal", "plan")))
