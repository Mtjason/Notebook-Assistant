"""The extraction planner end to end, with a scripted model: request → plan → checks → changeset,
then applying it leaves the fixture vault compliant."""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any

import pytest

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.extract import (
    INSTRUCTIONS,
    Capture,
    Extraction,
    ExtractionError,
    build_request,
    catalog,
    compile_changeset,
    plan_extraction,
    related_notes,
    split_map,
)
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.invariants import check_note
from notebook_assistant.domain.split_plan import PLAN_SCHEMA, TopicProposal, parse_plan
from notebook_assistant.handbook import handbook_text
from notebook_assistant.ports.llm import LLMError
from tests.conftest import NOW, sequential_ids, uv_capture_text, uv_plan_json

CONFIG = load_default_config()
CAPTURE = Capture(uv_capture_text(), "ai-chat", "uv answer")
P = PurePosixPath


def run(store: MemoryVault, model: ScriptedModel) -> Extraction:
    return plan_extraction(
        CAPTURE,
        VaultIndex.build(store),
        model,
        config=CONFIG,
        handbook=handbook_text(),
        now=NOW,
        created_by="user:cli",
        new_id=sequential_ids(),
    )


def unlinked_plan() -> dict[str, Any]:
    """The recorded plan with the link from the principle note back to the SOP removed."""
    data = copy.deepcopy(uv_plan_json())
    note = data["notes"][1]
    note["body"] = note["body"].replace(" Worked example: [[SOP - Install uv (Linux)]].", "")
    return data


# ----- the request


def test_related_notes_are_ranked_by_shared_terms(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    titles = [n.title for n in related_notes(index, CAPTURE.text, 3)]
    assert len(titles) == 3 and "Bash commands" in titles
    assert related_notes(index, "zzz qqq", 5) == []  # nothing shared, nothing shown
    assert related_notes(index, CAPTURE.text, 0) == []


def test_catalog_lists_every_note_once(memory_vault: MemoryVault) -> None:
    text = catalog(VaultIndex.build(memory_vault))
    assert "- SOP - Install uv (Linux) | sop | 30-SOPs | aliases: Install uv, 安裝 uv" in text
    assert "- raw capture | no type | 00-Inbox" in text
    assert len(text.split("\n")) == 13


def test_request_puts_the_stable_parts_first_and_feedback_last(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    request = build_request(CAPTURE, index, config=CONFIG, handbook="HB", feedback=[])
    assert request.model == CONFIG.models.transform
    assert request.max_tokens == CONFIG.limits.max_tokens_per_job
    assert request.system == (INSTRUCTIONS, "HB") and request.schema == PLAN_SCHEMA
    assert "## The capture (origin: ai-chat)" in request.prompt
    assert "### 60-Knowledge/Systems/Bash commands.md" in request.prompt
    assert "rejected" not in request.prompt
    again = build_request(CAPTURE, index, config=CONFIG, handbook="HB", feedback=["no link"])
    assert again.prompt.endswith("fix these problems\n\n- no link")


# ----- planning


def test_a_good_plan_becomes_a_pending_changeset_that_applies(memory_vault: MemoryVault) -> None:
    model = ScriptedModel([uv_plan_json()])
    result = run(memory_vault, model)
    assert result.attempts == 1 and result.rejected == []
    cs = result.changeset
    assert cs.reason == "Digest uv answer" and cs.created_by == "user:cli"
    assert [(op.kind, op.path.as_posix()) for op in cs.ops] == [
        ("write", "30-SOPs/SOP - Install uv (Linux).md"),
        ("create", "60-Knowledge/Systems/curl pipe to shell install.md"),
        ("write", "60-Knowledge/Systems/Bash commands.md"),
        ("write", "60-Knowledge/Systems/MOC - Systems.md"),
    ]
    assert "### Split map" in cs.review and "### Dropped as filler" in cs.review

    assert apply_changeset(memory_vault, cs, now=NOW).ok, cs.error
    index = VaultIndex.build(memory_vault)
    facts = index.facts()
    assert {
        n.title: check_note(n, facts) for n in index.notes.values() if check_note(n, facts)
    } == {}
    assert index.broken == []
    created = memory_vault.read_text(P("60-Knowledge/Systems/curl pipe to shell install.md"))
    assert created.startswith("---\nid: n-test-1\ntype: knowledge\nkind: concept\n")
    assert "digest: review" in created and "origin: ai-chat" in created


def test_a_failing_plan_is_sent_back_once_with_its_problems(memory_vault: MemoryVault) -> None:
    model = ScriptedModel([unlinked_plan(), uv_plan_json()])
    result = run(memory_vault, model)
    assert result.attempts == 2
    problem = "curl pipe to shell install doesn't link to SOP - Install uv (Linux) (§3.1)"
    assert result.rejected == [[problem]]
    assert f"- {problem}" in model.requests[1].prompt


def test_a_malformed_plan_is_sent_back_too(memory_vault: MemoryVault) -> None:
    model = ScriptedModel([{"atoms": []}, uv_plan_json()])
    result = run(memory_vault, model)
    assert result.attempts == 2
    assert "the plan is malformed: plan has no 'notes'" in model.requests[1].prompt


def test_two_failing_plans_raise_with_the_last_problems(memory_vault: MemoryVault) -> None:
    model = ScriptedModel([unlinked_plan(), unlinked_plan(), uv_plan_json()])
    with pytest.raises(ExtractionError) as info:
        run(memory_vault, model)
    assert info.value.problems == [
        "curl pipe to shell install doesn't link to SOP - Install uv (Linux) (§3.1)"
    ]
    assert len(model.requests) == 2


def test_model_failures_propagate(memory_vault: MemoryVault) -> None:
    with pytest.raises(LLMError, match="declined"):
        run(memory_vault, ScriptedModel([LLMError("the model declined the request")]))


# ----- the review card and the operations


def test_split_map_lists_atoms_filler_and_a_topic_proposal(memory_vault: MemoryVault) -> None:
    result = run(memory_vault, ScriptedModel([uv_plan_json()]))
    plan = result.plan
    text = split_map(plan, result.outcomes)
    assert "| install-steps | instance | [[SOP - Install uv (Linux)]] (patch) |" in text
    assert "| curl-flags | principle | [[curl pipe to shell install]] (new) |" in text
    assert "\\| sh" in text  # table pipes in excerpts are escaped
    assert "- 詳細的拆解說明如下：" in text
    assert "amendment draft" not in text

    proposed = type(plan)(plan.atoms, plan.notes, TopicProposal("Networking", "a", "b", "c"))
    assert "| `Networking/` | a | b | c |" in split_map(proposed, result.outcomes)


def test_writes_carry_the_base_hash_of_the_stored_note(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    result = run(memory_vault, ScriptedModel([uv_plan_json()]))
    cs = compile_changeset(
        result.outcomes, index, reason="r", created_by="c", now=NOW, review="map"
    )
    sop = next(op for op in cs.ops if op.path.name == "SOP - Install uv (Linux).md")
    assert sop.base_hash == content_hash(memory_vault.read_bytes(sop.path))
    assert all(op.base_hash is None for op in cs.ops if op.kind == "create")
    assert cs.review == "map" and cs.created == NOW.isoformat(timespec="seconds")


def test_the_recorded_plan_parses_for_every_test_here() -> None:
    assert len(parse_plan(uv_plan_json()).notes) == 4
