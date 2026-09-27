"""Snapshots: the last approved body of each note (``99-System/Assistant/Snapshots/<id>.md``).

A snapshot lets the sweep tell what you added to an organized note since it was last approved
("integrate only what you added", Handbook §16.3), even after the note was renamed, because
it is keyed by the note's stable ``id``.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import ASSISTANT_DIR

SNAPSHOTS_DIR = ASSISTANT_DIR / "Snapshots"


def snapshot_path(note_id: str) -> PurePosixPath:
    return SNAPSHOTS_DIR / f"{note_id}.md"


def save(store: VaultStore, note_id: str, text: str) -> None:
    store.write_text(snapshot_path(note_id), text)


def load(store: VaultStore, note_id: str) -> str | None:
    path = snapshot_path(note_id)
    return store.read_text(path) if store.exists(path) else None
