"""The design documents agree with the handbook and with each other.

Every doc refers to other facts by section instead of restating them (``CLAUDE.md``), so the
checks here are mechanical:

- every ``§`` reference points to a section that exists in the document it names;
- the examples on ``docs/design.html`` (paths, ``type``, ``kind``, ``status``, ``digest``, topic
  MOCs) use values the current handbook allows;
- environment variables the project defines use the ``NA_`` prefix.

Judgment calls (is this the right topic for that note?) stay with review; this catches drift.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

from notebook_assistant.handbook import load_rules

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
HANDBOOK = DOCS / "handbook.md"
ARCHITECTURE = DOCS / "architecture.md"
DESIGN = DOCS / "design.html"

# Which document a bare "§x" means in each file, and the words that name another document.
DEFAULT_TARGET = {
    "docs/handbook.md": HANDBOOK,
    "docs/architecture.md": ARCHITECTURE,
    "docs/maintenance-job.md": HANDBOOK,
    "docs/design.html": HANDBOOK,
    "CLAUDE.md": HANDBOOK,
    "README.md": HANDBOOK,
}
NAMED_TARGET = [(re.compile(r"architecture(\.md)?\W*$", re.I), ARCHITECTURE)]
NAMED_HANDBOOK = re.compile(r"(handbook(\.md)?|Handbook)\W*$")
# Text allowed between two references that share a document: "§8.4 and §16.6", "§3, §8",
# "§5.4 (release) and §5.4.1".
CONNECTOR = re.compile(r"^[\s,;]*(\([^()]{0,40}\))?[\s,;)]*(and|or|to)?[\s,;(]*$")
REF = re.compile(r"§(\d+(?:\.\d+)*)")
HEADING = re.compile(r"^#{2,4} (\d+(?:\.\d+)*)\.?\s", re.M)
EXTERNAL_ENV = {"ANTHROPIC_API_KEY", "PYTHONUTF8"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _visible_text(page: str) -> str:
    """The page's text as a reader sees it, including strings inside its demo script."""
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _sections(doc: Path) -> set[str]:
    """Section numbers a reference may name: headings, and numbered list items under a
    heading (Handbook §15 rule 3 is cited as §15.3)."""
    text = _read(doc)
    found = set(HEADING.findall(text))
    for head in HEADING.finditer(text):
        nxt = HEADING.search(text, head.end())
        body = text[head.end() : nxt.start() if nxt else len(text)]
        found |= {f"{head.group(1)}.{n}" for n in re.findall(r"^(\d+)\. ", body, re.M)}
    return found


def _references(rel: str) -> list[tuple[str, Path, str]]:
    """(section, document it points to, context) for every § reference in ``rel``."""
    text = _read(REPO / rel)
    out: list[tuple[str, Path, str]] = []
    prev_end, prev_doc = -1, DEFAULT_TARGET[rel]
    for m in REF.finditer(text):
        before = re.sub(r"<[^>]+>", "", text[max(0, m.start() - 60) : m.start()])
        if prev_end >= 0 and CONNECTOR.match(text[prev_end : m.start()]):
            doc = prev_doc
        elif NAMED_HANDBOOK.search(before):
            doc = HANDBOOK
        else:
            doc = next((d for p, d in NAMED_TARGET if p.search(before)), DEFAULT_TARGET[rel])
        out.append((m.group(1), doc, text[max(0, m.start() - 30) : m.end()].replace("\n", " ")))
        prev_end, prev_doc = m.end(), doc
    return out


@pytest.mark.parametrize("rel", sorted(DEFAULT_TARGET))
def test_section_references_resolve(rel: str) -> None:
    known = {doc: _sections(doc) for doc in (HANDBOOK, ARCHITECTURE)}
    broken = [
        f"{doc.name} §{num}  ←  …{context}"
        for num, doc, context in _references(rel)
        if num not in known[doc]
    ]
    assert not broken, "\n".join(broken)


def test_design_examples_follow_the_handbook() -> None:
    """Values shown on the design page are ones the handbook allows (it is read as the spec)."""
    rules = load_rules()
    text = _visible_text(_read(DESIGN))
    kinds = {k for t in rules.types.values() for k in t.enums.get("kind", ())}
    problems: list[str] = []

    for topic in re.findall(r"60-Knowledge/([^/\n]+)/", text):
        if topic not in rules.topics:
            problems.append(f"60-Knowledge/{topic}/ is not a §2.3 topic")
    for topic in re.findall(r"\[\[MOC - ([^\]]+)\]\]", text):
        if topic not in rules.topics:
            problems.append(f"MOC - {topic} is not a §2.3 topic")

    # property strings are shown as "key: value · key: value"
    for line in re.findall(r"^.*\btype: [\w-]+.*$", text, re.M):
        pairs = re.findall(r"\b([a-z_]+): ([\w\[\]\- ]+?)(?= ·|$|\")", line)
        props = {key: value.strip() for key, value in pairs}
        rule = rules.types.get(props["type"])
        if rule is None:
            problems.append(f"type: {props['type']} is not a §4.2 type")
            continue
        if "kind" in props and props["kind"] not in rule.enums.get("kind", kinds):
            problems.append(f"kind: {props['kind']} is not allowed for {rule.name}")
        if "status" in props and props["status"] not in rule.statuses:
            problems.append(f"status: {props['status']} is not allowed for {rule.name}")
        digest = rules.common_enums.get("digest", frozenset())
        if "digest" in props and props["digest"] not in digest:
            problems.append(f"digest: {props['digest']} is not a §4.1 value")

    # a note shown at a path in a topic folder cites that topic's MOC
    for folder, moc in re.findall(
        r"60-Knowledge/([^/\n]+)/[^\n]*?[\s\S]{0,400}?\[\[MOC - ([^\]]+)\]\]", text
    ):
        if folder != moc:
            problems.append(f"a note in 60-Knowledge/{folder}/ cites MOC - {moc}")

    assert not problems, "\n".join(problems)


def test_environment_variables_use_the_project_prefix() -> None:
    names = set()
    for path in [*DOCS.glob("*"), REPO / "README.md", REPO / "CLAUDE.md"]:
        names |= set(re.findall(r"`([A-Z][A-Z0-9]*_[A-Z0-9_]+)=?`", _read(path)))
    for path in (REPO / "src").rglob("*.py"):
        names |= set(re.findall(r"environ(?:\.get)?\(\s*\"([A-Z0-9_]+)\"", _read(path)))
    foreign = sorted(n for n in names - EXTERNAL_ENV if not n.startswith("NA_"))
    assert not foreign, ", ".join(foreign)
