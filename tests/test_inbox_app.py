"""The Inbox end to end: capture, process through the planner (scripted model), apply."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app import inbox, review
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.capture import capture_to_inbox
from notebook_assistant.app.clicks import Button
from notebook_assistant.app.extract import Extraction
from notebook_assistant.app.filing import FilingError, scope_of
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.capture import CapturedFile, Email
from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.store import changesets as cs_store
from tests.conftest import sequential_ids

P = PurePosixPath
RULES = load_rules()
CONFIG = load_default_config()
NOW = datetime(2026, 10, 20, 14, 2, tzinfo=UTC)
CLICK = Button("test-pc", NOW)
SENTENCE = "Kedro hooks run before and after each node."


def plan(source: str, text: str = SENTENCE, title: str = "Kedro hooks") -> JsonObject:
    return {
        "atoms": [
            {"id": "a1", "text": text, "role": "principle", "notes": [title], "citation": ""}
        ],
        "notes": [
            {
                "title": title,
                "op": "create",
                "folder": "60-Knowledge/Software",
                "properties": [
                    {"key": "type", "value": "knowledge"},
                    {"key": "kind", "value": "concept"},
                    {"key": "scope", "value": "personal"},
                    {"key": "status", "value": "seed"},
                    {"key": "topic", "value": "[[MOC - Software]]"},
                    {"key": "aliases", "value": [title, "Kedro 鉤子"]},
                    {"key": "origin", "value": "own"},
                    {"key": "digest", "value": "review"},
                    {"key": "source", "value": source},
                ],
                "body": f"## Summary\n\n{text}\n",
                "sections": [],
                "history": [],
            }
        ],
        "topic_proposal": None,
    }


def save(store: MemoryVault, text: str, files: list[CapturedFile] | None = None) -> str:
    def no_email(name: str, data: bytes) -> Email:
        raise AssertionError("no email here")

    outcome = capture_to_inbox(
        store,
        text=text,
        files=files or [],
        origin="own",
        rules=RULES,
        click=CLICK,
        read_email=no_email,
    )
    return outcome.paths[0]


def process(store: MemoryVault, path: str, answer: JsonObject) -> Extraction:
    steps: list[str] = []
    result = inbox.process(
        store,
        path,
        ScriptedModel([answer]),
        config=CONFIG,
        rules=RULES,
        handbook=handbook_text(),
        now=NOW,
        created_by="button:process",
        progress=steps.append,
        new_id=sequential_ids(),
    )
    assert steps[-1] == "Proposed 1 note(s) for review"
    return result


def note(store: MemoryVault, path: str) -> Note:
    return Note.parse(P(path), store.read_text(P(path)))


def test_the_inbox_lists_what_waits_there(memory_vault: MemoryVault) -> None:
    save(memory_vault, "a line", [CapturedFile("x.png", b"\x89PNG")])
    items = inbox.inbox_items(memory_vault, RULES)
    assert [i.title for i in items] == ["2026-10-20 1402", "raw capture"]
    first, raw = items
    assert (first.kind, first.origin, first.captured) == ("image", "own", "2026-10-20")
    assert first.files == ["Attachments/2026-10-20 1402 - 1.png"]
    assert first.preview == "a line ![[2026-10-20 1402 - 1.png]]"
    assert (raw.kind, raw.origin, raw.captured, raw.gap) == ("text", "own", None, None)


def test_a_short_capture_cites_the_daily_note_and_is_logged_there(
    memory_vault: MemoryVault,
) -> None:
    path = save(memory_vault, SENTENCE)
    result = process(memory_vault, path, plan("[[2026-10-20]]"))
    cs = result.changeset
    assert [(op.kind, op.path.as_posix()) for op in cs.ops] == [
        ("create", "60-Knowledge/Software/Kedro hooks.md"),
        ("delete", path),
        ("create", "01-Daily/2026-10-20.md"),
    ]
    assert cs_store.load(memory_vault, cs_store.record_path(cs)).source == cs.source
    applied = apply_changeset(memory_vault, cs, now=NOW, machine="test-pc")
    assert applied.ok, applied.error
    assert not memory_vault.exists(P(path))
    assert note(memory_vault, "01-Daily/2026-10-20.md").body == "- Captured [[Kedro hooks]]\n"
    assert (
        note(memory_vault, "60-Knowledge/Software/Kedro hooks.md").props["source"]
        == "[[2026-10-20]]"
    )


def test_an_existing_daily_note_gets_a_line(memory_vault: MemoryVault) -> None:
    path = save(memory_vault, SENTENCE)
    memory_vault.write_text(
        P(path), memory_vault.read_text(P(path)).replace("2026-10-20", "2026-09-27")
    )
    cs = process(memory_vault, path, plan("[[2026-09-27]]")).changeset
    assert [(op.kind, op.label) for op in cs.ops][-1] == ("write", "log the capture")
    assert apply_changeset(memory_vault, cs, now=NOW, machine="test-pc").ok
    assert note(memory_vault, "01-Daily/2026-09-27.md").body.endswith(
        "- Captured [[Kedro hooks]]\n"
    )


def test_a_screenshot_capture_keeps_a_source_note_with_renamed_files(
    memory_vault: MemoryVault,
) -> None:
    path = save(memory_vault, SENTENCE, [CapturedFile("shot.png", b"\x89PNG")])
    title = "2026-10-20 image Kedro hooks run before and after each node"
    model_plan = plan(f"[[{title}]]")
    result = process(memory_vault, path, model_plan)
    assert result.changeset.source is not None
    assert result.changeset.source.cites == P(f"70-Sources/{title}.md")
    applied = apply_changeset(memory_vault, result.changeset, now=NOW, machine="test-pc")
    assert applied.ok, applied.error
    source = note(memory_vault, f"70-Sources/{title}.md")
    assert source.props["type"] == "source" and source.props["kind"] == "image"
    assert f"![[{title} - 1.png]]" in source.body and "- [[Kedro hooks]]" in source.body
    assert memory_vault.read_bytes(P(f"Attachments/{title} - 1.png")) == b"\x89PNG"
    assert not memory_vault.exists(P("Attachments/2026-10-20 1402 - 1.png"))


def test_the_model_sees_the_text_and_the_screenshots(memory_vault: MemoryVault) -> None:
    path = save(memory_vault, SENTENCE, [CapturedFile("shot.png", b"\x89PNG")])
    model = ScriptedModel([plan("[[x]]"), plan("[[x]]")])
    with pytest.raises(Exception, match="source must be"):
        inbox.process(
            memory_vault,
            path,
            model,
            config=CONFIG,
            rules=RULES,
            handbook=handbook_text(),
            now=NOW,
            created_by="t",
        )
    request = model.requests[0]
    assert [i.label for i in request.images] == ["screenshot 1: 2026-10-20 1402 - 1.png"]
    assert "![[" not in request.prompt.split("## The capture")[1].split("## Provenance")[0]
    assert "## Provenance" in request.prompt


def two_atoms(memory_vault: MemoryVault) -> tuple[str, JsonObject]:
    path = save(memory_vault, f"{SENTENCE} Thanks for asking!")
    answer = plan("[[2026-10-20]]", text=f"{SENTENCE} Thanks for asking!")
    answer["atoms"] = [
        {
            "id": "a1",
            "text": SENTENCE,
            "role": "principle",
            "notes": ["Kedro hooks"],
            "citation": "",
        },
        {
            "id": "a2",
            "text": "Thanks for asking!",
            "role": "principle",
            "notes": ["Kedro hooks"],
            "citation": "",
        },
    ]
    return path, answer


def test_moving_an_atom_keeps_the_filing(memory_vault: MemoryVault) -> None:
    path, answer = two_atoms(memory_vault)
    cs = process(memory_vault, path, answer).changeset
    assert (
        review.move_atom_in(
            memory_vault, cs, "a2", None, config=CONFIG, now=NOW, new_id=sequential_ids()
        )
        == []
    )
    saved = cs_store.load(memory_vault, cs_store.record_path(cs))
    assert [op.kind for op in saved.ops] == ["create", "delete", "create"]
    assert "Thanks for asking!" not in (saved.ops[0].content or "")


def test_a_recompile_after_the_inbox_note_went_says_so(memory_vault: MemoryVault) -> None:
    path, answer = two_atoms(memory_vault)
    cs = process(memory_vault, path, answer).changeset
    memory_vault.delete(P(path))
    problems = review.move_atom_in(
        memory_vault, cs, "a2", None, config=CONFIG, now=NOW, new_id=sequential_ids()
    )
    assert problems == [f"{path} is no longer in the Inbox"]


def test_what_cant_be_processed(memory_vault: MemoryVault) -> None:
    with pytest.raises(inbox.InboxError, match="isn't a raw note"):
        process(memory_vault, "60-Knowledge/Software/Polars with_columns.md", {})
    only_files = save(memory_vault, "", [CapturedFile("x.png", b"\x89PNG")])
    with pytest.raises(inbox.InboxError, match="no text, only files"):
        process(memory_vault, only_files, {})
    long = save(memory_vault, "\n".join(f"line {i}" for i in range(40)))
    memory_vault.write_text(P("70-Sources/2026-10-20 text line 0.md"), "x")
    with pytest.raises(inbox.InboxError, match="already exists"):
        process(memory_vault, long, {})


def test_every_inbox_file_is_listed_with_why_it_can_t_be_processed(
    memory_vault: MemoryVault,
) -> None:
    for name, data in [
        (".keep", b""),
        (
            "Drawing 2026-10-04 23.08.20.excalidraw.md",
            b"---\nexcalidraw-plugin: parsed\n---\n# Text\nhi\n",
        ),
        ("Untitled.canvas", b"{}"),
        ("technician_resource_check_shared.7z", b"7z"),
        ("Screenshot 0931.png", b"\x89PNG"),
        ("empty.md", b""),
    ]:
        memory_vault.write_bytes(P(f"00-Inbox/{name}"), data)
    items = {i.title: i for i in inbox.inbox_items(memory_vault, RULES)}
    assert ".keep" not in items and len(items) == 6
    assert items["raw capture"].blocked is None
    drawing = items["Drawing 2026-10-04 23.08.20.excalidraw.md"]
    assert (drawing.kind, drawing.origin, drawing.preview) == ("file", "", "")
    assert "graduated as-is" in str(drawing.blocked)
    assert "graduated as-is" in str(items["Untitled.canvas"].blocked)
    bare = items["technician_resource_check_shared.7z"]
    assert (bare.kind, bare.files) == ("file", ["00-Inbox/technician_resource_check_shared.7z"])
    assert "without a note" in str(bare.blocked)
    assert items["Screenshot 0931.png"].kind == "image"
    assert "no text" in str(items["empty"].blocked)
    with pytest.raises(inbox.InboxError, match="graduated as-is"):
        process(memory_vault, "00-Inbox/Drawing 2026-10-04 23.08.20.excalidraw.md", {})


def test_the_cited_note_follows_section_12(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    raw = index.note(P("00-Inbox/raw capture.md"))
    assert raw is not None
    assert inbox.cited_note(index, raw, RULES, today="2026-10-20") == P("01-Daily/2026-10-20.md")
    email = Note.parse(
        P("00-Inbox/2026-09-26 email Policy.md"), "---\nkind: email\n---\nPlease file.\n"
    )
    assert inbox.cited_note(index, email, RULES, today="d") == P(
        "70-Sources/2026-09-26 email Policy.md"
    )


def test_captured_on_and_kind_of() -> None:
    plain = Note.parse(P("00-Inbox/n.md"), "---\ncreated: 2026-10-01\n---\nx\n")
    assert inbox.captured_on(plain, "2026-10-20") == "2026-10-01"
    assert inbox.captured_on(Note(path=P("00-Inbox/n.md"), body=""), "2026-10-20") == "2026-10-20"


def test_the_filed_note_s_scope_is_the_plan_s(memory_vault: MemoryVault) -> None:
    path = save(memory_vault, SENTENCE)
    result = process(memory_vault, path, plan("[[2026-10-20]]"))
    assert scope_of(result.outcomes) == "personal"
    with pytest.raises(FilingError, match="no note with a scope"):
        scope_of({})
