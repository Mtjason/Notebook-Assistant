"""A click's changeset is applied at once and recorded."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.clicks import ApplyRefusedError, Button, apply_click
from notebook_assistant.domain.changeset import Changeset, Operation, Status
from notebook_assistant.store import changesets as cs_store

CLICK = Button("test-pc", datetime(2026, 10, 20, 9, 5, 7, tzinfo=UTC))
P = PurePosixPath


def test_a_button_knows_its_day_and_stamp() -> None:
    assert (CLICK.today, CLICK.stamp) == ("2026-10-20", "2026-10-20T09:05:07+00:00")


def test_a_click_applies_and_records(memory_vault: MemoryVault) -> None:
    op = Operation("create", P("00-Inbox/new.md"), content="hi\n")
    cs = Changeset(reason="r", created_by="button:test", created=CLICK.stamp, ops=[op])
    assert apply_click(memory_vault, cs, CLICK) == cs.id
    assert memory_vault.read_text(P("00-Inbox/new.md")) == "hi\n"
    [record] = [cs_store.load(memory_vault, p) for p in cs_store.list_records(memory_vault)]
    assert record.status is Status.APPLIED and record.machine == "test-pc"


def test_a_refused_click_says_why(memory_vault: MemoryVault) -> None:
    op = Operation("create", P("00-Inbox/raw capture.md"), content="clash\n")
    cs = Changeset(reason="r", created_by="button:test", created=CLICK.stamp, ops=[op])
    with pytest.raises(ApplyRefusedError, match="already exists"):
        apply_click(memory_vault, cs, CLICK)
