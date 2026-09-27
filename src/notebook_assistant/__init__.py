"""Notebook assistant: keeps an Obsidian vault organized under one handbook.

Layering (see docs/architecture.md §3):

- ``domain``   pure logic: notes, frontmatter, links, names, rules, changesets. No I/O.
- ``ports``    interfaces the application depends on (e.g. ``VaultStore``).
- ``adapters`` implementations of the ports (filesystem, in-memory).
- ``app``      use cases that combine domain logic with ports (index, rename, apply).
- ``store``    vault-backed state files under ``99-System/Assistant/``.
"""

__version__ = "0.1.0.dev0"
