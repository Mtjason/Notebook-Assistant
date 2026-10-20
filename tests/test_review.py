"""The Review screen's use cases on a real planned changeset (the recorded uv answer)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.adapters.overlay_vault import OverlayVault
from notebook_assistant.app import review
from notebook_assistant.app.extract import Capture, plan_extraction
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.review import ReviewError
from notebook_assistant.config import load_default_config
from notebook_assistant.domain.changeset import Changeset, Status
from notebook_assistant.domain.split_plan import parse_plan
from notebook_assistant.handbook import handbook_text
from notebook_assistant.store import changesets as cs_store
from tests.conftest import NOW, sequential_ids, uv_capture_text, uv_plan_json

P = PurePosixPath
CONFIG = load_default_config()
SOP = P("30-SOPs/SOP - Install uv (Linux).md")
NEW = P("60-Knowledge/Systems/curl pipe to shell install.md")


def proposed(store: MemoryVault) -> Changeset:
    result = plan_extraction(
        Capture(uv_capture_text(), "ai-chat", "uv answer"),
        VaultIndex.build(store),
        ScriptedModel([uv_plan_json()]),
        config=CONFIG,
        handbook=handbook_text(),
        now=NOW,
        created_by="user:test",
        new_id=sequential_ids(),
    )
    cs_store.save(store, result.changeset)
    return review.load(store, result.changeset.id)


def detail(store: MemoryVault, cs: Changeset) -> review.ChangesetDetail:
    return review.changeset_detail(store, cs, now=NOW, sandbox=OverlayVault)


def test_pending_and_history_lists(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    assert [s.id for s in review.list_changesets(memory_vault, pending=True)] == [cs.id]
    assert review.list_changesets(memory_vault, pending=False) == []
    review.reject(memory_vault, cs)
    assert [s.status for s in review.list_changesets(memory_vault, pending=False)] == ["rejected"]
    with pytest.raises(ReviewError, match="no changeset"):
        review.load(memory_vault, "cs-missing")


def test_detail_shows_operations_checks_and_atoms(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    shown = detail(memory_vault, cs)
    sop = next(op for op in shown.operations if op.path == SOP.as_posix())
    assert sop.kind == "write" and sop.before == memory_vault.read_text(SOP)
    assert sop.after is not None and "curl pipe to shell install" in sop.after
    new = next(op for op in shown.operations if op.path == NEW.as_posix())
    assert new.before is None and new.after is not None
    assert [c.name for c in shown.checks] == ["nothing lost", "base hash", "links", "rules"]
    assert all(c.ok for c in shown.checks)
    assert "zsh" in [a.id for a in shown.atoms] and "Bash commands" in shown.planned_notes
    assert shown.review.startswith("### Split map")


def test_a_stale_target_fails_the_base_hash_check(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    memory_vault.write_text(SOP, memory_vault.read_text(SOP) + "edited by you\n")
    checks = {c.name: c for c in detail(memory_vault, cs).checks}
    assert not checks["base hash"].ok and "changed since the proposal" in checks["base hash"].detail


def test_apply_selected_then_undo(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    before = memory_vault.read_text(SOP)
    with pytest.raises(ReviewError, match="choose operations"):
        review.apply_selected(memory_vault, cs, [99], now=NOW, machine="pc")
    sop, new = (next(i for i, op in enumerate(cs.ops) if op.path == p) for p in (SOP, NEW))
    result = review.apply_selected(memory_vault, cs, [new, sop], now=NOW, machine="pc")
    assert result.ok and memory_vault.read_text(SOP) != before and memory_vault.exists(NEW)
    applied = review.load(memory_vault, cs.id)
    assert applied.status is Status.APPLIED and len(applied.ops) == 2  # the patches were dropped
    views = {v.path: v for v in review.operation_views(memory_vault, applied)}
    assert views[SOP.as_posix()].before == before  # from the recorded reverse operation
    assert views[NEW.as_posix()].before is None
    assert detail(memory_vault, applied).checks == []  # only pending changesets are checked
    assert review.undo(memory_vault, applied, now=NOW + timedelta(minutes=1)).ok
    assert memory_vault.read_text(SOP) == before
    assert review.load(memory_vault, cs.id).status is Status.REVERTED
    with pytest.raises(ReviewError, match="not pending"):
        review.reject(memory_vault, applied)


def test_moving_an_atom_recompiles_the_changeset(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    problems = review.move_atom_in(
        memory_vault,
        cs,
        "zsh",
        "SOP - Install uv (Linux)",
        config=CONFIG,
        now=NOW,
        new_id=sequential_ids(),
    )
    assert problems == []
    moved = review.load(memory_vault, cs.id)
    sop = next(op for op in moved.ops if op.path == SOP)
    assert sop.content is not None and "source ~/.zshrc" in sop.content
    assert moved.source is not None
    plan = parse_plan(moved.source.plan)
    assert next(a for a in plan.atoms if a.id == "zsh").notes == ("SOP - Install uv (Linux)",)


def test_an_atom_move_the_checks_reject_leaves_the_changeset_alone(
    memory_vault: MemoryVault,
) -> None:
    cs = proposed(memory_vault)
    overlap = review.move_atom_in(
        memory_vault, cs, "path-correction", None, config=CONFIG, now=NOW, new_id=sequential_ids()
    )
    assert overlap == ["atom path-correction overlaps atom bashrc; move or drop that one"]
    broken = review.move_atom_in(
        memory_vault, cs, "zsh", "Bash commands", config=CONFIG, now=NOW, new_id=sequential_ids()
    )
    assert broken == [
        "SOP - Install uv (Linux) doesn't link to Bash commands (§3.1)",
        "Bash commands doesn't link to SOP - Install uv (Linux) (§3.1)",
    ]
    assert review.load(memory_vault, cs.id).ops == cs.ops


def test_applying_half_of_a_dependent_change_is_refused(memory_vault: MemoryVault) -> None:
    """The SOP patch links to the note the changeset creates; alone, the link would dangle."""
    cs = proposed(memory_vault)
    sop = next(i for i, op in enumerate(cs.ops) if op.path == SOP)
    result = review.apply_selected(memory_vault, cs, [sop], now=NOW, machine="pc")
    assert not result.ok and result.error is not None and "points nowhere" in result.error
    assert review.load(memory_vault, cs.id).status is Status.FAILED


def test_actions_on_a_changeset_without_a_capture(memory_vault: MemoryVault) -> None:
    plain = Changeset(reason="r", created_by="t", created=NOW.isoformat())
    cs_store.save(memory_vault, plain)
    with pytest.raises(ReviewError, match="wasn't planned from a capture"):
        review.move_atom_in(
            memory_vault, plain, "a", None, config=CONFIG, now=NOW, new_id=sequential_ids()
        )
    assert detail(memory_vault, plain).atoms == []
