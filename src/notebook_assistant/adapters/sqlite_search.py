"""The search index as SQLite FTS5 (docs/architecture.md §4.2): BM25 ranking over text that
jieba has split into words, so Chinese is searchable by word as English is. The original text
is kept beside the tokens, for snippets."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import warnings
from collections.abc import Iterable
from pathlib import Path

from notebook_assistant.ports.search import DocKind, Document, Hit

with warnings.catch_warnings():  # jieba 0.42 predates Python 3.12's escape-sequence warnings
    warnings.simplefilter("ignore", SyntaxWarning)
    import jieba

jieba.setLogLevel(logging.WARNING)

SNIPPET = 160  # characters of context around the first match
_WORD = re.compile(r"[^\W_]", re.UNICODE)  # a letter or digit; "_" alone is not a word


def tokens(text: str) -> list[str]:
    """Words for the index: jieba's search-mode split, lower-cased, punctuation dropped."""
    return [str(t).lower() for t in jieba.cut_for_search(text) if _WORD.search(str(t))]


def _match_query(query: str) -> str | None:
    words = dict.fromkeys(tokens(query))
    return " AND ".join('"' + w.replace('"', '""') + '"' for w in words) or None


def snippet(text: str, query: str) -> str:
    """The text around the first query word found, with every query word in **bold**."""
    words = sorted({w for w in tokens(query)}, key=len, reverse=True)
    flat = " ".join(text.split())
    lowered = flat.lower()
    first = min((i for w in words if (i := lowered.find(w)) >= 0), default=0)
    start = max(0, first - SNIPPET // 3)
    piece = flat[start : start + SNIPPET]
    for w in words:
        piece = re.sub(re.escape(w), lambda m: f"**{m.group(0)}**", piece, flags=re.I)
    return ("…" if start else "") + piece + ("…" if start + SNIPPET < len(flat) else "")


class SqliteSearch:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        # one connection shared by the service's worker threads, used one at a time
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (path TEXT PRIMARY KEY, title TEXT, kind TEXT,
                                             text TEXT, hash TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(path UNINDEXED, words,
                                                              tokenize='unicode61');
            """
        )

    def known(self) -> dict[str, str]:
        with self._lock:
            return dict(self._db.execute("SELECT path, hash FROM docs").fetchall())

    def upsert(self, docs: Iterable[Document]) -> None:
        with self._lock, self._db:
            for d in docs:
                self._db.execute("DELETE FROM fts WHERE path = ?", (d.path,))
                self._db.execute(
                    "INSERT OR REPLACE INTO docs VALUES (?, ?, ?, ?, ?)",
                    (d.path, d.title, d.kind, d.text, d.hash),
                )
                self._db.execute(
                    "INSERT INTO fts (path, words) VALUES (?, ?)",
                    (d.path, " ".join(tokens(d.text))),
                )

    def remove(self, paths: Iterable[str]) -> None:
        with self._lock, self._db:
            for p in paths:
                self._db.execute("DELETE FROM docs WHERE path = ?", (p,))
                self._db.execute("DELETE FROM fts WHERE path = ?", (p,))

    def clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM docs")
            self._db.execute("DELETE FROM fts")

    def search(self, query: str, *, limit: int, kind: DocKind | None = None) -> list[Hit]:
        match = _match_query(query)
        if match is None:
            return []
        with self._lock:
            rows = self._query(match, kind, limit)
        return [Hit(p, t, k, snippet(text, query), -rank) for p, t, k, text, rank in rows]

    def _query(
        self, match: str, kind: DocKind | None, limit: int
    ) -> list[tuple[str, str, DocKind, str, float]]:
        rows: list[tuple[str, str, DocKind, str, float]] = self._db.execute(
            """SELECT d.path, d.title, d.kind, d.text, bm25(fts) AS rank
               FROM fts JOIN docs d ON d.path = fts.path
               WHERE fts MATCH ? AND (? IS NULL OR d.kind = ?)
               ORDER BY rank LIMIT ?""",
            (match, kind, kind, limit),
        ).fetchall()
        return rows
