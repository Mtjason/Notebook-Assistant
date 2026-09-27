"""Vault-backed state in the assistant's state folder (docs/architecture.md §4.1).

The folder itself is defined once, in Handbook §0.1 (Scope), and read from there.

Everything is a Markdown note so it syncs with Obsidian Sync, stays readable, and lets any
installation on any PC continue where another left off. The assistant keeps no local state.
"""

from pathlib import PurePosixPath

from notebook_assistant.handbook import load_rules

ASSISTANT_DIR = PurePosixPath(load_rules().state_prefix.rstrip("/"))
