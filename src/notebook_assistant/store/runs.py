"""Run log: one line per job run in ``99-System/Assistant/Runs/YYYY-MM.md``."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import ASSISTANT_DIR

RUNS_DIR = ASSISTANT_DIR / "Runs"


def runs_path(now: datetime) -> PurePosixPath:
    return RUNS_DIR / f"{now:%Y-%m}.md"


def append(store: VaultStore, now: datetime, machine: str, job: str, outcome: str) -> None:
    path = runs_path(now)
    if store.exists(path):
        text = store.read_text(path)
    else:
        day = now.date().isoformat()
        text = (
            f"---\ntype: system\nscope: personal\nstatus: active\ncreated: {day}\n"
            f"updated: {day}\n---\n# Runs {now:%Y-%m}\n\n"
        )
    if not text.endswith("\n"):
        text += "\n"
    line = f"- {now.isoformat(timespec='seconds')} · {machine} · {job} · {outcome}\n"
    store.write_text(path, text + line)
