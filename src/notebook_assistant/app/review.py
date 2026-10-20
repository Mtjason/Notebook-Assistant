"""The Review screen's use cases (``docs/design.html``, Review): every proposed change in one
place, checked before you apply it.

- :func:`list_changesets`: pending ones, or the history (applied, rejected, reverted, failed);
- :func:`changeset_detail`: the operations with their before/after text, the split map's atoms
  for a planned capture, and :func:`dry_run` checks (base hash, links, handbook rules), made by
  applying a copy inside a sandbox the caller provides (an overlay that keeps writes in memory);
- :func:`apply_selected`, :func:`reject`, :func:`undo`;
- :func:`move_atom_in`: move or drop one atom of a planned capture; the plan is recompiled into
  operations and checked again, with no model call (architecture §5.4.1, branch 4).

Every change still goes through ``app/apply.py``; this module only decides what to ask it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from notebook_assistant.app.apply import ApplyResult, apply_changeset, undo_changeset
from notebook_assistant.app.extract import Capture, compile_changeset, evaluate, split_map
from notebook_assistant.app.filing import FilingError
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.changeset import Changeset, Operation, Status
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.plan_edit import PlanEditError, move_atom
from notebook_assistant.domain.split_plan import parse_plan, plan_to_json
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store

Sandbox = Callable[[VaultStore], VaultStore]  # a view of the vault whose writes go nowhere


class ReviewError(ValueError):
    """The action doesn't fit the changeset (wrong status, unknown operation or atom)."""


@dataclass(frozen=True)
class ChangesetSummary:
    id: str
    reason: str
    created_by: str
    created: str
    status: str
    operations: int


@dataclass(frozen=True)
class OperationView:
    index: int
    kind: str
    path: str
    dest: str | None
    label: str
    before: str | None  # the file's text before the change (None: doesn't exist / binary)
    after: str | None  # its text after (None: deleted)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class AtomView:
    id: str
    role: str
    notes: list[str]
    text: str


@dataclass(frozen=True)
class ChangesetDetail:
    summary: ChangesetSummary
    error: str | None
    review: str  # Markdown: the split map, filler, any topic proposal
    operations: list[OperationView]
    checks: list[CheckResult]
    atoms: list[AtomView]  # empty unless the changeset came from a planned capture
    planned_notes: list[str]  # where an atom may be moved


def summarize(cs: Changeset) -> ChangesetSummary:
    return ChangesetSummary(
        id=cs.id,
        reason=cs.reason,
        created_by=cs.created_by,
        created=cs.created,
        status=cs.status.value,
        operations=len(cs.ops),
    )


def load(store: VaultStore, cs_id: str) -> Changeset:
    path = cs_store.find(store, cs_id)
    if path is None:
        raise ReviewError(f"no changeset {cs_id!r}")
    return cs_store.load(store, path)


def list_changesets(store: VaultStore, *, pending: bool) -> list[ChangesetSummary]:
    """Pending changesets, or every other one (the history), newest first."""
    found = [cs_store.load(store, p) for p in cs_store.list_records(store)]
    chosen = [cs for cs in found if (cs.status is Status.PENDING) == pending]
    return [summarize(cs) for cs in sorted(chosen, key=lambda cs: cs.created, reverse=True)]


def _text(store: VaultStore, op: Operation) -> str | None:
    if not store.exists(op.path):
        return None
    try:
        return store.read_text(op.path)
    except UnicodeDecodeError:
        return None


def operation_views(store: VaultStore, cs: Changeset) -> list[OperationView]:
    """Before and after text per operation: from the vault while pending, from the recorded
    reverse operations once applied."""
    applied = cs.status in (Status.APPLIED, Status.REVERTED) and cs.reverse_ops
    reverse = list(reversed(cs.reverse_ops)) if applied else []
    views: list[OperationView] = []
    for i, op in enumerate(cs.ops):
        if applied:
            undo = reverse[i]
            before = undo.content if op.kind != "create" else None
        else:
            before = _text(store, op) if op.kind != "create" else None
        after = None if op.kind == "delete" else (op.content if op.content is not None else before)
        views.append(
            OperationView(
                index=i,
                kind=op.kind,
                path=op.path.as_posix(),
                dest=op.dest.as_posix() if op.dest else None,
                label=op.label,
                before=before,
                after=after,
            )
        )
    return views


