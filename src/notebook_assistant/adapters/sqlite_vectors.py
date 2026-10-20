"""Passage vectors in SQLite beside the full-text index (docs/architecture.md §4.2). A few
thousand passages are compared by brute force in well under a second, so no vector extension is
needed; vectors are stored as float32 blobs."""

from __future__ import annotations

import sqlite3
import threading
from array import array
from collections.abc import Iterable
from pathlib import Path


def _blob(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def _vector(blob: bytes) -> array[float]:
    values = array("f")
    values.frombytes(blob)
    return values


class SqliteVectors:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS vectors (path TEXT, n INTEGER, hash TEXT, model TEXT,
                                                vec BLOB, PRIMARY KEY (path, n));
            """
        )

    def known(self, model: str) -> dict[str, str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT path, hash FROM vectors WHERE model = ? AND n = 0", (model,)
            ).fetchall()
        return dict(rows)

    def upsert(self, path: str, doc_hash: str, model: str, vectors: list[list[float]]) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM vectors WHERE path = ?", (path,))
            self._db.executemany(
                "INSERT INTO vectors VALUES (?, ?, ?, ?, ?)",
                [(path, n, doc_hash, model, _blob(v)) for n, v in enumerate(vectors)],
            )

    def remove(self, paths: Iterable[str]) -> None:
        with self._lock, self._db:
            self._db.executemany("DELETE FROM vectors WHERE path = ?", [(p,) for p in paths])

    def clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM vectors")

    def nearest(self, vector: list[float], model: str, *, limit: int) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT path, vec FROM vectors WHERE model = ?", (model,)
            ).fetchall()
        best: dict[str, float] = {}
        for path, blob in rows:
            score = sum(a * b for a, b in zip(vector, _vector(blob), strict=True))
            if score > best.get(path, -2.0):
                best[path] = score
        return sorted(best.items(), key=lambda item: item[1], reverse=True)[:limit]
