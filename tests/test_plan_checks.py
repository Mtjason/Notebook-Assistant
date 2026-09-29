"""Split-plan checks: the recorded uv plan passes, and each rule catches its own mistake.

Every mutation below breaks exactly one thing a good plan must get right (docs/maintenance-job.md,
Extraction, step 7), so a check that stops firing fails its test.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from notebook_assistant.app.extract import Capture, evaluate
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.split_plan import parse_plan
from tests.conftest import load_fixture_memory, sequential_ids, uv_capture_text, uv_plan_json

SOP, CURL, BASH, MOC = 0, 1, 2, 3  # positions of the notes in the recorded plan
DOCS = "https://docs.astral.sh/uv/getting-started/installation/"


def problems(data: dict[str, Any], origin: str = "ai-chat") -> list[str]:
    index = VaultIndex.build(load_fixture_memory())
    _, found = evaluate(
        parse_plan(data),
        index,
        Capture(uv_capture_text(), origin, "uv answer"),
        config=load_default_config(),
        today="2026-09-30",
        new_id=sequential_ids(),
    )
    return found


def mutated(change: Callable[[dict[str, Any]], object]) -> dict[str, Any]:
    data = copy.deepcopy(uv_plan_json())
    change(data)
    return data


def atom(data: dict[str, Any], atom_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(a for a in data["atoms"] if a["id"] == atom_id)
    return found


def prop(data: dict[str, Any], note: int, key: str, value: object) -> None:
    props = [p for p in data["notes"][note]["properties"] if p["key"] != key]
    data["notes"][note]["properties"] = [*props, {"key": key, "value": value}]


def drop_prop(data: dict[str, Any], note: int, key: str) -> None:
    data["notes"][note]["properties"] = [
        p for p in data["notes"][note]["properties"] if p["key"] != key
    ]


def section(data: dict[str, Any], note: int, heading: str, content: str) -> None:
    data["notes"][note]["sections"].append({"heading": heading, "content": content})


def replace_in(data: dict[str, Any], note: int, field: str, old: str, new: str) -> None:
    note_data = data["notes"][note]
    if field == "body":
        assert old in note_data["body"]
        note_data["body"] = note_data["body"].replace(old, new)
    else:
        for item in note_data[field]:
            if isinstance(item, dict):
                item["content"] = item["content"].replace(old, new)
        note_data[field] = [
            i.replace(old, new) if isinstance(i, str) else i for i in note_data[field]
        ]


def uncited(d: dict[str, Any]) -> None:
    replace_in(d, SOP, "sections", DOCS, "the docs")
    replace_in(d, SOP, "history", DOCS, "the docs")


def gap_outside_inbox(d: dict[str, Any]) -> None:
    prop(d, CURL, "handbook_gap", "Networking")
    prop(d, CURL, "needs_review", True)


def gap_unflagged(d: dict[str, Any]) -> None:
    d["notes"][CURL]["folder"] = "00-Inbox"
    prop(d, CURL, "handbook_gap", "Networking")


def test_the_recorded_plan_passes_every_check() -> None:
    assert problems(uv_plan_json()) == []


def test_a_topic_gap_plan_passes_when_it_waits_in_the_inbox() -> None:
    def gap(d: dict[str, Any]) -> None:
        d["notes"][CURL]["folder"] = "00-Inbox"
        prop(d, CURL, "needs_review", True)
        prop(d, CURL, "handbook_gap", "no topic fits; proposed topic Networking")
        d["topic_proposal"] = {
            "folder": "Networking",
            "answers": "How networks and downloads work",
            "examples": "curl, HTTP redirects",
            "not_here": "Shell usage → Systems",
        }

    assert problems(mutated(gap)) == []


MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], object], str]] = [
    (
        "atom invented",
        lambda d: atom(d, "intro").__setitem__("text", "uv is fast."),
        "atom intro: its text is not a verbatim excerpt",
    ),
    (
        "filler kept",
        lambda d: atom(d, "lead-in").__setitem__("notes", ["SOP - Install uv (Linux)"]),
        "atom lead-in: filler is dropped",
    ),
    (
        "principle in two notes",
        lambda d: atom(d, "zsh")["notes"].append("Bash commands"),
        "atom zsh: must land in exactly one note, not 2",
    ),
    (
        "correction nowhere",
        lambda d: atom(d, "path-correction").__setitem__("notes", []),
        "a correction must land in the notes it corrects",
    ),
    (
        "unlisted note",
        lambda d: atom(d, "intro").__setitem__("notes", ["uv"]),
        "lands in 'uv', which the plan doesn't list",
    ),
    (
        "empty created note",
        lambda d: d["notes"].append({**copy.deepcopy(d["notes"][CURL]), "title": "curl flags"}),
        "curl flags: a created note must carry at least one atom",
    ),
    (
        "content lost",
        lambda d: replace_in(d, CURL, "body", atom(d, "zsh")["text"], ""),
        "content lost: 1 code block/URL/link(s) missing; 1 sentence(s) missing or changed",
    ),
    (
        "principle duplicated",
        lambda d: section(d, SOP, "Gotchas", atom(d, "curl-flags")["text"]),
        "atom curl-flags: principle text repeated in SOP - Install uv (Linux)",
    ),
    (
        "no link back",
        lambda d: replace_in(d, CURL, "body", "Worked example: [[SOP - Install uv (Linux)]].", ""),
        "curl pipe to shell install doesn't link to SOP - Install uv (Linux) (§3.1)",
    ),
    (
        "dangling link",
        lambda d: section(d, MOC, "Notes", "- [[Nowhere]]"),
        "MOC - Systems: link to 'Nowhere' points nowhere",
    ),
    (
        "correction unsourced",
        lambda d: atom(d, "path-correction").__setitem__("citation", ""),
        "atom path-correction: a correction needs a source URL",
    ),
    (
        "correction cites the capture",
        lambda d: atom(d, "path-correction").__setitem__("citation", "https://blog.csdn.net"),
        "the capture's own references don't verify it",
    ),
    (
        "citation on a non-correction",
        lambda d: atom(d, "intro").__setitem__("citation", DOCS),
        "atom intro: only corrections cite a source",
    ),
    (
        "correction not written into the note",
        uncited,
        f"SOP - Install uv (Linux) doesn't cite {DOCS}",
    ),
    ("no aliases", lambda d: drop_prop(d, CURL, "aliases"), "needs aliases in both languages"),
    (
        "digest state",
        lambda d: prop(d, CURL, "digest", "pending"),
        "a new knowledge note gets digest: review (§19.6)",
    ),
    (
        "assistant property",
        lambda d: prop(d, CURL, "created", "2020-01-01"),
        "sets created, which the assistant manages",
    ),
    (
        "handbook gap outside the Inbox",
        gap_outside_inbox,
        "waits on a handbook gap, so it goes to the Inbox",
    ),
    (
        "handbook gap not flagged",
        gap_unflagged,
        "waits on a handbook gap, so needs_review: true",
    ),
    (
        "existing topic proposed",
        lambda d: d.__setitem__(
            "topic_proposal",
            {"folder": "Systems", "answers": "a", "examples": "b", "not_here": "c"},
        ),
        "topic 'Systems' already exists",
    ),
    (
        "proposal nobody waits on",
        lambda d: d.__setitem__(
            "topic_proposal",
            {"folder": "Networking", "answers": "a", "examples": "b", "not_here": "c"},
        ),
        "topic 'Networking' is proposed but no note waits on it",
    ),
    (
        "handbook rule",
        lambda d: prop(d, CURL, "kind", "essay"),
        "curl pipe to shell install: I-3 kind: 'essay' is not one of",
    ),
]


@pytest.mark.parametrize(("change", "expected"), [(c, e) for _, c, e in MUTATIONS],
                         ids=[name for name, _, _ in MUTATIONS])  # fmt: skip
def test_each_check_catches_its_mistake(
    change: Callable[[dict[str, Any]], object], expected: str
) -> None:
    found = problems(mutated(change))
    assert any(expected in p for p in found), "\n".join(found)


def test_origin_must_match_the_capture() -> None:
    found = problems(uv_plan_json(), origin="own")
    assert "curl pipe to shell install: origin must stay 'own' (§12)" in found
