"""The digestion queue's state changes on one note (Handbook §19)."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.domain import digest
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import load_rules

RULES = load_rules()
TODAY = "2026-10-20"
STUB = """---
type: knowledge
kind: concept
status: seed
digest: pending
digest_reason: [stub, screenshot-only]
updated: 2026-09-01
---
Accuracy, Precision and Recall
![[Confusion matrix - 1.png]]
"""


def stub() -> Note:
    return Note.parse(PurePosixPath("60-Knowledge/ML/Confusion matrix.md"), STUB)


def test_a_queued_note_is_an_item_and_others_are_not() -> None:
    item = digest.item_of(stub(), RULES)
    assert (
        item is not None and item.state == "pending" and item.reasons == ["stub", "screenshot-only"]
    )
    plain = Note.parse(PurePosixPath("a.md"), "---\ntype: knowledge\n---\nx\n")
    assert digest.item_of(plain, RULES) is None


def test_approve_records_the_runner_and_a_failure_returns_to_the_queue() -> None:
    running = digest.approved(stub(), RULES, runner="pc", started="2026-10-20T10:00", today=TODAY)
    assert running.props["digest"] == "approved" and running.props["digest_runner"] == "pc"
    back = digest.failed(running, RULES, error="network down", today=TODAY)
    assert back.props["digest"] == "pending" and back.props["digest_error"] == "network down"
    assert "digest_runner" not in back.props and back.props["updated"] == TODAY


def test_an_in_place_draft_keeps_the_original_in_the_box() -> None:
    draft = digest.drafted_in_place(
        stub(), "## Summary\n\nA table of predictions.", RULES, today=TODAY
    )
    assert draft.props["digest"] == "review"
    assert draft.body.startswith(
        "## Summary\n\nA table of predictions.\n\n> [!quote]- Original capture\n"
    )
    assert "> Accuracy, Precision and Recall\n> ![[Confusion matrix - 1.png]]" in draft.body
    assert digest.original_of(draft.body, RULES) == stub().body
    redrafted = digest.drafted_in_place(draft, "## Summary\n\nBetter.", RULES, today=TODAY)
    assert redrafted.body.count("Original capture") == 1  # the original, not the old draft
    assert digest.original_of("no box\n", RULES) is None


def test_sending_back_restores_the_original_with_feedback() -> None:
    draft = digest.drafted_in_place(stub(), "## Summary\n\nDraft.", RULES, today=TODAY)
    back = digest.sent_back(draft, " add the formulas ", RULES, today=TODAY)
    assert back.body == stub().body and back.props["digest"] == "pending"
    assert back.props["digest_feedback"] == "add the formulas"


def test_graduating_sets_what_the_handbook_says() -> None:
    done = digest.graduated(stub(), RULES, today=TODAY)
    for key, value in RULES.digestion.graduate.items():
        assert done.props[key] == value
    assert done.props["digest"] == "graduated" and "digest_reason" not in done.props
    as_is = digest.graduated_as_is(stub(), RULES, today=TODAY)
    assert as_is.props["graduated_via"] == "direct" and as_is.body == stub().body


def test_a_learn_task_links_its_draft_and_closes_with_produced() -> None:
    task = Note.parse(
        PurePosixPath("10-Tasks/Learn Kedro hooks.md"),
        "---\ntype: task\nkind: learn\nstatus: todo\ndigest: approved\n---\nraw\n",
    )
    linked = digest.draft_linked(task, "Kedro hooks", RULES, today=TODAY)
    assert linked.props["digest_draft"] == "[[Kedro hooks]]" and linked.props["digest"] == "review"
    closed = digest.task_closed(linked, "Kedro hooks", RULES, today=TODAY)
    assert closed.props["status"] == "done" and closed.props["produced"] == ["[[Kedro hooks]]"]
    assert "digest_draft" not in closed.props and closed.body == "raw\n"


def test_the_moc_gains_a_link_once() -> None:
    moc = Note.parse(
        PurePosixPath("60-Knowledge/ML/MOC - ML.md"),
        "---\ntype: moc\n---\n## Notes\n\n- [[Random forest]]\n",
    )
    linked = digest.moc_linking(moc, "Confusion matrix", today=TODAY)
    assert linked is not None and linked.body.endswith(
        "- [[Random forest]]\n- [[Confusion matrix]]\n"
    )
    assert digest.moc_linking(linked, "confusion MATRIX", today=TODAY) is None
