"""Content-preservation check: prove a restructured note lost nothing (Handbook §16.4 rule 1).

The original body is split into atomic units:

- **exact atoms**, which must reappear verbatim, as many times as in the original:
  code blocks, URLs, embeds and links;
- **numbers**, each of which must appear somewhere in the result;
- **text units** (sentences, list items, table cells), each of which must match some text unit
  of the result with a similarity of at least :data:`SIMILARITY` after normalization, so
  reformatting passes but dropped or rewritten content does not.

The result may be several notes (a split), so all resulting bodies are checked together.
This is deterministic code: it never relies on the model saying it kept everything.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

SIMILARITY = 0.9

_FENCED = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_EMBED = re.compile(r"!\[\[[^\]\n]+\]\]|!\[[^\]\n]*\]\([^)\n]+\)")
_WIKILINK = re.compile(r"(?<!!)\[\[([^\]\n|]+)(?:\|[^\]\n]*)?\]\]")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,:]\d+)*(?![\w])")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", re.M)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_SENTENCE_END = re.compile(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z0-9一-鿿])")
_MARKUP = re.compile(r"[*_~=>`|]+|\[\[|\]\]|^\s*[-*+]\s+", re.M)


@dataclass
class PreservationReport:
    missing_exact: list[str] = field(default_factory=list)
    missing_numbers: list[str] = field(default_factory=list)
    missing_text: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing_exact or self.missing_numbers or self.missing_text)

    def summary(self) -> str:
        if self.ok:
            return "nothing lost"
        parts = []
        if self.missing_exact:
            parts.append(f"{len(self.missing_exact)} code block/URL/link(s) missing")
        if self.missing_numbers:
            parts.append(f"{len(self.missing_numbers)} number(s) missing")
        if self.missing_text:
            parts.append(f"{len(self.missing_text)} sentence(s) missing or changed")
        return "; ".join(parts)


def _exact_atoms(text: str) -> tuple[Counter[str], str]:
    """Pull out exact atoms; return them and the text with code removed."""
    atoms: Counter[str] = Counter()
    for m in _FENCED.finditer(text):
        atoms["code:" + m.group(0).strip()] += 1
    no_blocks = _FENCED.sub(" ", text)
    for m in _INLINE_CODE.finditer(no_blocks):
        atoms["code:" + m.group(0)] += 1
    no_code = _INLINE_CODE.sub(" ", no_blocks)
    for m in _URL.finditer(no_code):
        atoms["url:" + m.group(0).rstrip(".,;")] += 1
    for m in _EMBED.finditer(no_code):
        atoms["embed:" + m.group(0)] += 1
    for m in _WIKILINK.finditer(no_code):
        atoms["link:" + m.group(1).strip()] += 1
    return atoms, no_code


def _numbers(text_without_code: str) -> set[str]:
    stripped = _LIST_MARKER.sub("", _URL.sub(" ", text_without_code))
    return set(_NUMBER.findall(stripped))


def normalize(text: str) -> str:
    """Lowercase, drop Markdown markup, collapse whitespace."""
    text = _MARKUP.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def text_units(text_without_code: str) -> list[str]:
    """Sentences, list items and table cells, normalized, ignoring trivial fragments."""
    text = _HEADING.sub("", _URL.sub(" ", text_without_code))
    units: list[str] = []
    for line in text.split("\n"):
        line = _LIST_MARKER.sub("", line)
        if re.fullmatch(r"\s*\|?[\s:|-]*\|?\s*", line):  # table separator / blank
            continue
        cells = [c for c in line.split("|")] if line.count("|") >= 2 else [line]
        for cell in cells:
            for piece in _SENTENCE_END.split(cell):
                norm = normalize(piece)
                if len(re.sub(r"\W", "", norm)) >= 2:
                    units.append(norm)
    return units


def check(
    original: str, results: list[str], *, similarity: float = SIMILARITY
) -> PreservationReport:
    """Compare an original body with the resulting bodies (one per resulting note)."""
    report = PreservationReport()
    orig_atoms, orig_text = _exact_atoms(original)
    res_atoms: Counter[str] = Counter()
    res_texts: list[str] = []
    for body in results:
        atoms, text = _exact_atoms(body)
        res_atoms.update(atoms)
        res_texts.append(text)
    for atom, count in orig_atoms.items():
        if res_atoms[atom] < count:
            report.missing_exact.append(atom)

    res_all = "\n".join(res_texts)
    res_numbers = _numbers(res_all) | set(_NUMBER.findall(res_all))
    report.missing_numbers = sorted(_numbers(orig_text) - res_numbers)

    res_units = text_units(res_all)
    res_joined = " ".join(res_units)
    for unit in text_units(orig_text):
        if unit in res_joined:
            continue
        if not any(_similar(unit, cand, similarity) for cand in res_units):
            report.missing_text.append(unit)
    return report


def _similar(a: str, b: str, threshold: float) -> bool:
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
        return False
    return matcher.ratio() >= threshold
