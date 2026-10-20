"""The chat endpoints: a session, a turn as a job, the transcript; and the retention task."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from notebook_assistant.adapters.fake_llm import ScriptedChat, ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.api.server import create_app
from notebook_assistant.ports.llm import ChatReply, LLMError, ToolCall
from notebook_assistant.store import lease
from tests.test_server_digest import HOST, WRITE, finished


@contextmanager
def client(
    store: MemoryVault, replies: Sequence[ChatReply | LLMError], retention: bool = False
) -> Iterator[TestClient]:
    chat = ScriptedChat(replies)
    app = create_app(
        store,
        HOST,
        vault_label="/v",
        web_dir=None,
        allowed_hosts=["testserver"],
        clock=lambda: datetime(2026, 10, 21, 9, 0, tzinfo=UTC),
        model=lambda: ScriptedModel([]),
        chat=lambda: chat,
        retention=retention,
    )
    with TestClient(app) as api:
        yield api


def test_a_turn_runs_as_a_job_and_lands_in_the_transcript(memory_vault: MemoryVault) -> None:
    replies = [
        ChatReply("", (ToolCall("t1", "read_note", {"note": "Polars with_columns"}),), 5, 1),
        ChatReply("See [[Polars with_columns]].", (), 5, 1),
    ]
    with client(memory_vault, replies) as api:
        made = api.post("/api/sessions", json={"title": "columns?"}, headers=WRITE)
        assert made.status_code == 200
        path = made.json()["path"]
        started = api.post(f"/api/sessions/turn/{path}", json={"text": "columns?"}, headers=WRITE)
        assert started.status_code == 200 and started.json()["kind"] == "chat"
        job = finished(api, started.json()["id"])
        assert job["state"] == "done"
        view = api.get(f"/api/sessions/view/{path}").json()
    assert [t["role"] for t in view["turns"]] == ["You", "Assistant"]
    assert view["turns"][1]["text"] == "See [[Polars with_columns]]."
    assert view["turns"][1]["tools"] == ["read_note(Polars with_columns)"]


def test_a_failed_turn_and_bad_requests(memory_vault: MemoryVault) -> None:
    with client(memory_vault, [LLMError("offline")]) as api:
        path = api.post("/api/sessions", json={"title": "q"}, headers=WRITE).json()["path"]
        job = finished(
            api,
            api.post(f"/api/sessions/turn/{path}", json={"text": "q"}, headers=WRITE).json()["id"],
        )
        assert job["state"] == "failed" and job["message"] == "offline"
        assert (
            api.post(f"/api/sessions/turn/{path}", json={"text": " "}, headers=WRITE).status_code
            == 400
        )
        assert (
            api.post(
                "/api/sessions", json={"title": "q", "scope": "home"}, headers=WRITE
            ).status_code
            == 400
        )
        assert (
            api.get("/api/sessions/view/60-Knowledge/Software/Polars with_columns.md").status_code
            == 404
        )


def test_retention_runs_when_the_service_starts(memory_vault: MemoryVault) -> None:
    with client(memory_vault, [], retention=True):
        pass
    taken = lease.read(memory_vault)
    assert taken is not None and taken.holder == HOST.machine.name
