"""Session retention, the one automatic job (Handbook §16.6, §8.4): once a day, chat sessions
older than the handbook's limit are proposed for deletion as one batch for your approval.

The PC that takes the lease (``store/lease.py``) runs it; a batch already waiting on Review isn't
proposed again. Changesets that came from a deleted session keep its title and date in their own
record, since the record names the session in ``created_by`` and its reason.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.search import is_session
from notebook_assistant.domain.changeset import Changeset, Operation, Status
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store
from notebook_assistant.store import lease, runs

CREATED_BY = "retention"
LEASE_HOURS = 23  # held a little under a day, so tomorrow's run on either PC can take it


def old_sessions(index: VaultIndex, rules: Rules, today: date) -> list[str]:
    """Session notes started more than the handbook's limit ago (§8.4)."""
    cutoff = today - timedelta(days=rules.review.session_days)
    found: list[str] = []
    for note in index.notes.values():
        path = note.path.as_posix()
        started = str(note.prop("started") or "")[:10]
        if is_session(path, rules) and started and date.fromisoformat(started) < cutoff:
            found.append(path)
    return sorted(found)


def _waiting(store: VaultStore) -> bool:
    return any(
        (cs := cs_store.load(store, record)).created_by == CREATED_BY
        and cs.status is Status.PENDING
        for record in cs_store.list_records(store)
    )


def run_retention(store: VaultStore, rules: Rules, *, now: datetime, machine: str) -> str | None:
    """Propose today's batch; returns its changeset id, or None when there's nothing to do, the
    other PC holds the lease, or a batch is already waiting."""
    if not lease.try_acquire(store, machine, now, timedelta(hours=LEASE_HOURS)):
        return None
    index = VaultIndex.build(store)
    old = old_sessions(index, rules, now.date())
    if not old or _waiting(store):
        runs.append(
            store, now, machine, "retention", f"{len(old)} old session(s), nothing proposed"
        )
        return None
    ops: list[Operation] = []
    for path in map(PurePosixPath, old):
        text = index.text(path)
        assert text is not None, "the session comes from the index"
        ops.append(Operation("delete", path, base_hash=content_hash(text), label="old session"))
    cs = Changeset(
        reason=f"Delete {len(old)} chat session(s) older than {rules.review.session_days} days "
        "(Handbook §8.4)",
        created_by=CREATED_BY,
        created=now.isoformat(timespec="seconds"),
        ops=ops,
        machine=machine,
    )
    cs_store.save(store, cs)
    runs.append(store, now, machine, "retention", f"proposed {cs.id}")
    return cs.id
