"""Search over the vault through the per-PC index (docs/architecture.md §4.2, §4.3).

- :func:`documents`: what is searchable: every note and chat session, not the assistant's other
  state (changesets, snapshots, run logs, which Obsidian's search also leaves out);
- :func:`refresh`: brings the index in line with the vault by content hash, so only new or
  changed notes are indexed again; :func:`rebuild` starts from empty;
- :func:`refresh_meaning`: the same for passage vectors, when this PC has embeddings on
  (docs/architecture.md §4.3); only new or changed notes are embedded again;
- :func:`search`: refresh, then the ranked hits; with embeddings, word matches and meaning
  matches merged by reciprocal rank fusion.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain.chunks import chunks
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.embedder import Embedder
from notebook_assistant.ports.search import DocKind, Document, Hit, SearchIndex, VectorIndex
from notebook_assistant.ports.vault import VaultStore

RRF_K = 60  # reciprocal rank fusion's damping constant, the usual value


@dataclass
class Meaning:
    """This PC's embeddings: the model and where its vectors are kept."""

    vectors: VectorIndex
    embedder: Embedder
    busy: threading.Lock = field(default_factory=threading.Lock)  # one refresh at a time


@dataclass(frozen=True)
class Refreshed:
    indexed: int  # documents added or re-indexed
    removed: int
    total: int


def is_session(path: str, rules: Rules) -> bool:
    return path.startswith(rules.review.sessions + "/")


def documents(index: VaultIndex, rules: Rules) -> list[Document]:
    docs: list[Document] = []
    for note in index.notes.values():
        path = note.path.as_posix()
        session = is_session(path, rules)
        if is_state_path(note.path) and not session:
            continue
        aliases = note.frontmatter.get_list("aliases") if note.frontmatter else []
        title = str(note.prop("title") or note.title) if session else note.title
        text = " ".join([title, *(str(a) for a in aliases), note.body])
        kind: DocKind = "session" if session else "note"
        docs.append(Document(path, title, kind, text, content_hash(index.text(note.path) or "")))
    return docs


def refresh(store: VaultStore, search_index: SearchIndex, rules: Rules) -> Refreshed:
    docs = documents(VaultIndex.build(store), rules)
    known = search_index.known()
    changed = [d for d in docs if known.get(d.path) != d.hash]
    gone = set(known) - {d.path for d in docs}
    search_index.upsert(changed)
    search_index.remove(gone)
    return Refreshed(len(changed), len(gone), len(docs))


def rebuild(
    store: VaultStore, search_index: SearchIndex, rules: Rules, meaning: Meaning | None = None
) -> Refreshed:
    search_index.clear()
    if meaning is not None:
        meaning.vectors.clear()
        refresh_meaning(store, meaning, rules, wait=True)
    return refresh(store, search_index, rules)


def refresh_meaning(
    store: VaultStore, meaning: Meaning, rules: Rules, *, wait: bool = False
) -> Refreshed | None:
    """Embed new and changed notes; None when another refresh is running and ``wait`` is off
    (a search then uses the vectors there are rather than waiting for the first full pass)."""
    if not meaning.busy.acquire(blocking=wait):
        return None
    try:
        docs = documents(VaultIndex.build(store), rules)
        name = meaning.embedder.name
        known = meaning.vectors.known(name)
        changed = [d for d in docs if known.get(d.path) != d.hash]
        for doc in changed:
            vectors = meaning.embedder.embed(chunks(doc.title, doc.text), query=False)
            meaning.vectors.upsert(doc.path, doc.hash, name, vectors)
        gone = set(known) - {d.path for d in docs}
        meaning.vectors.remove(gone)
        return Refreshed(len(changed), len(gone), len(docs))
    finally:
        meaning.busy.release()


def fused(ranked: list[list[str]], limit: int) -> list[str]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) to a path's score."""
    scores: dict[str, float] = {}
    for paths in ranked:
        for rank, path in enumerate(paths, start=1):
            scores[path] = scores.get(path, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda p: scores[p], reverse=True)[:limit]


def search(
    store: VaultStore,
    search_index: SearchIndex,
    rules: Rules,
    query: str,
    *,
    limit: int,
    kind: DocKind | None = None,
    every_word: bool = True,
    meaning: Meaning | None = None,
) -> list[Hit]:
    refresh(store, search_index, rules)
    words = search_index.search(query, limit=limit * 2, kind=kind, every_word=every_word)
    if meaning is None:
        return words[:limit]
    refresh_meaning(store, meaning, rules)
    vector = meaning.embedder.embed([query], query=True)[0]
    near = meaning.vectors.nearest(vector, meaning.embedder.name, limit=limit * 2)
    close = [p for p, _ in near if kind is None or (kind == "session") == is_session(p, rules)]
    by_path = {h.path: h for h in words}
    hits = [
        by_path.get(p) or search_index.hit(p)
        for p in fused([[h.path for h in words], close], limit)
    ]
    return [h for h in hits if h is not None]
