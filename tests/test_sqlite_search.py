"""The SQLite FTS5 search index: Chinese and English by word, ranked, with snippets."""

from __future__ import annotations

from pathlib import Path

from notebook_assistant.adapters.sqlite_search import SqliteSearch, snippet, tokens
from notebook_assistant.ports.search import Document

DOCS = [
    Document(
        "a.md", "Polars LazyFrame", "note", "Polars LazyFrame 延遲計算 builds a query plan", "h1"
    ),
    Document("b.md", "資料分析流程", "note", "資料分析 的 流程: load, clean, profile", "h2"),
    Document(
        "99-System/Assistant/Sessions/s.md", "Chat", "session", "we talked about polars", "h3"
    ),
]


def test_tokens_split_chinese_into_words_and_drop_punctuation() -> None:
    assert tokens("資料分析流程？Polars!") == ["資料", "分析", "流程", "polars"]


def test_search_ranks_by_word_in_both_languages(tmp_path: Path) -> None:
    index = SqliteSearch(tmp_path / "cache" / "index.sqlite")
    index.upsert(DOCS)
    assert [h.path for h in index.search("分析", limit=5)] == ["b.md"]
    assert {h.path for h in index.search("polars", limit=5)} == {
        "a.md",
        "99-System/Assistant/Sessions/s.md",
    }
    assert [h.path for h in index.search("polars", limit=5, kind="session")] == [
        "99-System/Assistant/Sessions/s.md"
    ]
    assert index.search("polars plan", limit=5)[0].path == "a.md"  # every word must match
    assert index.search("？？", limit=5) == []
    assert index.known() == {"a.md": "h1", "b.md": "h2", "99-System/Assistant/Sessions/s.md": "h3"}


def test_upsert_replaces_and_remove_and_clear_forget(tmp_path: Path) -> None:
    index = SqliteSearch(":memory:")
    index.upsert(DOCS)
    index.upsert([Document("a.md", "Polars LazyFrame", "note", "now about duckdb", "h9")])
    assert index.search("polars", limit=5, kind="note") == []
    assert index.known()["a.md"] == "h9"
    index.remove(["a.md"])
    assert "a.md" not in index.known()
    index.clear()
    assert index.known() == {}


def test_snippets_bold_the_matches_around_the_first_one() -> None:
    text = "intro " * 60 + "the Polars plan is lazy " + "outro " * 60
    piece = snippet(text, "polars lazy")
    assert piece.startswith("…") and piece.endswith("…")
    assert "**Polars**" in piece and "**lazy**" in piece
    assert snippet("short polars", "polars") == "short **polars**"


def test_identifiers_split_on_underscores_still_match() -> None:
    assert tokens("with_columns") == ["with", "columns"]
    index = SqliteSearch(":memory:")
    index.upsert([Document("p.md", "Polars", "note", "use with_columns to add", "h")])
    assert [h.path for h in index.search("with_columns", limit=5)] == ["p.md"]
