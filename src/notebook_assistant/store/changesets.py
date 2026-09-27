"""Changeset records: ``99-System/Assistant/Changesets/YYYY-MM/<id>.md``.

Each record is a readable note:

- frontmatter with status, who proposed it, when, on which machine, and the targets;
- the reason as the heading;
- a unified diff per changed text file (what you review);
- the operations and, once applied, the reverse operations as JSON (what the code runs).
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import PurePosixPath

from notebook_assistant.domain.changeset import Changeset, Operation, Status
from notebook_assistant.domain.frontmatter import Frontmatter
from notebook_assistant.domain.note import Note
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import ASSISTANT_DIR

CHANGESETS_DIR = ASSISTANT_DIR / "Changesets"
_JSON_BLOCK = re.compile(r"^## (Operations|Reverse operations)\n+```json\n(.*?)\n```", re.S | re.M)


def record_path(cs: Changeset) -> PurePosixPath:
    return CHANGESETS_DIR / cs.created[:7] / f"{cs.id}.md"


def unified_diff(store: VaultStore, op: Operation) -> str:
    """Diff for a text-changing operation, against the file's current content."""
    if op.content is None:
        return ""
    before = ""
    if op.kind in ("write", "move") and store.exists(op.path):
        try:
            before = store.read_text(op.path)
        except UnicodeDecodeError:
            return ""
    after_path = op.dest if op.kind == "move" and op.dest is not None else op.path
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        op.content.splitlines(keepends=True),
        fromfile=f"a/{op.path.as_posix()}",
        tofile=f"b/{after_path.as_posix()}",
    )
    return "".join(lines)


def render(cs: Changeset, diffs: dict[int, str] | None = None) -> str:
    fm = Frontmatter.from_dict(
        {
            "type": "system",
            "kind": "changeset",
            "scope": "personal",
            "status": "active",
            "created": cs.created[:10],
            "updated": (cs.applied or cs.created)[:10],
        }
    )
    for key, value in (
        ("id", cs.id),
        ("changeset_status", cs.status.value),
        ("created_at", cs.created),
        ("created_by", cs.created_by),
        ("machine", cs.machine),
        ("applied_at", cs.applied),
        ("error", cs.error),
        ("targets", [p.as_posix() for p in cs.targets]),
    ):
        if value not in (None, "", []):
            fm.set(key, value)
    parts = [f"# {cs.reason}\n"]
    labels = "\n".join(
        f"- `{op.kind}` {op.path.as_posix()}"
        + (f" → {op.dest.as_posix()}" if op.dest else "")
        + (f": {op.label}" if op.label else "")
        for op in cs.ops
    )
    parts.append(f"## Summary\n\n{labels}\n")
    if diffs:
        joined = "\n".join(d.rstrip("\n") for d in diffs.values() if d)
        if joined:
            parts.append(f"## Diff\n\n````diff\n{joined}\n````\n")
    ops_json = json.dumps([op.to_json() for op in cs.ops], ensure_ascii=False, indent=1)
    parts.append(f"## Operations\n\n```json\n{ops_json}\n```\n")
    if cs.reverse_ops:
        rev = json.dumps([op.to_json() for op in cs.reverse_ops], ensure_ascii=False, indent=1)
        parts.append(f"## Reverse operations\n\n```json\n{rev}\n```\n")
    return f"---\n{fm.render()}\n---\n" + "\n".join(parts)


def parse(text: str) -> Changeset:
    note = Note.parse(PurePosixPath("changeset.md"), text)
    props = note.props
    heading = re.search(r"^# (.+)$", note.body, re.M)
    blocks = {m.group(1): json.loads(m.group(2)) for m in _JSON_BLOCK.finditer(note.body)}
    return Changeset(
        reason=heading.group(1) if heading else "",
        created_by=str(props.get("created_by", "")),
        created=str(props.get("created_at", "")),
        ops=[Operation.from_json(o) for o in blocks.get("Operations", [])],
        id=str(props["id"]),
        status=Status(props.get("changeset_status", "pending")),
        machine=str(props.get("machine", "")),
        reverse_ops=[Operation.from_json(o) for o in blocks.get("Reverse operations", [])],
        applied=props.get("applied_at"),
        error=props.get("error"),
    )


_DIFF_BLOCK = re.compile(r"^## Diff\n\n````diff\n(.*?)\n````", re.S | re.M)


def save(store: VaultStore, cs: Changeset, *, with_diff: bool = True) -> PurePosixPath:
    """Write (or overwrite) the changeset's record and return its path.

    With ``with_diff`` the diff is computed against the vault as it is now (for a pending
    proposal). Without it, the diff already in the record is kept, so an applied changeset
    still shows exactly what you reviewed.
    """
    path = record_path(cs)
    diffs: dict[int, str] | None
    if with_diff:
        diffs = {i: unified_diff(store, op) for i, op in enumerate(cs.ops)}
    else:
        previous = _DIFF_BLOCK.search(store.read_text(path)) if store.exists(path) else None
        diffs = {0: previous.group(1)} if previous else None
    store.write_text(path, render(cs, diffs))
    return path


def load(store: VaultStore, path: PurePosixPath) -> Changeset:
    return parse(store.read_text(path))


def list_records(store: VaultStore) -> list[PurePosixPath]:
    prefix = CHANGESETS_DIR.as_posix() + "/"
    return [p for p in store.iter_files() if p.as_posix().startswith(prefix) and p.suffix == ".md"]
