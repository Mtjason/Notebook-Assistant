"""A button click in the web app is your approval (Handbook §15 rule 1, §19.2): the changeset it
builds is applied at once (``app/apply.py`` still checks base hashes, links and rules) and its
record saved, so the step shows in Review's history and can be undone there."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.domain.changeset import Changeset
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store


class ApplyRefusedError(ValueError):
    """Apply refused the click's changeset (a stale base hash, a broken link or rule)."""


@dataclass(frozen=True)
class Button:
    """Who clicks, where, when: what every changeset a button makes records."""

    machine: str
    now: datetime

    @property
    def today(self) -> str:
        return self.now.date().isoformat()

    @property
    def stamp(self) -> str:
        return self.now.isoformat(timespec="seconds")


def apply_click(store: VaultStore, cs: Changeset, click: Button) -> str:
    """Record, apply and re-record ``cs``; returns its id, or :class:`ApplyRefusedError`."""
    cs.machine = click.machine
    cs_store.save(store, cs)
    result = apply_changeset(store, cs, now=click.now, machine=click.machine)
    cs_store.save(store, result.changeset, with_diff=False)
    if not result.ok:
        raise ApplyRefusedError(result.error or "apply failed")
    return cs.id
