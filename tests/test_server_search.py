"""The search, index and sessions endpoints."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from tests.test_search_app import SESSION, SESSION_TEXT
from tests.test_server_digest import WRITE, client


def test_full_text_search_and_rebuild(memory_vault: MemoryVault) -> None:
    with client(memory_vault, []) as api:
        hits = api.get("/api/search", params={"q": "with_columns"}).json()
        assert hits and hits[0]["kind"] == "note" and "**" in hits[0]["snippet"]
        assert api.get("/api/search", params={"q": "x", "kind": "other"}).status_code == 422
        rebuilt = api.post("/api/index/rebuild", headers=WRITE).json()
        assert rebuilt["indexed"] == rebuilt["total"] > 0


def test_sessions_listed_and_searched(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(SESSION, SESSION_TEXT)
    memory_vault.write_text(PurePosixPath("00-Inbox/n.md"), "credentials in a note")
    with client(memory_vault, []) as api:
        listed = api.get("/api/sessions").json()
        assert [r["session"]["id"] for r in listed] == ["ses-1"] and listed[0]["snippet"] is None
        found = api.get("/api/sessions", params={"q": "credentials"}).json()
        assert [r["session"]["id"] for r in found] == ["ses-1"] and "**credentials**" in found[0][
            "snippet"
        ]
