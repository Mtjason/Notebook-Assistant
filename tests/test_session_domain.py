"""A chat session note: created, appended to, read back."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

from notebook_assistant.domain import session
from notebook_assistant.domain.frontmatter import load_yaml
from notebook_assistant.domain.note import Note, split_frontmatter

START = datetime(2026, 10, 21, 9, 5, tzinfo=UTC)


def make() -> Note:
    return session.new_session(
        "99-System/Assistant/Sessions",
        "ses-1",
        title="Kedro credentials",
        started=START,
        device="work-pc",
        model="claude-x",
        scope="all",
    )


def test_a_new_session_lives_by_year_and_month() -> None:
    note = make()
    assert note.path == PurePosixPath("99-System/Assistant/Sessions/2026/10/ses-1.md")
    assert (
        note.props["title"] == "Kedro credentials"
        and note.props["started"] == "2026-10-21T09:05+00:00"
    )


def test_turns_are_appended_and_read_back_with_their_tools() -> None:
    note = session.with_turn(make(), "You", START, "where do credentials go?")
    note = session.with_turn(
        note,
        "Assistant",
        START.replace(minute=6),
        "In conf/local [[Kedro credentials]].",
        ['search("kedro credentials")', 'read_note("Kedro credentials")'],
    )
    text = note.render()
    assert "## 09:05 · You\n\nwhere do credentials go?\n\n## 09:06 · Assistant" in text
    assert '> [!tool]- search("kedro credentials")' in text
    you, answer = session.turns(Note.parse(note.path, text))
    assert (you.role, you.time, you.text, you.tools) == (
        "You",
        "09:05",
        "where do credentials go?",
        [],
    )
    assert answer.text == "In conf/local [[Kedro credentials]]." and len(answer.tools) == 2


def test_meta_merges_citations_changesets_and_tokens() -> None:
    note = session.with_meta(make(), cited=["A"], changesets=["cs-1"], tokens_in=10, tokens_out=2)
    note = session.with_meta(note, cited=["A", "B"], changesets=[], tokens_in=5, tokens_out=1)
    fm_text, _ = split_frontmatter(note.render())
    data = load_yaml(fm_text or "")
    assert data["notes_cited"] == ["[[A]]", "[[B]]"] and data["changesets"] == ["cs-1"]
    assert data["tokens"] == {"in": 15, "out": 3}
    assert (
        "changesets"
        not in session.with_meta(make(), cited=[], changesets=[], tokens_in=0, tokens_out=0).props
    )
