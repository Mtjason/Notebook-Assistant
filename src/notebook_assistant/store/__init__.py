"""Vault-backed state under ``99-System/Assistant/`` (docs/architecture.md §4.1).

Everything is a Markdown note so it syncs with Obsidian Sync, stays readable, and lets any
installation on any PC continue where another left off. The assistant keeps no local state.
"""

from pathlib import PurePosixPath

ASSISTANT_DIR = PurePosixPath("99-System/Assistant")
