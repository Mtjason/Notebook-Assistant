"""The Review screen's endpoints: list, detail, apply selected, reject, undo, move an atom."""

from __future__ import annotations

from pathlib import PurePosixPath

from fastapi.testclient import TestClient

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.api.server import CLIENT_HEADER, create_app
from notebook_assistant.domain.changeset import Changeset
from notebook_assistant.host import Host
from notebook_assistant.machine import MachineConfig
from notebook_assistant.platform.profiles import Profile
from notebook_assistant.store import changesets as cs_store
from tests.conftest import NOW
from tests.test_review import proposed

HOST = Host(MachineConfig("id-1", "test-pc"), Profile.LINUX)
WRITE = {"X-Requested-With": CLIENT_HEADER}
SOP = PurePosixPath("30-SOPs/SOP - Install uv (Linux).md")


def client(store: MemoryVault) -> TestClient:
    app = create_app(
        store, HOST, vault_label="/v", web_dir=None, allowed_hosts=["testserver"], clock=lambda: NOW
    )
    return TestClient(app)


def test_list_and_detail(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    api = client(memory_vault)
    [summary] = api.get("/api/changesets").json()
    assert summary["id"] == cs.id and summary["status"] == "pending"
    assert api.get("/api/changesets?status=history").json() == []
    detail = api.get(f"/api/changesets/{cs.id}").json()
    assert {c["name"] for c in detail["checks"]} == {"nothing lost", "base hash", "links", "rules"}
    assert len(detail["operations"]) == 4 and detail["atoms"]
    assert api.get("/api/changesets/cs-missing").status_code == 404


def test_writes_need_the_client_header(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    refused = client(memory_vault).post(f"/api/changesets/{cs.id}/reject")
    assert refused.status_code == 403 and "X-Requested-With" in refused.json()["detail"]


def test_apply_then_undo(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    api = client(memory_vault)
    before = memory_vault.read_text(SOP)
    applied = api.post(f"/api/changesets/{cs.id}/apply", json={"ops": None}, headers=WRITE).json()
    assert applied == {"ok": True, "status": "applied", "problems": []}
    assert memory_vault.read_text(SOP) != before
    again = api.post(f"/api/changesets/{cs.id}/apply", json={}, headers=WRITE)
    assert again.status_code == 409 and "not pending" in again.json()["detail"]
    reverted = api.post(f"/api/changesets/{cs.id}/revert", headers=WRITE).json()
    assert reverted["ok"] and reverted["status"] == "reverted"
    assert memory_vault.read_text(SOP) == before


def test_a_failed_apply_reports_why(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    sop = next(i for i, op in enumerate(cs.ops) if op.path == SOP)
    result = client(memory_vault).post(
        f"/api/changesets/{cs.id}/apply", json={"ops": [sop]}, headers=WRITE
    )
    body = result.json()
    assert not body["ok"] and body["status"] == "failed" and "points nowhere" in body["problems"][0]


def test_reject_and_move_an_atom(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    api = client(memory_vault)
    moved = api.post(
        f"/api/changesets/{cs.id}/atoms/zsh",
        json={"note": "SOP - Install uv (Linux)"},
        headers=WRITE,
    ).json()
    assert moved == {"ok": True, "status": "pending", "problems": []}
    refused = api.post(
        f"/api/changesets/{cs.id}/atoms/zsh", json={"note": "Bash commands"}, headers=WRITE
    )
    assert not refused.json()["ok"] and refused.json()["problems"]
    rejected = api.post(f"/api/changesets/{cs.id}/reject", headers=WRITE).json()
    assert rejected["status"] == "rejected"
    late = api.post(f"/api/changesets/{cs.id}/atoms/zsh", json={"note": None}, headers=WRITE)
    assert late.status_code == 409


def test_a_bad_config_md_stops_an_atom_move(memory_vault: MemoryVault) -> None:
    cs = proposed(memory_vault)
    memory_vault.write_text(
        PurePosixPath("99-System/Assistant/Config.md"), "---\nlimts: {a: 1}\n---\n"
    )
    result = client(memory_vault).post(
        f"/api/changesets/{cs.id}/atoms/zsh", json={"note": None}, headers=WRITE
    )
    assert result.status_code == 409 and "limts" in result.json()["detail"]


def test_changesets_without_a_capture_have_no_atoms(memory_vault: MemoryVault) -> None:
    plain = Changeset(reason="r", created_by="t", created=NOW.isoformat())
    cs_store.save(memory_vault, plain)
    assert client(memory_vault).get(f"/api/changesets/{plain.id}").json()["atoms"] == []
