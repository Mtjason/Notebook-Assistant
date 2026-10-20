"""Search over the vault through the per-PC index (docs/architecture.md §4.2, §4.3).

- :func:`documents`: what is searchable: every note and chat session, not the assistant's other
  state (changesets, snapshots, run logs, which Obsidian's search also leaves out);
- :func:`refresh`: brings the index in line with the vault by content hash, so only new or
  changed notes are indexed again; :func:`rebuild` starts from empty;
- :func:`search`: refresh, then the ranked hits.
"""

from __future__ import annotations

from dataclasses import dataclass

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.search import DocKind, Document, Hit, SearchIndex
from notebook_assistant.ports.vault import VaultStore


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


def rebuild(store: VaultStore, search_index: SearchIndex, rules: Rules) -> Refreshed:
    search_index.clear()
    return refresh(store, search_index, rules)


def search(
    store: VaultStore,
    search_index: SearchIndex,
    rules: Rules,
    query: str,
    *,
    limit: int,
    kind: DocKind | None = None,
) -> list[Hit]:
    refresh(store, search_index, rules)
    return search_index.search(query, limit=limit, kind=kind)
