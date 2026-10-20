"""The Digest endpoints: the queue, approve-to-digest as a job, graduate, send back, as-is,
and the image endpoint the screens use."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Any

import pytest
from fastapi.testclient import TestClient

from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.api.events import EventBus
from notebook_assistant.api.jobs import JobBusyError, JobResult, JobRunner
from notebook_assistant.api.server import CLIENT_HEADER, create_app
from notebook_assistant.host import Host
from notebook_assistant.machine import MachineConfig
from notebook_assistant.platform.profiles import Profile
from notebook_assistant.ports.llm import LLMError
from tests.conftest import NOW
from tests.test_digest_app import DRAFT, STUB, STUB_TEXT

HOST = Host(MachineConfig("id-1", "test-pc"), Profile.LINUX)
WRITE = {"X-Requested-With": CLIENT_HEADER}


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
    )
    with TestClient(app) as api:  # one event loop for the whole test, as under uvicorn
        yield api


def finished(api: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(200):
        job: dict[str, Any] = api.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("the job didn't finish")


@pytest.fixture
def vault(memory_vault: MemoryVault) -> MemoryVault:
    memory_vault.write_text(STUB, STUB_TEXT)
    return memory_vault


def test_the_queue_lists_items_and_unowned_canvases(vault: MemoryVault) -> None:
    with client(vault, []) as api:
        queue = api.get("/api/digest").json()
    [item] = queue["items"]
    assert item["path"] == STUB.as_posix() and item["state"] == "pending"
    assert queue["canvases"] == ["60-Knowledge/Software/Software map.canvas"]
    assert "concept" in queue["kinds"]


def test_approve_runs_as_a_job_then_graduate(vault: MemoryVault) -> None:
    with client(vault, [{"body": DRAFT}]) as api:
        started = api.post(f"/api/digest/approve/{STUB}", headers=WRITE)
        assert started.status_code == 200 and started.json()["state"] == "running"
        job = finished(api, started.json()["id"])
        assert job["state"] == "done" and job["steps"][0] == "Approved on test-pc"
        assert job["steps"][-1] == "Draft ready"
        graduated = api.post(f"/api/digest/graduate/{STUB}", headers=WRITE).json()
        assert graduated == {"ok": True, "status": "graduated", "problems": []}
        again = api.post(f"/api/digest/graduate/{STUB}", headers=WRITE)
        assert again.status_code == 409


def test_a_failed_job_says_why(vault: MemoryVault) -> None:
    with client(vault, [LLMError("can't reach the Claude API")]) as api:
        job = finished(api, api.post(f"/api/digest/approve/{STUB}", headers=WRITE).json()["id"])
        assert job["state"] == "failed" and job["message"] == "can't reach the Claude API"


def test_approve_refuses_notes_outside_the_queue(vault: MemoryVault) -> None:
    with client(vault, []) as api:
        assert api.post("/api/digest/approve/nowhere.md", headers=WRITE).status_code == 404
        moc = "60-Knowledge/Software/MOC - Software.md"
        assert api.post(f"/api/digest/approve/{moc}", headers=WRITE).status_code == 409
        assert api.post(f"/api/digest/approve/{STUB}").status_code == 403  # no client header
        assert api.get("/api/jobs/job-missing").status_code == 404


def test_send_back_and_graduate_as_is(vault: MemoryVault) -> None:
    with client(vault, [{"body": DRAFT}]) as api:
        finished(api, api.post(f"/api/digest/approve/{STUB}", headers=WRITE).json()["id"])
        back = api.post(f"/api/digest/send-back/{STUB}", json={"feedback": "more"}, headers=WRITE)
        assert back.json()["status"] == "pending"
        canvas = "60-Knowledge/Software/Software map.canvas"
        refused = api.post(f"/api/graduate/{canvas}", json={}, headers=WRITE)
        assert refused.status_code == 409 and "kind" in refused.json()["detail"]
        done = api.post(f"/api/graduate/{canvas}", json={"kind": "concept"}, headers=WRITE).json()
        assert done["ok"]


def test_images_are_served_but_nothing_else(vault: MemoryVault) -> None:
    with client(vault, []) as api:
        image = api.get("/api/files/Attachments/Polars with_columns - 1.png")
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")
        assert api.get(f"/api/files/{STUB}").status_code == 404  # a note, not an image
        vault.write_bytes(PurePosixPath("99-System/Assistant/x.png"), b"\x89PNG")
        assert api.get("/api/files/99-System/Assistant/x.png").status_code == 404
        assert api.get("/api/files/Attachments/missing.png").status_code == 404


def test_one_job_per_note_at_a_time() -> None:
    async def scenario() -> list[str]:
        runner = JobRunner(EventBus())
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        def slow(progress: object) -> JobResult:
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
            return JobResult(True, "ok")

        first = runner.start("digest", "a.md", slow)
        with pytest.raises(JobBusyError):
            runner.start("digest", "a.md", slow)
        other = runner.start("digest", "b.md", lambda progress: JobResult(False, "boom"))
        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if first.state != "running" and other.state != "running":
                break
        return [first.state, other.state, other.message]

    assert asyncio.run(scenario()) == ["done", "failed", "boom"]
