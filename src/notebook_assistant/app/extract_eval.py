"""Score a split plan against a fixture capture's ``expected.yaml`` (the digestion eval set,
docs/maintenance-job.md, Extraction, Tests).

An expected atom is found when the plan has an atom with the same role landing in the same
note(s); its target note must also have the expected operation (create or patch), type, topic
folder and shape, and a correction must cite a source. Expected links must exist in the resulting
notes. ``must_not`` lines are prose for the reviewer and aren't scored.

Atom ids are the plan's own names, so matching never depends on them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

from notebook_assistant.domain.frontmatter import load_yaml
from notebook_assistant.domain.links import Resolver, find_links
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.plan_notes import Outcome
from notebook_assistant.domain.split_plan import Atom, NoteOp, Role, SplitPlan


class EvalFormatError(ValueError):
    """An ``expected.yaml`` doesn't have the expected shape."""


@dataclass(frozen=True)
class ExpectedAtom:
    id: str
    role: Role
    notes: tuple[str, ...]
    op: NoteOp | None = None
    type: str | None = None
    topic: str | None = None
    shape: str | None = None  # "collection-rows": the patch adds table rows
    requires_citation: bool = False


@dataclass(frozen=True)
class Expected:
    capture: str  # file name of the capture, next to expected.yaml
    origin: str
    atoms: tuple[ExpectedAtom, ...]
    links: tuple[tuple[str, str], ...]


@dataclass
class Score:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def fraction(self) -> float:
        total = len(self.passed) + len(self.failed)
        return len(self.passed) / total if total else 1.0

    def check(self, ok: bool, what: str) -> None:
        (self.passed if ok else self.failed).append(what)


def _text(data: Mapping[str, object], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise EvalFormatError(f"{where}: {key} must be text")
    return value


def _optional(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    return str(value) if value is not None else None


def _atom(data: object, where: str) -> ExpectedAtom:
    if not isinstance(data, dict):
        raise EvalFormatError(f"{where} must be a mapping")
    target = data.get("target")
    if not isinstance(target, dict):
        raise EvalFormatError(f"{where}: target must be a mapping")
    notes = target.get("notes", [target.get("note")])
    if not isinstance(notes, list) or not all(isinstance(n, str) and n for n in notes):
        raise EvalFormatError(f"{where}: target needs a note or a list of notes")
    try:
        role = Role(_text(data, "role", where))
        op = NoteOp(target["op"]) if "op" in target else None
    except ValueError as exc:
        raise EvalFormatError(f"{where}: {exc}") from None
    return ExpectedAtom(
        id=_text(data, "id", where),
        role=role,
        notes=tuple(notes),
        op=op,
        type=_optional(target, "type"),
        topic=_optional(target, "topic"),
        shape=_optional(target, "shape"),
        requires_citation=data.get("requires_citation") is True,
    )


def parse_expected(text: str) -> Expected:
    try:
        data = load_yaml(text)
    except yaml.YAMLError as exc:
        raise EvalFormatError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise EvalFormatError("expected.yaml must be a mapping")
    atoms = data.get("atoms")
    links = data.get("links", [])
    if not isinstance(atoms, list) or not isinstance(links, list):
        raise EvalFormatError("atoms and links must be lists")
    pairs: list[tuple[str, str]] = []
    for i, link in enumerate(links):
        if not isinstance(link, dict):
            raise EvalFormatError(f"links[{i}] must be a mapping")
        pairs.append((_text(link, "from", f"links[{i}]"), _text(link, "to", f"links[{i}]")))
    return Expected(
        capture=_text(data, "capture", "expected.yaml"),
        origin=_text(data, "origin", "expected.yaml"),
        atoms=tuple(_atom(a, f"atoms[{i}]") for i, a in enumerate(atoms)),
        links=tuple(pairs),
    )


def _matching(plan: SplitPlan, want: ExpectedAtom) -> list[Atom]:
    """The plan's atoms with the expected role, landing in exactly the expected notes."""
    keys = {name_key(n) for n in want.notes}
    return [a for a in plan.atoms if a.role is want.role and {name_key(n) for n in a.notes} == keys]


def _target_ok(want: ExpectedAtom, outcome: Outcome | None) -> str | None:
    """Why the target note doesn't meet ``want``; None if it does."""
    if outcome is None:
        return "the plan has no such note"
    if want.op is not None and outcome.planned.op is not want.op:
        return f"it is a {outcome.planned.op.value}, not a {want.op.value}"
    if want.type is not None and outcome.after.type != want.type:
        return f"its type is {outcome.after.type!r}, not {want.type!r}"
    if want.topic is not None and outcome.after.path.parent.name != want.topic:
        return f"it is in {outcome.after.path.parent}, not the {want.topic} topic"
    if want.shape == "collection-rows" and not any(
        line.lstrip().startswith("|") for line in outcome.added.split("\n")
    ):
        return "it adds no table rows"
    return None


def score(
    plan: SplitPlan,
    outcomes: Mapping[str, Outcome],
    expected: Expected,
    paths: tuple[PurePosixPath, ...],
) -> Score:
    """How much of ``expected`` the plan gets right; ``paths`` are the vault's files after it."""
    result = Score()
    for want in expected.atoms:
        label = f"atom {want.id} ({want.role.value} → {', '.join(want.notes)})"
        found = _matching(plan, want)
        result.check(bool(found), label)
        for title in want.notes:
            problem = _target_ok(want, outcomes.get(name_key(title)))
            result.check(problem is None, f"{label}: {title}" + (f": {problem}" if problem else ""))
        if want.requires_citation:
            result.check(any(a.citation for a in found), f"{label}: cites a source")
    resolver = Resolver(paths)
    for source, target in expected.links:
        outcome = outcomes.get(name_key(source))
        ok = outcome is not None and any(
            (hit := resolver.resolve(link, outcome.after.path)) is not None
            and name_key(hit.stem) == name_key(target)
            for link in find_links(outcome.after.render())
        )
        result.check(ok, f"link {source} → {target}")
    return result
