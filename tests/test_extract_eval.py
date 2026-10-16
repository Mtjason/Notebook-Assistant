"""The digestion eval: expected.yaml parses, and scoring finds what a plan gets right or wrong."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest

from notebook_assistant.app.extract import Capture, evaluate, paths_after
from notebook_assistant.app.extract_eval import (
    EvalFormatError,
    Expected,
    ExpectedAtom,
    Score,
    parse_expected,
    resolve_titles,
    score,
)
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.split_plan import NoteOp, Role, parse_plan
from tests.conftest import (
    UV_CAPTURE,
    load_fixture_memory,
    sequential_ids,
    uv_capture_text,
    uv_plan_json,
)

EXPECTED = parse_expected((UV_CAPTURE / "expected.yaml").read_text(encoding="utf-8"))


def scored(data: dict[str, Any], expected: Expected = EXPECTED) -> Score:
    index = VaultIndex.build(load_fixture_memory())
    plan = parse_plan(data)
    outcomes, _ = evaluate(
        plan,
        index,
        Capture(uv_capture_text(), expected.origin, "uv"),
        config=load_default_config(),
        today="2026-09-30",
        new_id=sequential_ids(),
    )
    return score(plan, outcomes, expected, paths_after(index, outcomes))


def test_expected_yaml_parses() -> None:
    assert EXPECTED.capture == "capture.md" and EXPECTED.origin == "ai-chat"
    flags = next(a for a in EXPECTED.atoms if a.id == "curl-flags")
    assert flags == ExpectedAtom(
        "curl-flags",
        Role.PRINCIPLE,
        ("curl pipe to shell install",),
        op=NoteOp.CREATE,
        type="knowledge",
        topic="Systems",
    )
    correction = next(a for a in EXPECTED.atoms if a.role is Role.CORRECTION)
    assert correction.requires_citation and len(correction.notes) == 2
    assert ("curl pipe to shell install", "MOC - Systems") in EXPECTED.links


def test_the_recorded_plan_scores_full_marks() -> None:
    result = scored(uv_plan_json())
    assert result.failed == [] and result.fraction == 1.0


def test_scoring_names_what_the_plan_got_wrong() -> None:
    data = copy.deepcopy(uv_plan_json())
    for atom in data["atoms"]:
        if atom["role"] == "principle":
            atom["notes"] = ["SOP - Install uv (Linux)"]  # everything filed under uv
        if atom["role"] == "correction":
            atom["citation"] = ""
    data["notes"][2]["sections"] = [{"heading": "Commands", "content": "curl and source."}]
    failed = scored(data).failed
    assert "atom curl-flags (principle → curl pipe to shell install)" in failed
    assert any(
        f.startswith("atom path-correction") and f.endswith(": cites a source") for f in failed
    )
    assert any(f.endswith("Bash commands: it adds no table rows") for f in failed)
    assert 0 < scored(data).fraction < 1


def test_target_checks_report_op_type_topic_and_missing_notes() -> None:
    expected = Expected(
        "capture.md",
        "ai-chat",
        (
            ExpectedAtom("a", Role.INSTANCE, ("SOP - Install uv (Linux)",), op=NoteOp.CREATE),
            ExpectedAtom("b", Role.PRINCIPLE, ("curl pipe to shell install",), type="sop"),
            ExpectedAtom("c", Role.PRINCIPLE, ("curl pipe to shell install",), topic="Software"),
            ExpectedAtom("d", Role.PRINCIPLE, ("uv notes",)),
        ),
        (("uv notes", "MOC - Systems"),),
    )
    failed = "\n".join(scored(uv_plan_json(), expected).failed)
    assert "SOP - Install uv (Linux): it is a patch, not a create" in failed
    assert "its type is 'knowledge', not 'sop'" in failed
    assert "not the Software topic" in failed
    assert "uv notes: the plan has no such note" in failed
    assert "link uv notes → MOC - Systems" in failed


def test_an_empty_score_counts_as_complete() -> None:
    assert Score().fraction == 1.0


HEAD = "capture: c.md\norigin: own\n"


def one_atom(body: str) -> str:
    return f"{HEAD}atoms:\n  - id: a\n{body}"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[1, 2]", "must be a mapping"),
        (f"{HEAD}atoms: {{}}\n", "atoms and links must be lists"),
        (f"{HEAD}atoms: [x]\n", "atoms[0] must be a mapping"),
        (one_atom("    role: x\n    target: {note: N}\n"), "atoms[0]: 'x' is not a valid Role"),
        (one_atom("    role: instance\n"), "target must be a mapping"),
        (one_atom("    role: instance\n    target: {op: create}\n"), "target needs a note"),
        ("capture: c.md\natoms: []\n", "origin must be text"),
        (f"{HEAD}atoms: []\nlinks: [x]\n", "links[0] must be a mapping"),
        ("capture: [\n", "invalid YAML"),
    ],
)
def test_malformed_expected_files_fail_loudly(text: str, message: str) -> None:
    with pytest.raises(EvalFormatError, match=re.escape(message)):
        parse_expected(text)


def real_answer() -> dict[str, Any]:
    """claude-sonnet-5's answer on 2026-10-17 (test checkpoint 1): sound split, different name."""
    text = (UV_CAPTURE / "real-answer-2026-10-17.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def test_a_renamed_note_costs_one_item_not_everything_aimed_at_it() -> None:
    result = scored(real_answer())
    assert result.failed == [
        "note curl pipe to shell install: the plan calls it 'curl pipe install pattern'",
        "atom curl-flags (principle → curl pipe to shell install): curl pipe to shell install:"
        " it is in 60-Knowledge/Software, not the Systems topic",
        "atom command-rows (extracted → Bash commands)",
        "atom path-correction (correction → SOP - Install uv (Linux), curl pipe to shell install)",
        "atom path-correction (correction → SOP - Install uv (Linux), curl pipe to shell"
        " install): cites a source",
        "link curl pipe to shell install → MOC - Systems",
    ]
    assert round(result.fraction, 2) == 0.67


def test_titles_resolve_exactly_then_by_role_and_operation() -> None:
    titles = resolve_titles(parse_plan(real_answer()), EXPECTED)
    assert titles["curl pipe to shell install"] == "curl pipe install pattern"
    assert titles["sop - install uv (linux)"] == "SOP - Install uv (Linux)"
    assert titles["moc - systems"] is None  # the plan doesn't touch it

    expected = Expected(
        "capture.md",
        "ai-chat",
        (
            ExpectedAtom("a", Role.PRINCIPLE, ("First",), op=NoteOp.CREATE),
            ExpectedAtom("b", Role.PRINCIPLE, ("Second",), op=NoteOp.CREATE),
            ExpectedAtom("c", Role.FILLER, ("Third",), op=NoteOp.PATCH),
        ),
        (),
    )
    resolved = resolve_titles(parse_plan(real_answer()), expected)
    assert resolved["first"] == "curl pipe install pattern"
    assert resolved["second"] is None  # already claimed by "First"
    assert resolved["third"] is None  # no patched note receives filler
