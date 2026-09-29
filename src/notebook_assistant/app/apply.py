"""Apply an approved changeset, all or nothing, and undo it later.

Steps:

1. **Pre-check** every operation: targets of ``write``/``move``/``delete`` still have their base
   hash (you haven't edited them since the proposal); ``create``/``move`` targets are free.
2. **Execute** in order, recording a reverse operation for each.
3. **Verify links:** every reference that resolved before must still resolve, to the same file
   (followed through the changeset's moves). Deleting a file that is still linked fails.
4. **Re-check the rules:** no note the changeset creates, writes or moves may gain a handbook
   violation (``new_violations``), whatever produced the changeset.
5. On any failure, **roll back** the executed operations in reverse order. The changeset is
   marked ``failed`` with the reason, and the vault is as it was.

Undo applies the stored reverse operations, with the same checks, so an undo also refuses if
you edited a file after the changeset was applied.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.changeset import Changeset, Operation, Status
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.invariants import new_violations
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import is_note_path
from notebook_assistant.ports.vault import VaultError, VaultStore


class StaleChangesetError(VaultError):
    """A target changed since the changeset was proposed."""


class BrokenLinksError(VaultError):
    """Applying the changeset would break links."""


@dataclass(frozen=True)
class ApplyResult:
    changeset: Changeset
    ok: bool
    error: str | None = None


def _key(path: PurePosixPath) -> str:
    return name_key(path.as_posix())


def precheck(store: VaultStore, ops: list[Operation]) -> None:
    """Raise :class:`StaleChangesetError` if any operation can't apply to the current vault."""
    planned_moves = {_key(op.path): op for op in ops if op.kind == "move"}
    for op in ops:
        if op.kind == "create":
            if store.exists(op.path):
                raise StaleChangesetError(f"{op.path} already exists")
            continue
        if not store.exists(op.path):
            raise StaleChangesetError(f"{op.path} no longer exists")
        if op.base_hash is not None and content_hash(store.read_bytes(op.path)) != op.base_hash:
            raise StaleChangesetError(f"{op.path} changed since the proposal was made")
        if op.kind == "move" and op.dest is not None:
            case_only = _key(op.dest) == _key(op.path)
            if store.exists(op.dest) and not case_only and _key(op.dest) not in planned_moves:
                raise StaleChangesetError(f"{op.dest} already exists")


def _execute(store: VaultStore, op: Operation) -> Operation:
    """Run one operation and return the operation that reverses it."""
    if op.kind == "create":
        assert op.content is not None, "create needs content"
        store.write_text(op.path, op.content)
        return Operation("delete", op.path, base_hash=content_hash(op.content), label="undo create")
    if op.kind == "write":
        assert op.content is not None, "write needs content"
        old = store.read_bytes(op.path)
        store.write_text(op.path, op.content)
        return Operation(
            "write",
            op.path,
            content=old.decode("utf-8"),
            base_hash=content_hash(op.content),
            label="undo edit",
        )
    if op.kind == "move":
        assert op.dest is not None, "move needs dest"
        old = store.read_bytes(op.path)
        store.move(op.path, op.dest)
        if op.content is not None:
            store.write_text(op.dest, op.content)
        new_bytes = op.content.encode("utf-8") if op.content is not None else old
        return Operation(
            "move",
            op.dest,
            dest=op.path,
            content=old.decode("utf-8") if op.content is not None else None,
            base_hash=content_hash(new_bytes),
            label="undo move",
        )
    if op.kind == "delete":
        old = store.read_bytes(op.path)
        store.delete(op.path)
        try:
            return Operation("create", op.path, content=old.decode("utf-8"), label="undo delete")
        except UnicodeDecodeError:
            return Operation(
                "create",
                op.path,
                content_b64=base64.b64encode(old).decode("ascii"),
                label="undo delete",
            )
    raise ValueError(f"unknown operation kind: {op.kind}")


def _execute_create_binary(store: VaultStore, op: Operation) -> Operation:
    assert op.content_b64 is not None
    data = base64.b64decode(op.content_b64)
    store.write_bytes(op.path, data)
    return Operation("delete", op.path, base_hash=content_hash(data), label="undo create")


def run_ops(store: VaultStore, ops: list[Operation]) -> list[Operation]:
    """Execute ``ops``; on error roll back what ran and re-raise. Returns reverse ops (in order)."""
    done: list[Operation] = []
    try:
        for op in ops:
            if op.kind == "create" and op.content is None and op.content_b64 is not None:
                done.append(_execute_create_binary(store, op))
            else:
                done.append(_execute(store, op))
    except Exception:
        _rollback(store, done)
        raise
    return done


def _rollback(store: VaultStore, reverse_ops: list[Operation]) -> None:
    for rev in reversed(reverse_ops):
        if rev.kind == "create" and rev.content is None and rev.content_b64 is not None:
            _execute_create_binary(store, rev)
        else:
            _execute(store, rev)


