"""The local service: every endpoint the shell calls, the event stream, and the web app mount."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from notebook_assistant import __version__
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.api.events import Event, EventBus, sse
from notebook_assistant.api.server import NOT_BUILT, create_app
from notebook_assistant.handbook import load_rules
from notebook_assistant.host import Host
from notebook_assistant.machine import MachineConfig
from notebook_assistant.platform.profiles import Profile

HOST = Host(MachineConfig("id-1", "test-pc"), Profile.WSL_DRVFS)


def client(store: MemoryVault, web_dir: Path | None = None) -> TestClient:
    app = create_app(
        store, HOST, vault_label="/vault", web_dir=web_dir, allowed_hosts=["testserver"]
    )
    return TestClient(app)


def test_status_names_this_pc_and_the_versions(memory_vault: MemoryVault) -> None:
    body = client(memory_vault).get("/api/status").json()
    assert body == {
        "version": __version__,
        "handbook_version": load_rules().version,
        "machine": "test-pc",
        "machine_id": "id-1",
        "profile": "wsl-drvfs",
        "watch": "polling",
        "vault": "/vault",
        "search": "keyword",
        "search_options": ["keyword", "e5-small", "bge-m3"],
    }


def test_counts_and_notes(memory_vault: MemoryVault) -> None:
    api = client(memory_vault)
    assert set(api.get("/api/counts").json()) == {"inbox", "digest", "review"}
    notes = api.get("/api/notes").json()
    assert {"path", "title", "type", "aliases"} == set(notes[0])
    one = api.get("/api/notes/30-SOPs/SOP - Install uv (Linux).md").json()
    assert one["title"] == "SOP - Install uv (Linux)" and one["props"]["type"] == "sop"
    assert one["body"].startswith("## Steps")
    missing = api.get("/api/notes/nowhere.md")
    assert missing.status_code == 404 and "nowhere.md" in missing.json()["detail"]


def test_the_web_app_is_served_when_built(memory_vault: MemoryVault, tmp_path: Path) -> None:
    assert client(memory_vault).get("/").text == NOT_BUILT
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")
    page = client(memory_vault, tmp_path).get("/")
    assert page.status_code == 200 and "<title>shell</title>" in page.text


def test_events_endpoint_streams(memory_vault: MemoryVault) -> None:
    with client(memory_vault).stream("GET", "/api/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert next(response.iter_text()) == ": connected\n\n"


def test_sse_format() -> None:
    assert sse(Event("job", {"step": "讀取", "n": 1})) == (
        'event: job\ndata: {"step": "讀取", "n": 1}\n\n'
    )


def test_the_bus_fans_out_heartbeats_and_unsubscribes() -> None:
    async def scenario() -> list[str]:
        bus = EventBus()
        stream = bus.stream(heartbeat=0.01)
        received = [await anext(stream)]  # connected
        assert bus.listeners == 1
        received.append(await anext(stream))  # silence → heartbeat
        bus.publish(Event("counts", {"review": 1}))
        received.append(await anext(stream))
        await stream.aclose()
        assert bus.listeners == 0
        bus.publish(Event("ignored"))  # nobody listening: dropped, no error
        return received

    assert asyncio.run(scenario()) == [
        ": connected\n\n",
        ": heartbeat\n\n",
        'event: counts\ndata: {"review": 1}\n\n',
    ]


def test_only_this_pcs_host_names_are_served(memory_vault: MemoryVault) -> None:
    """A page on another site can't reach the service through DNS rebinding."""
    api = TestClient(create_app(memory_vault, HOST, vault_label="/v", web_dir=None))
    assert api.get("/api/status").status_code == 400  # Host: testserver
    assert api.get("/api/status", headers={"host": "127.0.0.1:8765"}).status_code == 200
    assert api.get("/api/status", headers={"host": "localhost"}).status_code == 200
    assert api.get("/api/status", headers={"host": "evil.example"}).status_code == 400
