from pathlib import PurePosixPath

import pytest
from hypothesis import given
from hypothesis import strategies as st

from notebook_assistant.domain.frontmatter import Frontmatter, FrontmatterError, load_yaml
from notebook_assistant.domain.note import Note, split_frontmatter

SAMPLE = """---
type: knowledge
kind: snippet
scope: personal
status: seed
created: 2026-03-15
updated: 2026-03-15
topic: "[[MOC - Software]]"
aliases: [with_columns, 新增欄位]
# a comment the user wrote
tags: [tool/polars]
---
# Body
"""


def test_values_keep_vault_semantics() -> None:
    data = load_yaml("d: 2026-09-27\nsw: on\nyn: yes\nt: 1:30\nb: true\nn: 3\nf: 0.5\nz: 0755\n")
    assert data == {
        "d": "2026-09-27",
        "sw": "on",
        "yn": "yes",
        "t": "1:30",
        "b": True,
        "n": 3,
        "f": 0.5,
        "z": "0755",
    }


def test_untouched_note_renders_identically() -> None:
    note = Note.parse("n.md", SAMPLE)
    assert note.render() == SAMPLE


def test_set_changes_only_that_entry() -> None:
    note = Note.parse("n.md", SAMPLE)
    assert note.frontmatter is not None
    note.frontmatter.set("status", "evergreen")
    out = note.render()
    assert out == SAMPLE.replace("status: seed", "status: evergreen")


def test_new_key_goes_to_canonical_position() -> None:
    note = Note.parse("n.md", SAMPLE)
    assert note.frontmatter is not None
    note.frontmatter.set("id", "n-1")
    note.frontmatter.set("origin", "ai-chat")
    lines = note.render().split("\n")
    assert lines[1] == "id: n-1"
    assert lines.index("origin: ai-chat") == lines.index("tags: [tool/polars]") + 1


def test_delete_and_list_values() -> None:
    fm = Frontmatter.parse("aliases: [a, b]\ntags: [x]")
    assert fm.get_list("aliases") == ["a", "b"]
    fm.delete("tags")
    assert "tags" not in fm
    assert fm.render() == "aliases: [a, b]"


def test_quoting_rules() -> None:
    fm = Frontmatter.from_dict(
        {
            "topic": "[[MOC - ML]]",
            "trigger": "on: first day",
            "aliases": ["Confusion matrix", "混淆矩陣", "a, b", "yes"],
            "created": "2026-09-27",
            "sensitive": True,
        }
    )
    text = fm.render()
    assert 'topic: "[[MOC - ML]]"' in text
    assert 'trigger: "on: first day"' in text
    assert 'aliases: [Confusion matrix, 混淆矩陣, "a, b", "yes"]' in text
    assert "created: 2026-09-27" in text
    assert "sensitive: true" in text
    assert load_yaml(text) == fm.to_dict()


@given(
    st.dictionaries(
        st.from_regex(r"[a-z][a-z_]{0,10}", fullmatch=True),
        st.one_of(
            st.text(max_size=30),
            st.booleans(),
            st.integers(-1000, 1000),
            st.lists(st.text(max_size=12), max_size=4),
        ),
        max_size=6,
    )
)
def test_emitted_yaml_round_trips(props: dict[str, object]) -> None:
    props = {k: v for k, v in props.items() if v not in ("", [])}
    fm = Frontmatter.from_dict(props)
    assert (load_yaml(fm.render()) or {}) == props


def test_invalid_frontmatter_raises() -> None:
    with pytest.raises(FrontmatterError):
        Frontmatter.parse("created: {{date}}")
    with pytest.raises(FrontmatterError):
        Frontmatter.parse("- a list")


def test_split_frontmatter_edge_cases() -> None:
    assert split_frontmatter("no fm") == (None, "no fm")
    assert split_frontmatter("---\nunclosed") == (None, "---\nunclosed")
    assert split_frontmatter("---\n---\nbody") == ("", "body")
    assert split_frontmatter("---\na: 1\n---") == ("a: 1", "")
    assert split_frontmatter("---\na: ---x\n---\nb") == ("a: ---x", "b")


def test_crlf_is_preserved() -> None:
    crlf = SAMPLE.replace("\n", "\r\n")
    note = Note.parse(PurePosixPath("n.md"), crlf)
    assert note.newline == "\r\n"
    assert note.render() == crlf
    assert note.frontmatter is not None
    note.frontmatter.set("status", "evergreen")
    assert "status: evergreen\r\n" in note.render()
    assert "\n" not in note.render().replace("\r\n", "")
