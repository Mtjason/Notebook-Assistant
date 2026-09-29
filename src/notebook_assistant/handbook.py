"""Load the vault rules from the one Vault Handbook (``docs/handbook.md``).

Where the text comes from, in order:

1. ``NA_HANDBOOK``: a path, for trying out a handbook change before merging it;
2. the handbook built into the installed package (the release was tested against it);
3. ``docs/handbook.md`` of the source checkout (development).

2 and 3 are the same file: the wheel build packages ``docs/handbook.md`` as-is, it is never
edited separately.
"""

from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources
from pathlib import Path

from notebook_assistant.domain.rules import Rules, parse_handbook

PACKAGED_NAME = "_handbook.md"


def handbook_path() -> Path:
    override = os.environ.get("NA_HANDBOOK")
    if override:
        return Path(override)
    packaged = resources.files("notebook_assistant") / PACKAGED_NAME
    if packaged.is_file():
        return Path(str(packaged))
    source = Path(__file__).resolve().parents[2] / "docs" / "handbook.md"
    if source.is_file():
        return source
    raise FileNotFoundError("Vault Handbook not found (set NA_HANDBOOK or reinstall)")


@lru_cache(maxsize=4)
def _read(path: str, mtime_ns: int) -> str:
    return Path(path).read_text(encoding="utf-8")


@lru_cache(maxsize=4)
def _load(path: str, mtime_ns: int) -> Rules:
    return parse_handbook(_read(path, mtime_ns))


def handbook_text() -> str:
    """The handbook itself, as the planners give it to the model (re-read when it changes)."""
    path = handbook_path()
    return _read(str(path), path.stat().st_mtime_ns)


def load_rules() -> Rules:
    """The current rules (re-read when the handbook file changes)."""
    path = handbook_path()
    return _load(str(path), path.stat().st_mtime_ns)
