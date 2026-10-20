"""The Sweep changes button (Handbook §16, docs/maintenance-job.md): find the raw notes written
anywhere since the last approved state and propose each as a pending changeset through the
extraction planner (§16.3 row 1), exactly as processing an Inbox note does.

Detect: every note :func:`app.inbox.is_raw` accepts. Settle: one edited within the handbook's
settle time is left for the next run (§16.2). A note that already has a pending proposal is not
planned again (§16.5). Organized notes you edited are covered by Lint (§16.3: keep your wording);
integrating text appended to them is not built yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from notebook_assistant.app import inbox
from notebook_assistant.app.extract import ExtractionError
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.changeset import Status
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.ids import new_note_id
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.llm import LanguageModel, LLMError
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store
from notebook_assistant.store import runs

Progress = Callable[[str], None]


@dataclass
class SweepResult:
    proposed: dict[str, str] = field(default_factory=dict)  # note path → changeset id
    unsettled: list[str] = field(default_factory=list)  # edited too recently (§16.2)
    already_proposed: list[str] = field(default_factory=list)
    blocked: dict[str, str] = field(default_factory=dict)  # path → why it can't be planned
    failed: dict[str, str] = field(default_factory=dict)  # path → why planning failed

    @property
    def summary(self) -> str:
        parts = [f"{len(self.proposed)} proposed"]
        for label, items in (
            ("still being edited", self.unsettled),
            ("already proposed", self.already_proposed),
            ("can't be planned", self.blocked),
            ("failed", self.failed),
        ):
            if items:
                parts.append(f"{len(items)} {label}")
        return ", ".join(parts)


def pending_captures(store: VaultStore) -> set[str]:
    """Raw notes a pending changeset already plans (its capture's Inbox note)."""
    found: set[str] = set()
    for record in cs_store.list_records(store):
        cs = cs_store.load(store, record)
        if cs.status is Status.PENDING and cs.source is not None and cs.source.inbox is not None:
            found.add(cs.source.inbox.as_posix())
    return found


def raw_notes(store: VaultStore, rules: Rules, now: datetime) -> tuple[list[str], list[str]]:
    """(settled, unsettled) raw note paths, in path order."""
    index = VaultIndex.build(store)
    settle = timedelta(minutes=rules.review.settle_minutes)
    settled: list[str] = []
    unsettled: list[str] = []
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        if not inbox.is_raw(note, rules):
            continue
        recent = now - store.modified(note.path) < settle
        (unsettled if recent else settled).append(note.path.as_posix())
    return settled, unsettled


def sweep_changes(
    store: VaultStore,
    model: LanguageModel,
    *,
    config: Config,
    rules: Rules,
    handbook: str,
    now: datetime,
    machine: str,
    progress: Progress = lambda step: None,
    new_id: Callable[[], str] = new_note_id,
) -> SweepResult:
    result = SweepResult()
    settled, result.unsettled = raw_notes(store, rules, now)
    waiting = pending_captures(store)
    index = VaultIndex.build(store)
    todo: list[str] = []
    for path in settled:
        note = index.note(PurePosixPath(path))
        blocked = inbox.blocked_reason(note.path, note) if note else "gone"
        if path in waiting:
            result.already_proposed.append(path)
        elif blocked:
            result.blocked[path] = blocked
        else:
            todo.append(path)
    progress(f"Found {len(todo)} raw note(s) to plan")
    for n, path in enumerate(todo, start=1):
        progress(f"Planning {n}/{len(todo)}: {path}")
        try:
            planned = inbox.process(
                store,
                path,
                model,
                config=config,
                rules=rules,
                handbook=handbook,
                now=now,
                created_by="sweep",
                new_id=new_id,
            )
        except (inbox.InboxError, ExtractionError, LLMError) as exc:
            result.failed[path] = str(exc).splitlines()[0]
            continue
        result.proposed[path] = planned.changeset.id
    runs.append(store, now, machine, "sweep", result.summary)
    progress(f"Done: {result.summary}")
    return result
