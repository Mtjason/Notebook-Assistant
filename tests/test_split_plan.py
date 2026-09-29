"""The split plan's schema and parser: the model's JSON becomes typed data, or a clear error."""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from notebook_assistant.domain.split_plan import (
    PLAN_SCHEMA,
    NoteOp,
    PlanFormatError,
    Role,
    parse_plan,
)
from tests.conftest import uv_plan_json


def _objects(schema: Any) -> list[dict[str, Any]]:
    """Every object schema inside ``schema``."""
    found: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found.extend(_objects(value))
    elif isinstance(schema, list):
        for item in schema:
            found.extend(_objects(item))
    return found


def test_schema_is_strict_everywhere() -> None:
    """Structured output needs every object closed and every property required."""
    objects = _objects(PLAN_SCHEMA)
    assert len(objects) >= 6
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])


def test_recorded_plan_parses() -> None:
    plan = parse_plan(uv_plan_json())
    assert {a.role for a in plan.atoms} == set(Role)  # the recorded plan uses every role
    sop = plan.note("sop - install UV (linux)")  # titles match like names: case-insensitively
    assert sop is not None and sop.op is NoteOp.PATCH and sop.folder == ""
    created = plan.note("curl pipe to shell install")
    assert created is not None and created.op is NoteOp.CREATE
    assert ("aliases", ["curl | sh", "管道安裝腳本"]) in created.properties
    assert {a.id for a in plan.atoms_for("curl pipe to shell install")} >= {"curl-flags", "zsh"}
    assert plan.topic_proposal is None


def test_topic_proposal_and_folder_slashes() -> None:
    data = uv_plan_json()
    data["topic_proposal"] = {
        "folder": "Networking/",
        "answers": "How networks work",
        "examples": "DNS",
        "not_here": "Shell → Systems",
    }
    data["notes"][1]["folder"] = "/60-Knowledge/Systems/"
    plan = parse_plan(data)
    assert plan.topic_proposal is not None and plan.topic_proposal.folder == "Networking"
    assert plan.notes[1].folder == "60-Knowledge/Systems"


def _broken(change: Any) -> dict[str, Any]:
    data = copy.deepcopy(uv_plan_json())
    change(data)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.pop("atoms"), "plan has no 'atoms'"),
        (lambda d: d.__setitem__("notes", {}), "plan.notes must be a list"),
        (lambda d: d["atoms"][0].__setitem__("role", "summary"), "atoms[0].role is 'summary'"),
        (lambda d: d["atoms"][0].__setitem__("text", 3), "atoms[0].text must be text"),
        (lambda d: d["atoms"][0].__setitem__("notes", "one"), "atoms[0].notes must be a list"),
        (lambda d: d["notes"][0].__setitem__("op", "rewrite"), "notes[0].op is 'rewrite'"),
        (lambda d: d["notes"][0].__setitem__("sections", ["x"]), "sections[0] must be an object"),
        (
            lambda d: d["notes"][1]["properties"].append({"key": "n", "value": 3}),
            "must be text, true/false or a list of text",
        ),
        (lambda d: d["atoms"][1].__setitem__("id", "intro"), "two atoms are named 'intro'"),
        (
            lambda d: d["notes"].append(copy.deepcopy(d["notes"][0])),
            "two notes are named 'SOP - Install uv (Linux)'",
        ),
        (lambda d: d.__setitem__("topic_proposal", {"folder": "X"}), "has no 'answers'"),
    ],
)
def test_malformed_plans_are_rejected_with_the_place(change: Any, message: str) -> None:
    with pytest.raises(PlanFormatError, match=re.escape(message)):
        parse_plan(_broken(change))
