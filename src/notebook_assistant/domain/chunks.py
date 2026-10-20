"""Splitting a note into passages for embeddings (docs/architecture.md §4.3), as a pure function:
paragraphs (blank-line separated, a heading starts a new one) packed up to a size the embedding
models read whole, so a match points at a passage, not a whole long note."""

from __future__ import annotations

import re

MAX_CHARS = 1200  # ~300-500 tokens: well inside the 512-token window of the smallest model


def chunks(title: str, text: str) -> list[str]:
    """The note's passages, each starting with its title for context; never empty."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n|\n(?=#)", text) if b.strip()]
    packed: list[str] = []
    current = ""
    for block in blocks:
        while len(block) > MAX_CHARS:  # one huge paragraph: cut it
            if current:
                packed.append(current)
                current = ""
            packed.append(block[:MAX_CHARS])
            block = block[MAX_CHARS:]
        if current and len(current) + len(block) + 2 > MAX_CHARS:
            packed.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current:
        packed.append(current)
    return [f"{title}\n\n{p}" for p in packed] or [title]
