"""Search over the vault, and the session list."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.adapters.sqlite_search import SqliteSearch
from notebook_assistant.app import search, sessions
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.handbook import load_rules

P = PurePosixPath
RULES = load_rules()
SESSION = P("99-System/Assistant/Sessions/2026/10/ses-1.md")
SESSION_TEXT = (
    "---\nid: ses-1\ntitle: Kedro credentials\nstarted: 2026-10-20T09:00+08:00\ndevice: work-pc\n"
    'changesets: ["[[cs-1]]"]\n---\n## 09:00 · You\nwhere do kedro credentials go?\n'
)


def test_documents_cover_notes_and_sessions_not_other_state(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(SESSION, SESSION_TEXT)
    docs = {d.path: d for d in search.documents(VaultIndex.build(memory_vault), RULES)}
    assert (
        docs[SESSION.as_posix()].kind == "session"
        and docs[SESSION.as_posix()].title == "Kedro credentials"
    )
    assert "60-Knowledge/Software/Polars with_columns.md" in docs
    assert not any("/Changesets/" in p for p in docs)


def test_refresh_reindexes_only_what_changed(memory_vault: MemoryVault) -> None:
    index = SqliteSearch(":memory:")
    first = search.refresh(memory_vault, index, RULES)
    assert first.indexed == first.total > 0 and first.removed == 0
    assert search.refresh(memory_vault, index, RULES).indexed == 0
    memory_vault.write_text(P("00-Inbox/new.md"), "duckdb notes")
    memory_vault.delete(P("00-Inbox/raw capture.md"))
    again = search.refresh(memory_vault, index, RULES)
    assert (again.indexed, again.removed) == (1, 1)
    assert [h.path for h in search.search(memory_vault, index, RULES, "duckdb", limit=5)] == [
        "00-Inbox/new.md"
    ]
    assert search.rebuild(memory_vault, index, RULES).indexed == again.total


def test_sessions_are_listed_newest_first_and_searchable(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(SESSION, SESSION_TEXT)
    older = SESSION.with_name("ses-0.md")
    memory_vault.write_text(older, "---\nid: ses-0\nstarted: 2026-09-01T09:00+08:00\n---\nhello\n")
    listed = sessions.list_sessions(memory_vault, RULES)
    assert [s.id for s in listed] == ["ses-1", "ses-0"]
    assert listed[0].device == "work-pc" and listed[0].changesets == 1
    assert listed[1].title == "ses-0"
    hits = search.search(
        memory_vault, SqliteSearch(":memory:"), RULES, "credentials", limit=5, kind="session"
    )
    assert [h.path for h in hits] == [SESSION.as_posix()]
