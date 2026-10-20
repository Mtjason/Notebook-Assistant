"""The Tasks and Incubator endpoints."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from tests.test_server_digest import WRITE, client

TASK = "10-Tasks/Learn Kedro hooks.md"


def test_tasks_view_and_a_status_change(memory_vault: MemoryVault) -> None:
    with client(memory_vault, []) as api:
        view = api.get("/api/views/tasks").json()
        assert view["views"][0]["name"] == "Today"
        refused = api.post(f"/api/status/{TASK}", json={"status": "done"}, headers=WRITE)
        assert refused.status_code == 409 and "produced" in refused.json()["detail"]
        done = api.post(
            f"/api/status/{TASK}",
            json={"status": "done", "produced": ["Polars with_columns"]},
            headers=WRITE,
        )
        assert done.status_code == 200 and done.json()["changeset"]
    assert "status: done" in memory_vault.read_text(PurePosixPath(TASK))


def test_incubator_and_promote(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(
        PurePosixPath("15-Incubator/Agent.md"),
        "---\ntype: idea\nscope: personal\nstatus: shaping\ncreated: 2026-09-01\n"
        "updated: 2026-09-01\nquestion: Why?\n---\nx [[MOC - Software]]\n",
    )
    with client(memory_vault, []) as api:
        board = api.get("/api/views/incubator").json()["columns"]
        assert [c["title"] for c in board["shaping"]] == ["Agent"]
        ok = api.post(
            "/api/ideas/promote/15-Incubator/Agent.md",
            json={"title": "Agent project"},
            headers=WRITE,
        )
        assert ok.status_code == 200
        detail = api.get(f"/api/changesets/{ok.json()['changeset']}").json()
        assert detail["summary"]["status"] == "pending"
        clash = api.post(
            "/api/ideas/promote/15-Incubator/Agent.md", json={"title": "Agent"}, headers=WRITE
        )
        assert clash.status_code == 409
