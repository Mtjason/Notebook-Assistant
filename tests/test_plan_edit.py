"""Moving or dropping an atom by hand, and the plan's JSON round trip."""

from __future__ import annotations

from typing import Any

import pytest

from notebook_assistant.domain.plan_edit import MOVED_HEADING, PlanEditError, move_atom
from notebook_assistant.domain.split_plan import Atom, Role, SplitPlan, parse_plan, plan_to_json
from tests.conftest import uv_plan_json

PLAN = parse_plan(uv_plan_json())
SOP, CURL, BASH = "SOP - Install uv (Linux)", "curl pipe to shell install", "Bash commands"


def atom(plan: SplitPlan, atom_id: str) -> Atom:
    return next(a for a in plan.atoms if a.id == atom_id)


def test_the_plan_round_trips_through_json() -> None:
    assert parse_plan(plan_to_json(PLAN)) == PLAN


def test_moving_an_atom_cuts_its_text_and_adds_it_to_the_target() -> None:
    text = atom(PLAN, "zsh").text
    moved = move_atom(PLAN, "zsh", SOP)
    assert atom(moved, "zsh").notes == (SOP,) and atom(moved, "zsh").role is Role.PRINCIPLE
    curl = moved.note(CURL)
    sop = moved.note(SOP)
    assert curl is not None and text not in curl.body
    assert sop is not None and sop.sections[-1].content.endswith(text)


def test_a_created_note_takes_the_text_at_the_end_of_its_body() -> None:
    moved = move_atom(PLAN, "intro", CURL)
    curl = moved.note(CURL)
    assert curl is not None and curl.body.rstrip().endswith(atom(PLAN, "intro").text)


def test_a_patch_without_sections_gets_one() -> None:
    data: dict[str, Any] = uv_plan_json()
    data["notes"][2]["sections"] = []
    bare = parse_plan(data)
    moved = move_atom(bare, "intro", BASH)
    bash = moved.note(BASH)
    assert bash is not None and bash.sections[0].heading == MOVED_HEADING


def test_dropping_an_atom_makes_it_filler() -> None:
    dropped = move_atom(PLAN, "zsh", None)
    assert atom(dropped, "zsh").role is Role.FILLER and atom(dropped, "zsh").notes == ()
    curl = dropped.note(CURL)
    assert curl is not None and atom(PLAN, "zsh").text not in curl.body


def test_moving_filler_into_a_note_makes_it_an_extracted_item() -> None:
    moved = move_atom(PLAN, "lead-in", BASH)
    assert atom(moved, "lead-in").role is Role.EXTRACTED


@pytest.mark.parametrize(
    ("atom_id", "to", "message"),
    [
        ("nope", SOP, "no atom 'nope'"),
        ("zsh", "Nowhere", "no note 'Nowhere'"),
        ("path-correction", SOP, "overlaps atom bashrc"),
        ("command-rows", SOP, "overlaps atom install-steps"),
    ],
)
def test_edits_that_cant_be_made_say_why(atom_id: str, to: str, message: str) -> None:
    with pytest.raises(PlanEditError, match=message):
        move_atom(PLAN, atom_id, to)


def test_an_atom_whose_text_was_rewritten_cant_be_moved() -> None:
    data: dict[str, Any] = uv_plan_json()
    data["notes"][1]["body"] = "## Summary\n\nRewritten."
    with pytest.raises(PlanEditError, match="isn't verbatim in curl pipe to shell install"):
        move_atom(parse_plan(data), "zsh", SOP)
