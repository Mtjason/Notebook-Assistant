"""The lease: which PC runs the daily session-retention job (``99-System/Assistant/Lease.md``).

A PC takes the lease by writing its machine id and an expiry time. Another PC that sees an
unexpired lease held by someone else skips the job. Sync lag can still let two PCs act at
nearly the same time; that is harmless because every write carries a base-hash check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from notebook_assistant.domain.frontmatter import Frontmatter
from notebook_assistant.domain.note import Note
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import ASSISTANT_DIR

LEASE_PATH = ASSISTANT_DIR / "Lease.md"


@dataclass(frozen=True)
class Lease:
    holder: str
    expires: datetime


def read(store: VaultStore) -> Lease | None:
    if not store.exists(LEASE_PATH):
        return None
    note = Note.parse(LEASE_PATH, store.read_text(LEASE_PATH))
    holder, expires = note.prop("holder"), note.prop("expires")
    if not isinstance(holder, str) or not isinstance(expires, str):
        return None
    try:
        return Lease(holder, datetime.fromisoformat(expires))
    except ValueError:
        return None


def try_acquire(store: VaultStore, machine: str, now: datetime, ttl: timedelta) -> bool:
    """Take or renew the lease. Returns False if another machine holds an unexpired lease."""
    current = read(store)
    if current is not None and current.holder != machine and current.expires > now:
        return False
    fm = Frontmatter.from_dict(
        {
            "type": "system",
            "scope": "personal",
            "status": "active",
            "created": now.date().isoformat(),
            "updated": now.date().isoformat(),
        }
    )
    fm.set("holder", machine)
    fm.set("expires", (now + ttl).isoformat(timespec="seconds"))
    body = "Which PC runs the daily session-retention job. Managed by the assistant.\n"
    store.write_text(LEASE_PATH, f"---\n{fm.render()}\n---\n{body}")
    return True


def release(store: VaultStore, machine: str, now: datetime) -> None:
    current = read(store)
    if current is not None and current.holder == machine:
        try_acquire(store, machine, now, timedelta(0))
