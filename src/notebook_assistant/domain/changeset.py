"""Changesets: every change to the vault, proposed first and applied only after approval.

A changeset is an ordered list of file operations. Each operation that touches an existing file
records that file's **base hash**, the content fingerprint when the proposal was made. Applying
refuses if the file changed since (Handbook §16.4 rule 4), so a stale proposal can never
overwrite your edits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from notebook_assistant.domain.ids import new_changeset_id


class Status(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"
    REVERTED = "reverted"
    FAILED = "failed"


OpKind = Literal["create", "write", "move", "delete"]


@dataclass(frozen=True)
class Operation:
    """One file operation.

    - ``create``: write ``content`` to a new file at ``path`` (must not exist).
    - ``write``: replace the content of ``path`` (must still have ``base_hash``).
    - ``move``: move ``path`` to ``dest`` (``path`` must still have ``base_hash``).
    - ``delete``: delete ``path`` (must still have ``base_hash``).

    A ``move`` may carry ``content``: the file is moved, then rewritten (e.g. a renamed note
    whose ``aliases`` gained its old title). ``content`` is text; ``content_b64`` carries binary
    content, used only by reverse operations that restore a deleted attachment.
    """

    kind: OpKind
    path: PurePosixPath
    content: str | None = None
    dest: PurePosixPath | None = None
    base_hash: str | None = None
    label: str = ""  # short human description, e.g. "rewrite 3 links"
    content_b64: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "path": self.path.as_posix()}
        if self.dest is not None:
            data["dest"] = self.dest.as_posix()
        if self.base_hash is not None:
            data["base_hash"] = self.base_hash
        if self.label:
            data["label"] = self.label
        if self.content is not None:
            data["content"] = self.content
        if self.content_b64 is not None:
            data["content_b64"] = self.content_b64
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Operation:
        return cls(
            kind=data["kind"],
            path=PurePosixPath(data["path"]),
            content=data.get("content"),
            dest=PurePosixPath(data["dest"]) if data.get("dest") else None,
            base_hash=data.get("base_hash"),
            label=data.get("label", ""),
            content_b64=data.get("content_b64"),
        )


@dataclass
class Changeset:
    reason: str
    created_by: str  # "session:<id>", "sweep", "button:<name>", "user"
    created: str  # ISO timestamp
    ops: list[Operation] = field(default_factory=list)
    id: str = field(default_factory=new_changeset_id)
    status: Status = Status.PENDING
    machine: str = ""
    reverse_ops: list[Operation] = field(default_factory=list)  # filled when applied
    applied: str | None = None
    error: str | None = None

    @property
    def targets(self) -> list[PurePosixPath]:
        seen: dict[str, PurePosixPath] = {}
        for op in self.ops:
            for p in (op.path, op.dest):
                if p is not None:
                    seen.setdefault(p.as_posix(), p)
        return list(seen.values())
