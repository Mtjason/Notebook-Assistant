"""The Inbox endpoints: list, capture (multipart), and process as a job."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Any

from fastapi.testclient import TestClient

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.api.server import create_app
from notebook_assistant.domain.capture import Email
from notebook_assistant.ports.email import EmailError
from notebook_assistant.ports.llm import LLMError
from tests.conftest import NOW
from tests.test_inbox_app import SENTENCE, plan
from tests.test_server_digest import HOST, WRITE, finished


def no_email(name: str, data: bytes) -> Email:
    raise EmailError("not an email")


@contextmanager
def client(store: MemoryVault, answers: list[Any]) -> Iterator[TestClient]:
    model = ScriptedModel(answers)
    app = create_app(
        store,
        HOST,
        vault_label="/v",
        web_dir=None,
        allowed_hosts=["testserver"],
        clock=lambda: NOW,
        model=lambda: model,
        emails=no_email,
    )
    with TestClient(app) as api:
        yield api


def test_the_inbox_lists_notes_and_the_origins(memory_vault: MemoryVault) -> None:
    with client(memory_vault, []) as api:
        view = api.get("/api/inbox").json()
    assert [i["title"] for i in view["items"]] == ["raw capture"]
    assert view["default_origin"] == "own" and "ai-chat" in view["origins"]


def test_capture_then_process_proposes_a_changeset(memory_vault: MemoryVault) -> None:
    with client(memory_vault, [plan("[[2026-09-27]]")]) as api:
        saved = api.post(
            "/api/capture",
            data={"origin": "own", "text": SENTENCE},
            files=[("files", ("notes.txt", b"", "text/plain"))],
            headers=WRITE,
        )
        assert saved.status_code == 200, saved.text
        [path] = saved.json()["paths"]
        assert path == "00-Inbox/2026-09-27 1000.md"
        started = api.post(f"/api/inbox/process/{path}", headers=WRITE)
        assert started.status_code == 200 and started.json()["kind"] == "process"
        job = finished(api, started.json()["id"])
        assert job["state"] == "done", job
        assert job["message"] == "1 note(s) proposed" and job["changeset"]
        detail = api.get(f"/api/changesets/{job['changeset']}").json()
    assert detail["summary"]["status"] == "pending"
    assert memory_vault.exists(PurePosixPath(path))  # nothing applied yet


def test_a_failed_plan_is_reported_on_the_job(memory_vault: MemoryVault) -> None:
    with client(memory_vault, [LLMError("can't reach the Claude API")]) as api:
        started = api.post("/api/inbox/process/00-Inbox/raw capture.md", headers=WRITE)
        job = finished(api, started.json()["id"])
    assert job["state"] == "failed" and job["message"] == "can't reach the Claude API"
    assert job["changeset"] is None


def test_what_the_endpoints_refuse(memory_vault: MemoryVault) -> None:
    with client(memory_vault, []) as api:
        empty = api.post("/api/capture", data={"origin": "own"}, headers=WRITE)
        assert empty.status_code == 400 and "nothing to capture" in empty.json()["detail"]
        email = api.post(
            "/api/capture",
            data={"origin": "own"},
            files=[("files", ("a.eml", b"x", "message/rfc822"))],
            headers=WRITE,
        )
        assert email.status_code == 400 and "not an email" in email.json()["detail"]
        assert api.post("/api/capture", data={"origin": "own", "text": "x"}).status_code == 403
        outside = api.post(
            "/api/inbox/process/60-Knowledge/Software/Polars with_columns.md", headers=WRITE
        )
        assert outside.status_code == 404
