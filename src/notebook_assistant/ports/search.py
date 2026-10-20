"""The search index port: the per-PC full-text index (docs/architecture.md §4.2, §4.3).

It's a cache, rebuilt from the vault at any time: callers tell it which documents exist (with
a content hash) and ask it for ranked hits. Adapter: SQLite FTS5 with jieba-split Chinese.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

DocKind = Literal["note", "session"]


@dataclass(frozen=True)
class Document:
    path: str
    title: str
    kind: DocKind
    text: str  # what is searched: title, aliases and body
    hash: str  # the note's content hash, so unchanged notes aren't indexed again


@dataclass(frozen=True)
class Hit:
    path: str
    title: str
    kind: DocKind
    snippet: str  # the text around the first match, with matches in **bold**
    score: float  # higher is better


class SearchIndex(Protocol):
    def known(self) -> dict[str, str]:
        """Every indexed path and the hash it was indexed at."""
        ...

    def upsert(self, docs: Iterable[Document]) -> None: ...

    def remove(self, paths: Iterable[str]) -> None: ...

    def clear(self) -> None: ...

    def hit(self, path: str) -> Hit | None:
        """One indexed document as a hit, its snippet the start of its text (for a match found
        by meaning, where no word matched)."""
        ...

    def search(
        self, query: str, *, limit: int, kind: DocKind | None = None, every_word: bool = True
    ) -> list[Hit]:
        """Ranked hits. With ``every_word`` each query word must appear (a search box); without
        it any may (a question asked in a sentence), and more matching words rank higher."""
        ...


class VectorIndex(Protocol):
    """The optional meaning index next to the full-text one: each note's passages as vectors."""

    def known(self, model: str) -> dict[str, str]:
        """Every path with vectors from ``model``, and the hash they were made from."""
        ...

    def upsert(self, path: str, doc_hash: str, model: str, vectors: list[list[float]]) -> None: ...

    def remove(self, paths: Iterable[str]) -> None: ...

    def clear(self) -> None: ...

    def nearest(self, vector: list[float], model: str, *, limit: int) -> list[tuple[str, float]]:
        """The notes whose best passage is closest to ``vector`` (cosine), best first."""
        ...
