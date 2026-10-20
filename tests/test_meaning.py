"""Embeddings: passage vectors kept current, and word and meaning hits fused."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from notebook_assistant.adapters.fake_embedder import HashEmbedder
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.adapters.onnx_embedder import MODELS, OnnxEmbedder
from notebook_assistant.adapters.sqlite_search import SqliteSearch
from notebook_assistant.adapters.sqlite_vectors import SqliteVectors
from notebook_assistant.app import search
from notebook_assistant.handbook import load_rules
from notebook_assistant.machine import SEARCH_OPTIONS
from notebook_assistant.ports.embedder import EmbedderError

P = PurePosixPath
RULES = load_rules()


def meaning() -> search.Meaning:
    return search.Meaning(SqliteVectors(":memory:"), HashEmbedder())


def test_vectors_are_kept_current_by_hash(memory_vault: MemoryVault) -> None:
    m = meaning()
    first = search.refresh_meaning(memory_vault, m, RULES)
    assert first is not None and first.indexed == first.total > 0
    again = search.refresh_meaning(memory_vault, m, RULES)
    assert again is not None and again.indexed == 0
    memory_vault.delete(P("00-Inbox/raw capture.md"))
    gone = search.refresh_meaning(memory_vault, m, RULES)
    assert gone is not None and gone.removed == 1


def test_a_refresh_already_running_is_not_waited_for(memory_vault: MemoryVault) -> None:
    m = meaning()
    with m.busy:
        assert search.refresh_meaning(memory_vault, m, RULES) is None


def test_meaning_hits_join_word_hits(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(
        P("60-Knowledge/Software/Lazy plans.md"), "lazy evaluation builds a query plan\n"
    )
    index, m = SqliteSearch(":memory:"), meaning()
    words_only = search.search(memory_vault, index, RULES, "query plan builds", limit=5)
    both = search.search(memory_vault, index, RULES, "plan builds evaluation", limit=5, meaning=m)
    assert both[0].path == "60-Knowledge/Software/Lazy plans.md"
    assert [h.path for h in words_only] == ["60-Knowledge/Software/Lazy plans.md"]
    no_words = search.search(
        memory_vault, index, RULES, "evaluation lazily planned", limit=5, meaning=m
    )
    assert any(h.path.endswith("Lazy plans.md") for h in no_words)  # found by meaning alone
    sessions = search.search(memory_vault, index, RULES, "plan", limit=5, meaning=m, kind="session")
    assert sessions == []


def test_rebuild_with_meaning_starts_from_empty(memory_vault: MemoryVault) -> None:
    index, m = SqliteSearch(":memory:"), meaning()
    done = search.rebuild(memory_vault, index, RULES, m)
    assert done.indexed == done.total and m.vectors.known(m.embedder.name)


def test_fusion_rewards_agreement() -> None:
    assert search.fused([["a", "b", "c"], ["c", "a"]], 2) == ["a", "c"]


def test_vector_store_ranks_by_best_passage(tmp_path: Path) -> None:
    store = SqliteVectors(tmp_path / "cache" / "index.sqlite")
    store.upsert("a.md", "h1", "m", [[1.0, 0.0], [0.0, 1.0]])
    store.upsert("b.md", "h2", "m", [[0.6, 0.8]])
    store.upsert("c.md", "h3", "other", [[1.0, 0.0]])
    assert [p for p, _ in store.nearest([0.0, 1.0], "m", limit=5)] == ["a.md", "b.md"]
    assert store.known("m") == {"a.md": "h1", "b.md": "h2"}
    store.remove(["a.md"])
    assert store.known("m") == {"b.md": "h2"}
    store.clear()
    assert store.known("other") == {}


def test_the_hit_lookup_gives_a_plain_snippet() -> None:
    index = SqliteSearch(":memory:")
    from notebook_assistant.ports.search import Document

    index.upsert([Document("a.md", "A", "note", "word " * 100, "h")])
    hit = index.hit("a.md")
    assert hit is not None and hit.snippet.endswith("…") and hit.score == 0.0
    assert index.hit("none.md") is None


def test_the_models_are_the_search_options() -> None:
    assert set(MODELS) == set(SEARCH_OPTIONS) - {"keyword"}
    with pytest.raises(EmbedderError, match="unknown embedding model"):
        OnnxEmbedder("tiny", Path("."))


@pytest.mark.skipif(
    not (Path.home() / ".cache" / "notebook-assistant" / "models").exists(),
    reason="the e5 model isn't downloaded on this PC",
)
def test_the_real_model_matches_across_languages() -> None:
    e = OnnxEmbedder("e5-small", Path.home() / ".cache" / "notebook-assistant" / "models")
    docs = e.embed(["How to install uv on Linux", "混淆矩陣 Precision Recall"], query=False)
    q = e.embed(["安裝 uv"], query=True)[0]
    scores = [sum(a * b for a, b in zip(q, d, strict=True)) for d in docs]
    assert scores[0] > scores[1] and e.name == "e5-small"
