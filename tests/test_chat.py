"""Chat: the tool-use loop and its tools, on the fixture vault with a scripted model."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import pytest

from notebook_assistant.adapters.fake_llm import ScriptedChat, ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.adapters.sqlite_search import SqliteSearch
from notebook_assistant.app import chat
from notebook_assistant.app.chat_tools import HIDDEN, ToolContext, run_tool
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.ports.llm import ChatReply, LanguageModel, LLMError, ToolCall
from notebook_assistant.store import changesets as cs_store
from tests.test_inbox_app import SENTENCE, plan

P = PurePosixPath
RULES = load_rules()
CONFIG = load_default_config()
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
POLARS = "60-Knowledge/Software/Polars with_columns.md"


def reply(text: str = "", *calls: tuple[str, JsonObject]) -> ChatReply:
    return ChatReply(text, tuple(ToolCall(f"t{i}", n, a) for i, (n, a) in enumerate(calls)), 10, 2)


def ctx(
    store: MemoryVault, scope: str = "all", planner: LanguageModel | None = None
) -> ToolContext:
    model = planner or ScriptedModel([])
    return ToolContext(
        store,
        SqliteSearch(":memory:"),
        RULES,
        CONFIG,
        handbook_text(),
        NOW,
        scope,
        created_by="session:ses-1",
        planner=lambda: model,
    )


def run(
    store: MemoryVault,
    replies: list[ChatReply | LLMError],
    question: str = "how do I add columns?",
    pinned: list[str] | None = None,
) -> tuple[chat.Answer, list[JsonObject], ScriptedChat]:
    note = chat.start_session(
        store, RULES, title=question, now=NOW, device="test-pc", model="m", scope="all"
    )
    events: list[JsonObject] = []
    model = ScriptedChat(replies)
    result = chat.answer(
        store,
        note.path.as_posix(),
        question,
        pinned=pinned or [],
        chat=model,
        planner=lambda: ScriptedModel([]),
        search_index=SqliteSearch(":memory:"),
        config=CONFIG,
        rules=RULES,
        handbook=handbook_text(),
        now=NOW,
        emit=events.append,
    )
    return result, events, model


def test_a_turn_searches_reads_answers_and_is_recorded(memory_vault: MemoryVault) -> None:
    result, events, model = run(
        memory_vault,
        [
            reply("Let me look.", ("search", {"query": "with_columns"})),
            reply("", ("read_note", {"note": "Polars with_columns"})),
            reply("Use with_columns [[Polars with_columns]]."),
        ],
    )
    assert result.text == "Let me look.\n\nUse with_columns [[Polars with_columns]]."
    assert result.cited == ["Polars with_columns"]
    assert [e["type"] for e in events if e["type"] != "token"] == ["tool", "tool", "done"]
    first = model.requests[0]
    assert first.system[1] == handbook_text() and "## The question" in first.messages[-1].text
    assert "Polars with_columns" in first.messages[-1].text  # the index found it for the question
    note = Note.parse(P(result.session), memory_vault.read_text(P(result.session)))
    assert note.props["notes_cited"] == ["[[Polars with_columns]]"] and note.props["tokens"] == {
        "in": 30,
        "out": 6,
    }
    assert "> [!tool]- search(with_columns)" in note.body
    again, _, _ = run(memory_vault, [reply("Yes.")], question="and chaining?")
    assert again.text == "Yes."


def test_the_next_turn_sees_the_conversation_so_far(memory_vault: MemoryVault) -> None:
    first, _, _ = run(memory_vault, [reply("Answer one.")])
    events: list[JsonObject] = []
    model = ScriptedChat([reply("Answer two.")])
    chat.answer(
        memory_vault,
        first.session,
        "follow up",
        pinned=[POLARS],
        chat=model,
        planner=lambda: ScriptedModel([]),
        search_index=SqliteSearch(":memory:"),
        config=CONFIG,
        rules=RULES,
        handbook=handbook_text(),
        now=NOW,
        emit=events.append,
    )
    messages = model.requests[0].messages
    assert [m.text for m in messages[:2]] == ["how do I add columns?", "Answer one."]
    assert "## Pinned: [[Polars with_columns]]" in messages[-1].text


def test_the_tool_call_limit_stops_a_runaway_turn(memory_vault: MemoryVault) -> None:
    looping = [
        reply("", ("search", {"query": "x"})) for _ in range(CONFIG.limits.tool_calls_per_turn + 1)
    ]
    result, _, model = run(memory_vault, [*looping, reply("Stopping here.")])
    last_results = model.requests[-1].messages[-1].tool_results
    assert last_results[0].is_error and "limit" in last_results[0].content
    assert result.text == "Stopping here."


def test_an_unknown_session_is_refused(memory_vault: MemoryVault) -> None:
    with pytest.raises(chat.ChatError):
        chat.answer(
            memory_vault,
            "nowhere.md",
            "q",
            pinned=[],
            chat=ScriptedChat([]),
            planner=lambda: ScriptedModel([]),
            search_index=SqliteSearch(":memory:"),
            config=CONFIG,
            rules=RULES,
            handbook="",
            now=NOW,
            emit=lambda e: None,
        )


NEW_NOTE: JsonObject = {
    "title": "Polars select",
    "folder": "60-Knowledge/Software",
    "body": "## Summary\n\nselect picks columns.",
    "properties": {
        "type": "knowledge",
        "kind": "concept",
        "scope": "personal",
        "status": "seed",
        "created": "2026-10-21",
        "updated": "2026-10-21",
        "topic": "[[MOC - Software]]",
    },
}


def test_propose_note_saves_a_pending_changeset_or_says_why_not(memory_vault: MemoryVault) -> None:
    c = ctx(memory_vault)
    text, failed = run_tool(c, "propose_note", NEW_NOTE)
    assert not failed and "Nothing changed yet" in text
    assert cs_store.find(memory_vault, c.changesets[0]) is not None
    assert not memory_vault.exists(P("60-Knowledge/Software/Polars select.md"))
    bad: JsonObject = {**NEW_NOTE, "title": "Other", "properties": {"type": "knowledge"}}
    text, failed = run_tool(c, "propose_note", bad)
    assert failed and "breaks the handbook" in text
    text, failed = run_tool(c, "propose_note", {**NEW_NOTE, "title": "Polars with_columns"})
    assert failed and "propose_edit" in text
    assert run_tool(ctx(memory_vault, scope="work"), "propose_note", NEW_NOTE) == (
        "this chat is limited to scope 'work'",
        True,
    )
    assert run_tool(c, "propose_note", {**NEW_NOTE, "properties": "x"})[1]


def test_propose_edit_guards_with_the_base_hash(memory_vault: MemoryVault) -> None:
    c = ctx(memory_vault)
    old = memory_vault.read_text(P(POLARS))
    _, failed = run_tool(
        c, "propose_edit", {"note": "Polars with_columns", "new_text": old + "\nMore.\n"}
    )
    assert not failed
    record = cs_store.find(memory_vault, c.changesets[0])
    assert record is not None and cs_store.load(memory_vault, record).ops[0].base_hash
    assert run_tool(c, "propose_edit", {"note": "Polars with_columns", "new_text": old})[1]
    assert run_tool(
        c, "propose_edit", {"note": "Polars with_columns", "new_text": "no frontmatter"}
    )[1]
    assert run_tool(c, "propose_edit", {"note": "nowhere", "new_text": "x"})[1]


def test_sensitive_notes_are_hidden_and_scope_limits_reading(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(
        P("40-Reference/Credentials/VPN.md"),
        "---\ntype: credential\nscope: work\nstatus: active\ncreated: 2026-10-01\n"
        "updated: 2026-10-01\nservice: VPN\nsensitive: true\n---\n## Login\npassword: hunter2\n",
    )
    text, failed = run_tool(ctx(memory_vault), "read_note", {"note": "VPN"})
    assert not failed and "hunter2" not in text and HIDDEN in text and "## Login" in text
    assert run_tool(ctx(memory_vault, scope="personal"), "read_note", {"note": "VPN"})[1]
    assert run_tool(ctx(memory_vault), "read_note", {})[1]
    assert run_tool(ctx(memory_vault), "nope", {}) == ("no tool 'nope'", True)
    found, _ = run_tool(ctx(memory_vault, scope="personal"), "search", {"query": "VPN"})
    assert found == "No note matches."


def test_propose_digest_runs_the_extraction_planner(memory_vault: MemoryVault) -> None:
    answer: Any = plan("[[x]]")
    props = answer["notes"][0]["properties"]
    answer["notes"][0]["properties"] = [p for p in props if p["key"] != "source"]
    c = ctx(memory_vault, planner=ScriptedModel([answer]))
    text, failed = run_tool(c, "propose_digest", {"text": SENTENCE, "origin": "own"})
    assert not failed and "Kedro hooks" in text and len(c.changesets) == 1
    assert run_tool(c, "propose_digest", {"text": "x", "origin": "dream"})[1]
    offline = ctx(memory_vault, planner=ScriptedModel([LLMError("offline"), LLMError("offline")]))
    text, failed = run_tool(offline, "propose_digest", {"text": SENTENCE})
    assert failed and "offline" in text
