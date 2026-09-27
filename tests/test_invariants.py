from collections import Counter
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.invariants import VaultFacts, check_note, is_checked
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note

BASE = {
    "type": "knowledge",
    "kind": "concept",
    "scope": "personal",
    "status": "seed",
    "created": "2026-09-27",
    "updated": "2026-09-27",
    "topic": '"[[MOC - ML]]"',
}


def make(path: str, drop: tuple[str, ...] = (), body: str = "text\n", **props: str) -> Note:
    merged = {k: v for k, v in {**BASE, **props}.items() if k not in drop}
    fm = "\n".join(f"{k}: {v}" for k, v in merged.items())
    return Note.parse(PurePosixPath(path), f"---\n{fm}\n---\n{body}")


def codes(note: Note, facts: VaultFacts | None = None) -> list[str]:
    facts = facts or VaultFacts(title_counts=Counter({name_key(note.title): 1}))
    return [v.code for v in check_note(note, facts)]


def test_fixture_vault_is_compliant(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    facts = index.facts()
    problems = {n.path: check_note(n, facts) for n in index.notes.values()}
    assert {p: v for p, v in problems.items() if v} == {}
    assert index.broken == []


def test_valid_knowledge_note() -> None:
    assert codes(make("60-Knowledge/ML/Confusion matrix.md")) == []


def test_i1_type() -> None:
    assert codes(Note.parse(PurePosixPath("10-Tasks/x.md"), "no frontmatter")) == ["I-1"]
    assert "I-1" in codes(make("60-Knowledge/ML/x.md", type="banana"))


def test_i2_folder() -> None:
    assert "I-2" in codes(make("10-Tasks/Confusion matrix.md"))
    assert "I-2" in codes(make("60-Knowledge/Unknown topic/x.md"))
    assert "I-2" in codes(make("root note.md"))


def test_i2_containers() -> None:
    hub = make("20-Projects/Demo/Demo.md", type="project", status="active", started="2026-01-01")
    assert codes(hub) == []
    wrong_hub = make(
        "20-Projects/Demo/Other.md", type="project", status="active", started="2026-01-01"
    )
    assert "I-2" in codes(wrong_hub)
    doc = make(
        "20-Projects/Demo/Design.md",
        drop=("kind",),
        type="project-doc",
        status="draft",
        project='"[[Demo]]"',
    )
    assert codes(doc) == []
    assert "I-2" in codes(make("20-Projects/Demo/Stray knowledge.md"))


def test_code_tree_files_are_exempt() -> None:
    readme = Note.parse(PurePosixPath("20-Projects/Demo/README.md"), "# Demo\n")
    assert codes(readme) == []
    deep = make("20-Projects/Demo/src/pkg/sub/notes.md", type="banana")
    assert codes(deep) == []


def test_i3_required_and_enums() -> None:
    assert "I-3" in codes(make("60-Knowledge/ML/x.md", drop=("scope",)))
    assert "I-3" in codes(make("60-Knowledge/ML/x.md", status="done"))
    assert "I-3" in codes(make("60-Knowledge/ML/x.md", kind="essay"))
    task = make("10-Tasks/Do it.md", type="task", kind="action", status="todo", priority="p9")
    assert codes(task) == ["I-3"]
    doc = make("20-Projects/Demo/Design.md", drop=("kind",), type="project-doc", status="draft")
    assert "I-3" in codes(doc)  # needs project, area or idea


def test_value_dates() -> None:
    assert "value" in codes(make("60-Knowledge/ML/x.md", updated="yesterday"))


def test_i4_unique_and_pattern() -> None:
    note = make("60-Knowledge/ML/x.md")
    facts = VaultFacts(title_counts=Counter({name_key("X"): 2}))
    assert "I-4" in codes(note, facts)
    sop = make(
        "30-SOPs/Install uv.md",
        drop=("kind",),
        type="sop",
        status="active",
        domain="dev-env",
        trigger="x",
        last_verified="2026-09-01",
    )
    assert "I-4" in codes(sop)


def test_i5_link_required_except_exempt_folders() -> None:
    no_link = make("60-Knowledge/ML/x.md", drop=("topic",), kind="concept")
    assert "I-5" in codes(no_link)
    daily = Note.parse(
        PurePosixPath("01-Daily/2026-09-27.md"),
        "---\ntype: daily\nscope: personal\nstatus: active\ncreated: 2026-09-27\n"
        "updated: 2026-09-27\ndate: 2026-09-27\n---\nno links\n",
    )
    assert codes(daily) == []


def test_i6_depth() -> None:
    assert "I-6" in codes(make("60-Knowledge/ML/a/b/x.md"))


def test_archive() -> None:
    assert codes(make("95-Archive/60-Knowledge/x.md", status="archived")) == []
    assert "value" in codes(make("95-Archive/60-Knowledge/x.md"))


def test_tags() -> None:
    facts = VaultFacts(
        title_counts=Counter({name_key("x"): 1}), registered_tags=frozenset({"ml/xai"})
    )
    assert codes(make("60-Knowledge/ML/x.md", tags="[ml/xai]"), facts) == []
    assert codes(make("60-Knowledge/ML/x.md", tags="[kedro]"), facts) == ["tag"]
    assert "tag" in codes(make("60-Knowledge/ML/x.md", tags="[a, b, c, d]"))


@pytest.mark.parametrize(
    ("path", "checked"),
    [
        ("00-Inbox/raw.md", False),
        ("98-Templates/Task.md", False),
        ("99-System/Assistant/Changesets/2026-09/cs.md", False),
        ("99-System/Tags.md", True),
        ("60-Knowledge/ML/x.md", True),
        ("Attachments/a.png", False),
    ],
)
def test_checked_locations(path: str, checked: bool) -> None:
    assert is_checked(PurePosixPath(path)) is checked
