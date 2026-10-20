"""What a capture becomes (Handbook §12), pure."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.domain import capture
from notebook_assistant.domain.capture import Email
from notebook_assistant.domain.invariants import VaultFacts, check_note
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import load_rules

P = PurePosixPath
RULES = load_rules()
INBOX = P("00-Inbox/2026-10-20 1402.md")


def test_inbox_files_are_every_file_there_but_dotfiles() -> None:
    assert capture.is_inbox_file(P("00-Inbox/a.7z"), RULES)
    assert not capture.is_inbox_file(P("00-Inbox/.keep"), RULES)
    assert not capture.is_inbox_file(P("01-Daily/2026-10-20.md"), RULES)
    assert not capture.is_inbox_file(P(""), RULES)


def test_the_inbox_title_is_the_minute_numbered_when_taken() -> None:
    now = datetime(2026, 10, 20, 14, 2, tzinfo=UTC)
    assert capture.inbox_title(now, lambda t: False) == "2026-10-20 1402"
    taken = {"2026-10-20 1402", "2026-10-20 1402 2"}
    assert capture.inbox_title(now, taken.__contains__) == "2026-10-20 1402 3"


def test_attachments_are_named_after_their_note() -> None:
    assert capture.attachment_name("Polars LazyFrame", 1, ".PNG") == "Polars LazyFrame - 1.png"


def test_an_inbox_note_keeps_the_text_then_embeds_the_files() -> None:
    note = capture.inbox_note(
        INBOX, " a line \n", kind="image", origin="own", captured="2026-10-20", embeds=["x - 1.png"]
    )
    assert note.props == {"kind": "image", "origin": "own", "captured": "2026-10-20"}
    assert note.body == "a line\n\n![[x - 1.png]]\n"
    assert capture.inbox_note(INBOX, "", kind="text", origin="own", captured="d").body == "\n"


EMAIL = Email(
    subject="Concur: policy?",
    sender="Amy <amy@example.com>",
    recipients=("jason@example.com",),
    date="2026-09-26",
    body="Please file by Friday.",
    attachments=(),
)


def test_an_email_is_named_and_shaped_as_its_source_note() -> None:
    title = capture.email_title(EMAIL, RULES)
    assert title == "2026-09-26 email Concur - policy？"
    pattern = RULES.types["source"].title_pattern
    assert pattern is not None and pattern.match(title)
    assert capture.email_title(replace(EMAIL, subject=""), RULES).endswith("email no subject")
    note = capture.email_note(
        P(f"00-Inbox/{title}.md"), EMAIL, origin="own", embeds=["a - 1.pdf"], original="a - 2.eml"
    )
    assert note.props["subject"] == "Concur: policy?" and note.props["kind"] == "email"
    assert note.props["recipients"] == ["jason@example.com"] and note.props["date"] == "2026-09-26"
    assert note.body == "Please file by Friday.\n\n![[a - 1.pdf]]\n![[a - 2.eml]]\n"


def test_the_capture_s_own_words_leave_out_its_files() -> None:
    assert (
        capture.without_embeds("a\n\n![[x.png]]\n\n\nb [[link]]\n![[y.pdf]]") == "a\n\nb [[link]]"
    )


@pytest.mark.parametrize(
    ("kind", "lines", "origin", "keeps"),
    [
        ("text", 3, "own", False),  # short typed text cites the daily note
        ("text", 31, "own", True),  # long text keeps its source
        ("text", 31, "ai-chat", False),  # an AI answer never does, however long
        ("image", 1, "own", True),
        ("email", 1, "own", True),
    ],
)
def test_which_captures_keep_a_source_note(kind: str, lines: int, origin: str, keeps: bool) -> None:
    text = "\n".join(f"line {i}" for i in range(lines))
    assert capture.keeps_source(kind, text, origin, RULES) is keeps


def test_the_subject_is_the_first_words() -> None:
    assert capture.subject_of("\n## Kedro *hooks* run `before` ![[x.png]] a b c d e f") == (
        "Kedro hooks run before a b c d"
    )
    assert capture.subject_of("![[x.png]]\n") == ""
    assert capture.source_title("2026-10-20", "image", "", RULES) == "2026-10-20 image image"
    assert capture.source_title("2026-10-20", "text", "a: b", RULES) == "2026-10-20 text a - b"


def test_source_and_daily_notes_have_one_live_status() -> None:
    assert capture.live_status(RULES, "source") == "active"
    assert capture.live_status(RULES, "daily") == "active"
    with pytest.raises(ValueError, match="live statuses"):
        capture.live_status(RULES, "task")


def facts() -> VaultFacts:
    return VaultFacts(RULES)


def test_a_source_note_obeys_the_handbook() -> None:
    inbox = capture.inbox_note(
        INBOX,
        "shot",
        kind="image",
        origin="own",
        captured="2026-10-19",
        embeds=["2026-10-20 1402 - 1.png"],
    )
    note = capture.source_note(
        inbox,
        "2026-10-19 image shot",
        rules=RULES,
        scope="personal",
        today="2026-10-20",
        extracted=["Kedro hooks"],
        renames={"2026-10-20 1402 - 1.png": "2026-10-19 image shot - 1.png"},
    )
    assert note.path == P("70-Sources/2026-10-19 image shot.md")
    assert "![[2026-10-19 image shot - 1.png]]" in note.body and "1402 - 1" not in note.body
    assert note.body.endswith("## Extracted\n\n- [[Kedro hooks]]\n")
    assert note.props["processed"] == "2026-10-20" and note.props["created"] == "2026-10-19"
    assert check_note(note, facts()) == []


def test_the_daily_note_logs_what_a_short_capture_produced() -> None:
    path = P("01-Daily/2026-10-20.md")
    new = capture.daily_logged(
        None, path, rules=RULES, scope="personal", today="2026-10-20", extracted=["A", "B"]
    )
    assert new.body == "- Captured [[A]], [[B]]\n" and new.props["date"] == "2026-10-20"
    assert check_note(new, facts()) == []
    existing = Note.parse(path, "---\ntype: daily\nupdated: 2026-10-01\n---\n- earlier\n")
    logged = capture.daily_logged(
        existing, path, rules=RULES, scope="personal", today="2026-10-20", extracted=["A"]
    )
    assert (
        logged.body == "- earlier\n- Captured [[A]]\n" and logged.props["updated"] == "2026-10-20"
    )
    empty = Note.parse(path, "---\ntype: daily\n---\n")
    assert (
        capture.daily_logged(
            empty, path, rules=RULES, scope="personal", today="d", extracted=["A"]
        ).body
        == "- Captured [[A]]\n"
    )
