"""The embedder port: text in, one vector per text out (docs/architecture.md §4.3). Adapters: an
ONNX model on the CPU, and a deterministic fake for tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbedderError(Exception):
    """The model can't be loaded or run (not installed, not downloaded, broken)."""


class Embedder(Protocol):
    @property
    def name(self) -> str:
        """Which model, so vectors from another model are never compared with these."""
        ...

    def embed(self, texts: Sequence[str], *, query: bool) -> list[list[float]]:
        """Unit-length vectors; ``query`` marks a search query rather than a passage (models
        like e5 embed the two differently)."""
        ...
