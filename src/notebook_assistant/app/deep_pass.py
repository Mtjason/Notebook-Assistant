"""The Deep pass button (Handbook §16.6, §16.3 last row), the parts code can find on its own:

- :func:`duplicate_candidates`: pairs of notes that may say the same thing (§8.2 merge
  candidates): one's title is the other's alias, or the titles are nearly the same
  (``checks.duplicate_similarity`` in ``Config.md``);
- :func:`missing_links`: a note that names another note's title in its text without linking it.

Both are reported for you to decide; merging and linking go through the Review screen or Chat.
Contradictions between notes and image descriptions need the model and come with Chat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain.invariants import is_checked
from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules

MIN_TITLE_WORDS = 2  # a one-word title ("Docker") is too common a word to call a missing link
STRUCTURAL = ("moc", "daily", "system", "source")  # Handbook §3: notes that index others


@dataclass(frozen=True)
class Duplicate:
    a: str  # vault paths
    b: str
    why: str


@dataclass(frozen=True)
class MissingLink:
    path: str  # the note that names it
    target: str  # the title it names
    excerpt: str


def _content_notes(index: VaultIndex, rules: Rules) -> list[Note]:
    top = rules.archive_root
    return [
        n
        for n in sorted(index.notes.values(), key=lambda n: n.path.as_posix())
        if n.type
        and n.type not in STRUCTURAL
        and is_checked(n.path, rules)
        and not is_state_path(n.path)
        and n.path.parts[0] != top
    ]


def _aliases(note: Note) -> set[str]:
    values = note.frontmatter.get_list("aliases") if note.frontmatter else []
    return {name_key(str(a)) for a in values}


def titles_alike(a: str, b: str, similarity: float) -> bool:
    """Whether two titles differ only by a near-identical word or two. Only the words that
    differ are compared, so titles sharing a naming pattern (`SOP - Install X (Linux)`) don't
    look alike because of the pattern."""
    wa, wb = set(re.findall(r"\w+", a)), set(re.findall(r"\w+", b))
    only_a, only_b = " ".join(sorted(wa - wb)), " ".join(sorted(wb - wa))
    if not only_a and not only_b:
        return True
    return SequenceMatcher(None, only_a, only_b).ratio() >= similarity


_NOT_PROSE = re.compile(r"```.*?```|`[^`\n]*`|!?\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)", re.S)


def prose(body: str) -> str:
    """The note's own words: no code, and no text inside links (it already links)."""
    return _NOT_PROSE.sub(" ", body)


def duplicate_candidates(index: VaultIndex, rules: Rules, similarity: float) -> list[Duplicate]:
    notes = _content_notes(index, rules)
    found: list[Duplicate] = []
    for a, b in combinations(notes, 2):
        if a.type != b.type:
            continue
        ka, kb = name_key(a.title), name_key(b.title)
        if ka in _aliases(b) or kb in _aliases(a):
            why = "one's title is the other's alias"
        elif titles_alike(ka, kb, similarity):
            why = "nearly the same title"
        else:
            continue
        found.append(Duplicate(a.path.as_posix(), b.path.as_posix(), why))
    return found


def missing_links(index: VaultIndex, rules: Rules) -> list[MissingLink]:
    notes = _content_notes(index, rules)
    titles = [n for n in notes if len(n.title.split()) >= MIN_TITLE_WORDS]
    found: list[MissingLink] = []
    for note in notes:
        linked = {name_key(link.target.split("/")[-1]) for link in find_links(note.render())}
        for other in titles:
            if other.path == note.path or name_key(other.title) in linked:
                continue
            text = prose(note.body)
            m = re.search(rf"(?<!\w){re.escape(other.title)}(?!\w)", text, re.I)
            if m:
                start = max(0, m.start() - 30)
                excerpt = " ".join(text[start : m.end() + 30].split())
                found.append(MissingLink(note.path.as_posix(), other.title, excerpt))
    return found