def link_signature(index: VaultIndex, moves: dict[str, PurePosixPath]) -> dict[str, Counter[str]]:
    """Per source file: how many links resolve to each target, with paths mapped through moves."""

    def mapped(path: PurePosixPath) -> str:
        return _key(moves.get(_key(path), path))

    signature: dict[str, Counter[str]] = {}
    for refs in index.refs_by_source.values():
        if refs:
            signature[mapped(refs[0].source)] = Counter(mapped(r.target) for r in refs)
    return signature


def verify_links(before: VaultIndex, after: VaultIndex, ops: list[Operation]) -> list[str]:
    """Links the changeset broke.

    - In files the changeset doesn't edit, every link that resolved before must still resolve,
      to the same file (followed through the changeset's moves).
    - In any file, a link that points nowhere after applying must already have pointed nowhere
      before. A file the changeset edits may drop links on purpose (e.g. an embed removed
      before its image is deleted), but it may not leave one dangling.
    """
    moves = {_key(op.path): op.dest for op in ops if op.kind == "move" and op.dest is not None}

    def mapped(path: PurePosixPath) -> str:
        return _key(moves.get(_key(path), path))

    edited = {mapped(op.path) for op in ops if op.kind == "write"} | {
        _key(op.dest) for op in ops if op.kind == "move" and op.dest is not None and op.content
    }
    deleted = {_key(op.path) for op in ops if op.kind == "delete"}
    sig_before = link_signature(before, moves)
    sig_after = link_signature(after, {})
    problems: list[str] = []
    for source, targets in sig_before.items():
        if source in deleted or source in edited:
            continue
        now = sig_after.get(source, Counter())
        for target, count in targets.items():
            if now[target] < count:
                problems.append(f"{source}: {count - now[target]} link(s) to {target} broke")
    already_broken = {(mapped(src), link.target.casefold()) for src, link in before.broken}
    for src, link in after.broken:
        if (_key(src), link.target.casefold()) not in already_broken:
            problems.append(f"{src}: link to {link.target!r} points nowhere")
    return problems


def rule_violations(before: VaultIndex, after: VaultIndex, ops: list[Operation]) -> list[str]:
    """Handbook violations the changeset introduced in the notes it created, wrote or moved."""
    problems: list[str] = []
    facts = after.facts()
    for op in ops:
        if op.kind == "delete":
            continue
        result_path = op.dest if op.kind == "move" and op.dest is not None else op.path
        note = after.note(result_path) if is_note_path(result_path) else None
        if note is None:
            continue
        old = before.note(op.path) if op.kind != "create" else None
        problems.extend(
            f"{result_path}: {v.code} {v.message} ({v.section})"
            for v in new_violations(old, note, facts)
        )
    return problems


def apply_changeset(
    store: VaultStore, cs: Changeset, *, now: datetime, machine: str = ""
) -> ApplyResult:
    if cs.status is not Status.PENDING:
        return ApplyResult(cs, False, f"changeset is {cs.status.value}, not pending")
    try:
        precheck(store, cs.ops)
    except StaleChangesetError as exc:
        cs.status, cs.error = Status.FAILED, f"stale: {exc}"
        return ApplyResult(cs, False, cs.error)

    before = VaultIndex.build(store)
    try:
        reverse = run_ops(store, cs.ops)
    except Exception as exc:  # rolled back inside run_ops
        cs.status, cs.error = Status.FAILED, f"apply failed and was rolled back: {exc}"
        return ApplyResult(cs, False, cs.error)

    after = VaultIndex.build(store)
    broken = verify_links(before, after, cs.ops)
    if broken:
        _rollback(store, reverse)
        cs.status = Status.FAILED
        cs.error = "would break links, rolled back: " + "; ".join(broken[:5])
        return ApplyResult(cs, False, cs.error)
    violations = rule_violations(before, after, cs.ops)
    if violations:
        _rollback(store, reverse)
        cs.status = Status.FAILED
        cs.error = "would break handbook rules, rolled back: " + "; ".join(violations[:5])
        return ApplyResult(cs, False, cs.error)

    cs.status = Status.APPLIED
    cs.reverse_ops = list(reversed(reverse))  # undo runs them in this order
    cs.applied = now.isoformat(timespec="seconds")
    cs.machine = machine or cs.machine
    cs.error = None
    return ApplyResult(cs, True)


def undo_changeset(store: VaultStore, cs: Changeset, *, now: datetime) -> ApplyResult:
    """Revert an applied changeset using its reverse operations."""
    if cs.status is not Status.APPLIED:
        return ApplyResult(cs, False, f"only applied changesets can be undone ({cs.status.value})")
    try:
        precheck(store, cs.reverse_ops)
        run_ops(store, cs.reverse_ops)
    except (StaleChangesetError, VaultError) as exc:
        return ApplyResult(cs, False, f"can't undo: {exc}")
    cs.status = Status.REVERTED
    cs.error = None
    return ApplyResult(cs, True)
