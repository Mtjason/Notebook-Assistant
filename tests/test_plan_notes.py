"""Planned notes become real notes: creates get full frontmatter, patches only add."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from notebook_assistant.domain.note import Note
from notebook_assistant.domain.plan_notes import (
    add_history,
    add_to_section,
    added_text,
    build_outcomes,
    created_note,
    note_path,
    patched_note,
)
from notebook_assistant.domain.split_plan import NoteOp, PlannedNote, Section, SplitPlan
from tests.conftest import sequential_ids

TODAY = "2026-09-30"


def planned(
    title: str = "New note",
    op: NoteOp = NoteOp.CREATE,
    *,
    folder: str = "60-Knowledge/Systems",
    properties: tuple[tuple[str, str | bool | list[str]], ...] = (),
    body: str = "",
    sections: tuple[Section, ...] = (),
    history: tuple[str, ...] = (),
) -> PlannedNote:
    return PlannedNote(title, op, folder, properties, body, sections, history)


SOP = """---
type: sop
created: 2026-02-01
updated: 2026-02-01
---
## Steps

1. Run the installer.

## Gotchas

## Related
"""


# ----- sections


def test_note_path_joins_folder_and_title() -> None:
    assert note_path(planned()) == PurePosixPath("60-Knowledge/Systems/New note.md")


def test_content_goes_at_the_end_of_its_section() -> None:
    body = "## A\n\ntext\n\n## B\n\nmore\n"
    assert add_to_section(body, "A", "added") == "## A\n\ntext\n\nadded\n\n## B\n\nmore\n"
    assert add_to_section(body, "B", "\nadded\n") == "## A\n\ntext\n\n## B\n\nmore\n\nadded\n"


def test_an_empty_section_gets_the_content_under_its_heading() -> None:
    body = "## Gotchas\n\n## Related\n"
    assert add_to_section(body, "Gotchas", "- tip") == "## Gotchas\n\n- tip\n\n## Related\n"


def test_subsections_stay_inside_their_section() -> None:
    body = "## A\n\n### A.1\n\nx\n\n## B\n"
    assert add_to_section(body, "A", "y") == "## A\n\n### A.1\n\nx\n\ny\n\n## B\n"


def test_rows_extend_a_table_and_items_extend_a_list() -> None:
    table = "## Commands\n\n| Command | Does |\n|---|---|\n| `ls` | list |\n"
    assert add_to_section(table, "Commands", "| `pwd` | where |").endswith(
        "| `ls` | list |\n| `pwd` | where |\n"
    )
    steps = "## Steps\n\n1. one\n"
    assert add_to_section(steps, "Steps", "2. two") == "## Steps\n\n1. one\n2. two\n"


def test_a_missing_section_is_added_before_history_or_at_the_end() -> None:
    with_history = "## Steps\n\nx\n\n## History\n\n- old\n"
    assert add_to_section(with_history, "Gotchas", "g") == (
        "## Steps\n\nx\n\n## Gotchas\n\ng\n\n## History\n\n- old\n"
    )
    assert add_to_section("## Steps\n\nx\n", "Gotchas", "g") == "## Steps\n\nx\n\n## Gotchas\n\ng\n"
    assert add_to_section("", "Gotchas", "g") == "## Gotchas\n\ng\n"


def test_history_lines_are_dated_and_in_order() -> None:
    assert add_history("## A\n", (), TODAY) == "## A\n"
    body = add_history("## A\n\nx\n", ("first", " second "), TODAY)
    assert body.endswith(f"## History\n\n- {TODAY}: first\n- {TODAY}: second\n")
    again = add_history(body, ("third",), "2026-10-01")
    assert again.endswith(f"- {TODAY}: second\n- 2026-10-01: third\n")


# ----- notes


def test_created_note_gets_the_assistant_properties_and_history() -> None:
    note = created_note(
        planned(
            properties=(("type", "knowledge"), ("created", "1999-01-01"), ("id", "n-mine")),
            body="\n## Summary\n\nText.\n\n",
            history=("from a capture",),
        ),
        today=TODAY,
        note_id="n-1",
    )
    assert note.path == PurePosixPath("60-Knowledge/Systems/New note.md")
    assert note.props == {"id": "n-1", "type": "knowledge", "created": TODAY, "updated": TODAY}
    assert note.body == f"## Summary\n\nText.\n\n## History\n\n- {TODAY}: from a capture\n"
    assert note.render().startswith("---\nid: n-1\ntype: knowledge\n")


def test_a_patch_only_adds_and_keeps_untouched_lines_byte_identical() -> None:
    existing = Note.parse("30-SOPs/SOP - X.md", SOP.replace("\n", "\r\n"))
    note = patched_note(
        existing,
        planned(
            "SOP - X",
            NoteOp.PATCH,
            folder="",
            properties=(("platform", ["linux"]), ("updated", "1999-01-01")),
            sections=(Section("Steps", "2. Reload."), Section("Gotchas", "- Watch out.")),
            history=("added a step",),
        ),
        today=TODAY,
        note_id="n-1",
    )
    text = note.render()
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")  # line endings kept
    lines = text.split("\r\n")
    assert lines[:3] == ["---", "id: n-1", "type: sop"]
    assert "created: 2026-02-01" in lines and f"updated: {TODAY}" in lines
    assert "platform: [linux]" in lines
    assert "1. Run the installer.\r\n2. Reload." in text
    assert "## Gotchas\r\n\r\n- Watch out.\r\n\r\n## Related" in text
    assert text.endswith(f"## History\r\n\r\n- {TODAY}: added a step\r\n")
    assert existing.render() == SOP.replace("\n", "\r\n")  # the original is untouched


def test_a_patch_keeps_an_existing_id() -> None:
    existing = Note.parse("a.md", SOP.replace("type: sop", "id: n-old\ntype: sop"))
    note = patched_note(existing, planned("a", NoteOp.PATCH), today=TODAY, note_id="n-new")
    assert note.prop("id") == "n-old"


def test_added_text_is_the_new_lines_of_a_patch_or_all_of_a_new_note() -> None:
    before = Note.parse("a.md", SOP)
    patch = planned("a", NoteOp.PATCH, sections=(Section("Related", "- [[B]]"),))
    after = patched_note(before, patch, today=TODAY, note_id="n-1")
    added = [line for line in added_text(before, after).split("\n") if line]
    assert added == ["id: n-1", f"updated: {TODAY}", "- [[B]]"]
    assert added_text(None, after) == after.render()


def test_build_outcomes_reports_patches_of_missing_notes_and_creates_of_existing_ones() -> None:
    existing = {"sop - x": Note.parse("30-SOPs/SOP - X.md", SOP)}
    plan = SplitPlan(
        atoms=(),
        notes=(
            planned("SOP - X", NoteOp.PATCH, folder=""),
            planned("New note"),
            planned("Missing", NoteOp.PATCH, folder=""),
            planned("sop - X", NoteOp.CREATE),
        ),
        topic_proposal=None,
    )
    outcomes, problems = build_outcomes(plan, existing, today=TODAY, new_id=sequential_ids())
    assert set(outcomes) == {"sop - x", "new note"}
    assert outcomes["sop - x"].before is existing["sop - x"]
    assert outcomes["new note"].before is None
    assert outcomes["new note"].added == outcomes["new note"].after.render()
    assert problems == [
        "Missing: patched, but no such note exists",
        "sop - X: already exists; patch it instead (§15.3)",
    ]


@pytest.mark.parametrize("heading", ["Steps", " Steps ", "Steps\t"])
def test_headings_match_despite_surrounding_spaces(heading: str) -> None:
    assert add_to_section("## Steps\n\n1. a\n", heading, "2. b") == "## Steps\n\n1. a\n2. b\n"