def dry_run(
    store: VaultStore, cs: Changeset, *, now: datetime, sandbox: Sandbox
) -> list[CheckResult]:
    """Apply a copy inside ``sandbox(store)`` and report what the real apply would find."""
    trial = copy.deepcopy(cs)
    trial.status = Status.PENDING
    result = apply_changeset(sandbox(store), trial, now=now)
    error = result.error or ""
    checks = [
        CheckResult("base hash", not error.startswith("stale"), error or "every target unchanged"),
        CheckResult("links", "break links" not in error, error or "no link breaks"),
        CheckResult("rules", "handbook rules" not in error, error or "no new rule violation"),
    ]
    if cs.source is not None:
        checks.insert(0, CheckResult("nothing lost", True, "checked when the capture was planned"))
    if error and all(c.ok for c in checks):
        checks.append(CheckResult("apply", False, error))
    return checks


def changeset_detail(
    store: VaultStore, cs: Changeset, *, now: datetime, sandbox: Sandbox
) -> ChangesetDetail:
    atoms: list[AtomView] = []
    planned: list[str] = []
    if cs.source is not None:
        plan = parse_plan(cs.source.plan)
        atoms = [AtomView(a.id, a.role.value, list(a.notes), a.text) for a in plan.atoms]
        planned = [n.title for n in plan.notes]
    return ChangesetDetail(
        summary=summarize(cs),
        error=cs.error,
        review=cs.review,
        operations=operation_views(store, cs),
        checks=dry_run(store, cs, now=now, sandbox=sandbox) if cs.status is Status.PENDING else [],
        atoms=atoms,
        planned_notes=planned,
    )


def _require_pending(cs: Changeset) -> None:
    if cs.status is not Status.PENDING:
        raise ReviewError(f"changeset {cs.id} is {cs.status.value}, not pending")


def apply_selected(
    store: VaultStore, cs: Changeset, indices: list[int] | None, *, now: datetime, machine: str
) -> ApplyResult:
    """Apply the operations at ``indices`` (all when None); the others are dropped."""
    _require_pending(cs)
    if indices is not None:
        if not indices or any(i < 0 or i >= len(cs.ops) for i in indices):
            raise ReviewError(f"choose operations between 0 and {len(cs.ops) - 1}")
        cs.ops = [cs.ops[i] for i in sorted(set(indices))]
    result = apply_changeset(store, cs, now=now, machine=machine)
    cs_store.save(store, result.changeset, with_diff=False)
    return result


def reject(store: VaultStore, cs: Changeset) -> None:
    _require_pending(cs)
    cs.status = Status.REJECTED
    cs_store.save(store, cs, with_diff=False)


def undo(store: VaultStore, cs: Changeset, *, now: datetime) -> ApplyResult:
    result = undo_changeset(store, cs, now=now)
    if result.ok:
        cs_store.save(store, result.changeset, with_diff=False)
    return result


def move_atom_in(
    store: VaultStore,
    cs: Changeset,
    atom_id: str,
    to: str | None,
    *,
    config: Config,
    now: datetime,
    new_id: Callable[[], str],
) -> list[str]:
    """Move atom ``atom_id`` to the planned note ``to`` (or drop it), recompile and save the
    changeset. Returns the problems that stopped it (the changeset is unchanged then)."""
    _require_pending(cs)
    if cs.source is None:
        raise ReviewError(f"changeset {cs.id} wasn't planned from a capture")
    try:
        edited = move_atom(parse_plan(cs.source.plan), atom_id, to)
    except PlanEditError as exc:
        return [str(exc)]
    capture = Capture(
        cs.source.text,
        cs.source.origin,
        cs.source.name,
        cites=cs.source.cites,
        inbox=cs.source.inbox,
    )
    index = VaultIndex.build(store)
    outcomes, problems = evaluate(
        edited, index, capture, config=config, today=now.date().isoformat(), new_id=new_id
    )
    if problems:
        return problems
    try:
        rebuilt = compile_changeset(
            outcomes,
            index,
            reason=cs.reason,
            created_by=cs.created_by,
            now=now,
            review="",
            source=cs.source,
        )
    except FilingError as exc:
        return [str(exc)]
    cs.ops = rebuilt.ops
    cs.review = split_map(edited, outcomes)
    cs.source = replace(cs.source, plan=plan_to_json(edited))
    cs_store.save(store, cs)
    return []
