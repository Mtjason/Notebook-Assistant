"""The maintenance endpoints: run a button as a job, read its report."""

from __future__ import annotations

from notebook_assistant.adapters.memory_vault import MemoryVault
from tests.test_server_digest import WRITE, client, finished


def test_lint_runs_as_a_job_and_leaves_its_report(memory_vault: MemoryVault) -> None:
    with client(memory_vault, []) as api:
        started = api.post("/api/sweep/run", json={"kind": "lint"}, headers=WRITE)
        assert started.status_code == 200 and started.json()["ref"] == "maintenance"
        job = finished(api, started.json()["id"])
        assert job["state"] == "done" and job["changeset"]
        report = api.get("/api/sweep").json()["lint"]
    assert report["summary"].startswith("13 notes") and report["changesets"] == [job["changeset"]]


def test_an_unknown_run_or_a_foreign_post_is_refused(memory_vault: MemoryVault) -> None:
    with client(memory_vault, []) as api:
        assert api.post("/api/sweep/run", json={"kind": "all"}, headers=WRITE).status_code == 400
        assert api.post("/api/sweep/run", json={"kind": "lint"}).status_code == 403
        assert api.get("/api/sweep").json() == {}
