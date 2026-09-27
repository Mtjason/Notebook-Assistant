"""An in-memory index of the vault: files, parsed notes, and the link graph.

Built from the storage port in one pass (a few hundred files take well under a second).
The per-PC persistent cache (SQLite, search) comes in a later branch; this index is the
authoritative, always-rebuildable view the planners and the apply step rely on.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from notebook_assistant.app import canvas
from notebook_assistant.domain.frontmatter import FrontmatterError
from notebook_assistant.domain.invariants import VaultFacts
from notebook_assistant.domain.links import Link, Resolver, find_links
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note, is_canvas_path, is_note_path
from notebook_assistant.handbook import load_rules
from notebook_assistant.ports.vault import VaultStore


@dataclass(frozen=True)
class Ref:
    """One reference from ``source`` to ``target``."""

    source: PurePosixPath
    target: PurePosixPath
    link: Link | None  # None for canvas file nodes


def is_state_path(path: PurePosixPath) -> bool:
    """The assistant's own state files (Handbook §0.1, Scope): not part of the link graph and
    never rewritten by renames."""
    return path.as_posix().startswith(load_rules().state_prefix)


@dataclass
class VaultIndex:
    files: list[PurePosixPath]
    texts: dict[str, str]  # name_key(path) -> text, for notes and canvases
    notes: dict[str, Note]  # name_key(path) -> parsed note
    unparseable: dict[str, str] = field(default_factory=dict)  # path -> error
    resolver: Resolver = field(init=False)
    refs_by_target: dict[str, list[Ref]] = field(init=False)
    refs_by_source: dict[str, list[Ref]] = field(init=False)
    broken: list[tuple[PurePosixPath, Link]] = field(init=False)
    _by_key: dict[str, PurePosixPath] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_key = {name_key(p.as_posix()): p for p in self.files}
        self.resolver = Resolver(self.files)
        self.refs_by_target = defaultdict(list)
        self.refs_by_source = defaultdict(list)
        self.broken = []
        for path in self.files:
            key = name_key(path.as_posix())
            if key not in self.texts or is_state_path(path):
                continue
            for ref, link in self._outgoing(path, self.texts[key]):
                if ref is None:
                    if link is not None:
                        self.broken.append((path, link))
                    continue
                self.refs_by_target[name_key(ref.target.as_posix())].append(ref)
                self.refs_by_source[key].append(ref)

    @classmethod
    def build(cls, store: VaultStore) -> VaultIndex:
        files = list(store.iter_files())
        texts: dict[str, str] = {}
        notes: dict[str, Note] = {}
        bad: dict[str, str] = {}
        for path in files:
            if not (is_note_path(path) or is_canvas_path(path)):
                continue
            key = name_key(path.as_posix())
            try:
                text = store.read_text(path)
            except UnicodeDecodeError:
                bad[path.as_posix()] = "not valid UTF-8"
                continue
            texts[key] = text
            if is_note_path(path):
                try:
                    notes[key] = Note.parse(path, text)
                except FrontmatterError as exc:
                    bad[path.as_posix()] = str(exc)
        return cls(files=files, texts=texts, notes=notes, unparseable=bad)

    def _outgoing(self, source: PurePosixPath, text: str) -> list[tuple[Ref | None, Link | None]]:
        out: list[tuple[Ref | None, Link | None]] = []
        if is_canvas_path(source):
            try:
                data = canvas.load(text)
            except ValueError:
                return out
            for file_path in canvas.file_refs(data):
                hit = self.path_of(file_path)
                out.append((Ref(source, hit, None) if hit else None, None))
            for node_text in canvas.text_nodes(data):
                out.extend(self._links_in(source, node_text))
            return out
        return self._links_in(source, text)

    def _links_in(self, source: PurePosixPath, text: str) -> list[tuple[Ref | None, Link | None]]:
        out: list[tuple[Ref | None, Link | None]] = []
        for link in find_links(text):
            target = self.resolver.resolve(link, source)
            out.append((Ref(source, target, link) if target else None, link))
        return out

    # ----- queries

    def path_of(self, path: PurePosixPath) -> PurePosixPath | None:
        """The stored spelling of ``path`` if it exists (case-insensitive)."""
        return self._by_key.get(name_key(path.as_posix()))

    def note(self, path: PurePosixPath) -> Note | None:
        return self.notes.get(name_key(path.as_posix()))

    def text(self, path: PurePosixPath) -> str | None:
        return self.texts.get(name_key(path.as_posix()))

    def backlinks(self, target: PurePosixPath) -> list[Ref]:
        return list(self.refs_by_target.get(name_key(target.as_posix()), []))

    def title_counts(self) -> Counter[str]:
        return Counter(
            name_key(n.title) for k, n in self.notes.items() if not is_state_path(n.path)
        )

    def facts(self) -> VaultFacts:
        return VaultFacts(
            rules=load_rules(),
            title_counts=self.title_counts(),
            registered_tags=self.tag_registry(),
        )

    def tag_registry(self) -> frozenset[str] | None:
        """Tags listed in ``99-System/Tags.md`` as `` `#tag` `` items (Handbook §6)."""
        text = self.text(PurePosixPath(load_rules().tag_registry))
        if text is None:
            return None
        return frozenset(re.findall(r"`#([^`\s]+)`", text))
