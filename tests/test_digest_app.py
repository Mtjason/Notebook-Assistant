"""The Digest buttons end to end on the fixture vault, with a scripted model."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app import digest as buttons
from notebook_assistant.app.digest import Button, DigestError
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.ports.llm import JsonRequest, LanguageModel, LLMError
from notebook_assistant.store import changesets as cs_store

P = PurePosixPath
RULES = load_rules()
CONFIG = load_default_config()
CLICK = Button("test-pc", datetime(2026, 10, 20, 10, 0, tzinfo=UTC))
STUB = P("60-Knowledge/Software/Polars LazyFrame dt error.md")
TASK = P("10-Tasks/Learn Kedro hooks.md")
MOC = P("60-Knowledge/Software/MOC - Software.md")
STUB_TEXT = """---
type: knowledge
kind: troubleshooting
scope: personal
status: seed
created: 2026-09-01
updated: 2026-09-01
topic: "[[MOC - Software]]"
aliases: [LazyFrame dt error]
digest: pending
digest_reason: [stub, screenshot-only]
---
.dt fails on a LazyFrame
![[Polars with_columns - 1.png]]
"""
DRAFT = """## Symptom

`.dt` fails on a LazyFrame (screenshot 1).

## Cause

It needs an expression.

## Fix

Move it into `with_columns`.
"""


@pytest.fixture
def vault(memory_vault: MemoryVault) -> MemoryVault:
    memory_vault.write_text(STUB, STUB_TEXT)
    return memory_vault


def note(store: MemoryVault, path: P) -> Note:
    found = VaultIndex.build(store).note(path)
    assert found is not None
    return found


def approve(store: MemoryVault, ref: str, model: LanguageModel) -> buttons.DigestOutcome:
    steps: list[str] = []
    outcome = buttons.approve_to_digest(
        store,
        ref,
        model,
        config=CONFIG,
        rules=RULES,
        handbook=handbook_text(),
        click=CLICK,
        progress=steps.append,
    )
    assert steps[0] == "Approved on test-pc"
    return outcome


def test_a_knowledge_note_is_drafted_in_place_with_its_screenshot(vault: MemoryVault) -> None:
    model = ScriptedModel([{"body": DRAFT}])
    outcome = approve(vault, STUB.as_posix(), model)
    assert outcome.ok and outcome.state == "review" and len(outcome.changesets) == 2
    [request] = model.requests
    assert request.model == CONFIG.models.digest
    assert [i.label for i in request.images] == ["screenshot 1: Polars with_columns - 1.png"]
    drafted = note(vault, STUB)
    assert drafted.props["digest"] == "review" and "digest_runner" not in drafted.props
    assert drafted.body.startswith("## Symptom") and "> [!quote]- Original capture" in drafted.body
    records = [cs_store.load(vault, p) for p in cs_store.list_records(vault)]
    assert {cs.created_by for cs in records} == {"button:approve-to-digest", "button:digest-draft"}


def test_only_queued_notes_can_be_approved(vault: MemoryVault) -> None:
    with pytest.raises(DigestError, match="isn't waiting in the digest queue"):
        approve(vault, MOC.as_posix(), ScriptedModel([]))
    with pytest.raises(DigestError, match="no note"):
        approve(vault, "nowhere.md", ScriptedModel([]))


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (LLMError("can't reach the Claude API"), "can't reach the Claude API"),
        ({"body": "  "}, "the model returned no draft"),
    ],
)
def test_a_failed_run_returns_the_note_to_the_queue_with_why(
    vault: MemoryVault, answer: JsonObject | LLMError, message: str
) -> None:
    outcome = approve(vault, STUB.as_posix(), ScriptedModel([answer]))
    assert not outcome.ok and outcome.message == message
    back = note(vault, STUB)
    assert back.props["digest"] == "pending" and back.props["digest_error"] == message
    assert back.body == Note.parse(STUB, STUB_TEXT).body


def test_an_edit_during_digestion_discards_the_draft(vault: MemoryVault) -> None:
    class EditsMeanwhile:
        def complete_json(self, request: JsonRequest) -> JsonObject:
            vault.write_text(STUB, vault.read_text(STUB) + "a line you added\n")
            return {"body": DRAFT}

    outcome = approve(vault, STUB.as_posix(), EditsMeanwhile())
    assert not outcome.ok and "changed while it was being digested" in outcome.message
    back = note(vault, STUB)
    assert back.props["digest"] == "pending" and "a line you added" in back.body


def test_graduating_an_in_place_draft_links_it_from_its_moc(vault: MemoryVault) -> None:
    approve(vault, STUB.as_posix(), ScriptedModel([{"body": DRAFT}]))
    outcome = buttons.graduate(vault, STUB.as_posix(), rules=RULES, click=CLICK)
    assert outcome.ok and outcome.state == "graduated"
    done = note(vault, STUB)
    assert done.props["status"] == "evergreen" and done.props["origin"] == "own"
    assert "- [[Polars LazyFrame dt error]]" in note(vault, MOC).body
    with pytest.raises(DigestError, match="no draft ready"):
        buttons.graduate(vault, STUB.as_posix(), rules=RULES, click=CLICK)


def test_sending_back_restores_the_original_for_the_next_draft(vault: MemoryVault) -> None:
    approve(vault, STUB.as_posix(), ScriptedModel([{"body": DRAFT}]))
    buttons.send_back(vault, STUB.as_posix(), "explain the cause", rules=RULES, click=CLICK)
    back = note(vault, STUB)
    assert (
        back.props["digest"] == "pending" and back.props["digest_feedback"] == "explain the cause"
    )
    assert back.body == Note.parse(STUB, STUB_TEXT).body
    model = ScriptedModel([{"body": DRAFT}])
    approve(vault, STUB.as_posix(), model)
    assert "explain the cause" in model.requests[0].prompt  # the redraft uses your feedback


def kedro_plan(task_body: str) -> JsonObject:
    lines = [line for line in task_body.splitlines() if line.strip()]
    return {
        "atoms": [
            {
                "id": f"a{i}",
                "text": line,
                "role": "principle",
                "notes": ["Kedro hooks"],
                "citation": "",
            }
            for i, line in enumerate(lines)
        ],
        "notes": [
            {
                "title": "Kedro hooks",
                "op": "create",
                "folder": "60-Knowledge/Software",
                "properties": [
                    {"key": "type", "value": "knowledge"},
                    {"key": "kind", "value": "concept"},
                    {"key": "scope", "value": "personal"},
                    {"key": "status", "value": "seed"},
                    {"key": "topic", "value": "[[MOC - Software]]"},
                    {"key": "aliases", "value": ["Kedro hooks", "Kedro 鉤子"]},
                    {"key": "origin", "value": "own"},
                    {"key": "digest", "value": "review"},
                ],
                "body": "## Summary\n\nWhat to learn about Kedro hooks.\n\n"
                + "\n".join(lines)
                + "\n",
                "sections": [],
                "history": [],
            }
        ],
        "topic_proposal": None,
    }


def test_a_learn_task_drafts_a_new_note_and_closes_on_graduation(vault: MemoryVault) -> None:
    text = vault.read_text(TASK).replace("status: todo\n", "status: todo\ndigest: pending\n")
    vault.write_text(TASK, text)
    outcome = approve(vault, TASK.as_posix(), ScriptedModel([kedro_plan(note(vault, TASK).body)]))
    assert outcome.ok, outcome.message
    task = note(vault, TASK)
    assert task.props["digest"] == "review" and task.props["digest_draft"] == "[[Kedro hooks]]"
    draft = note(vault, P("60-Knowledge/Software/Kedro hooks.md"))
    assert draft.props["digest"] == "review"

    buttons.graduate(vault, TASK.as_posix(), rules=RULES, click=CLICK)
    closed = note(vault, TASK)
    assert closed.props["status"] == "done" and closed.props["produced"] == ["[[Kedro hooks]]"]
    assert note(vault, draft.path).props["status"] == "evergreen"
    assert "- [[Kedro hooks]]" in note(vault, MOC).body


def test_graduate_as_is_leaves_the_content_alone(vault: MemoryVault) -> None:
    outcome = buttons.graduate_as_is(vault, STUB.as_posix(), rules=RULES, click=CLICK)
    assert outcome.ok
    done = note(vault, STUB)
    assert done.props["graduated_via"] == "direct" and done.body == Note.parse(STUB, STUB_TEXT).body
    with pytest.raises(DigestError, match="isn't placed yet"):
        buttons.graduate_as_is(vault, "00-Inbox/raw capture.md", rules=RULES, click=CLICK)


def test_a_canvas_gets_a_companion_note_whose_kind_you_choose(vault: MemoryVault) -> None:
    canvas = "60-Knowledge/Software/Software map.canvas"
    with pytest.raises(DigestError, match="choose the companion note's kind"):
        buttons.graduate_as_is(vault, canvas, rules=RULES, click=CLICK)
    assert "concept" in buttons.companion_kinds(RULES)
    outcome = buttons.graduate_as_is(vault, canvas, rules=RULES, click=CLICK, kind="concept")
    assert outcome.ok
    companion = note(vault, P("60-Knowledge/Software/Software map.md"))
    assert companion.props["kind"] == "concept" and companion.props["scope"] == "personal"
    assert (
        "Start at [[Polars with_columns]]" in companion.body
        and "![[Software map.canvas]]" in companion.body
    )
    again = buttons.graduate_as_is(vault, canvas, rules=RULES, click=CLICK)  # the owner now exists
    assert again.ok
    with pytest.raises(DigestError, match="no canvas"):
        buttons.graduate_as_is(vault, "missing.canvas", rules=RULES, click=CLICK)
