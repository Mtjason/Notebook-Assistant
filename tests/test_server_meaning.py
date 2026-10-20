"""Embeddings in the service: the search option setting, and the first pass at startup."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

from fastapi.testclient import TestClient

from notebook_assistant.adapters.fake_embedder import HashEmbedder
from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.adapters.sqlite_vectors import SqliteVectors
from notebook_assistant.api.server import create_app
from notebook_assistant.app.search import Meaning
from notebook_assistant.machine import load_machine_config
from tests.test_server_digest import HOST, WRITE


def app(store: MemoryVault, meaning: Meaning | None = None) -> TestClient:
    return TestClient(
        create_app(
            store,
            HOST,
            vault_label="/v",
            web_dir=None,
            allowed_hosts=["testserver"],
            clock=lambda: datetime(2026, 10, 21, tzinfo=UTC),
            model=lambda: ScriptedModel([]),
            meaning=meaning,
        )
    )


def test_the_search_option_is_saved_to_this_pc_s_config(memory_vault: MemoryVault) -> None:
    with app(memory_vault) as api:
        changed = api.post("/api/machine/search", json={"search": "e5-small"}, headers=WRITE)
        assert changed.status_code == 200
        assert (
            api.post("/api/machine/search", json={"search": "gpt"}, headers=WRITE).status_code
            == 400
        )
    saved = load_machine_config(profile=HOST.profile, bitwarden_found=False)
    assert saved.search == "e5-small"


def test_the_vault_is_embedded_at_startup_and_searched_by_meaning(
    memory_vault: MemoryVault,
) -> None:
    memory_vault.write_text(
        PurePosixPath("60-Knowledge/Software/Lazy plans.md"), "lazy evaluation builds a plan\n"
    )
    meaning = Meaning(SqliteVectors(":memory:"), HashEmbedder())
    with app(memory_vault, meaning) as api:
        hits = api.get("/api/search", params={"q": "evaluation lazily"}).json()
        rebuilt = api.post("/api/index/rebuild", headers=WRITE).json()
    assert meaning.vectors.known("hash-test")
    assert any(h["path"].endswith("Lazy plans.md") for h in hits)
    assert rebuilt["indexed"] == rebuilt["total"]
