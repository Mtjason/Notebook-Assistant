"""The Deep pass: duplicate candidates and missing links, found by code."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.deep_pass import (
    duplicate_candidates,
    missing_links,
    prose,
    titles_alike,
)
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.handbook import load_rules

P = PurePosixPath
RULES = load_rules()
HEAD = (
    "---\ntype: knowledge\nkind: concept\nscope: personal\nstatus: seed\n"
    'created: 2026-10-01\nupdated: 2026-10-01\ntopic: "[[MOC - Software]]"\n'
)


def add(store: MemoryVault, title: str, body: str, aliases: str = "[]") -> None:
    store.write_text(
        P(f"60-Knowledge/Software/{title}.md"), f"{HEAD}aliases: {aliases}\n---\n{body}\n"
    )


def test_duplicates_by_alias_and_by_nearly_equal_titles(memory_vault: MemoryVault) -> None:
    add(memory_vault, "Polars lazy frames", "x", aliases="[Polars LazyFrame]")
    add(memory_vault, "Polars LazyFrame", "y")
    add(memory_vault, "Polars LazyFrames", "z")
    found = {
        (d.a, d.b): d.why for d in duplicate_candidates(VaultIndex.build(memory_vault), RULES, 0.85)
    }
    base = "60-Knowledge/Software/"
    assert (
        found[(f"{base}Polars LazyFrame.md", f"{base}Polars lazy frames.md")]
        == "one's title is the other's alias"
    )
    assert (
        found[(f"{base}Polars LazyFrame.md", f"{base}Polars LazyFrames.md")]
        == "nearly the same title"
    )
    assert duplicate_candidates(VaultIndex.build(memory_vault), RULES, 0.99) == [
        d
        for d in duplicate_candidates(VaultIndex.build(memory_vault), RULES, 0.99)
        if "alias" in d.why
    ]


def test_a_title_named_but_not_linked_is_a_missing_link(memory_vault: MemoryVault) -> None:
    add(memory_vault, "Lazy evaluation", "Polars with_columns builds a plan; see the docs.")
    add(
        memory_vault,
        "Linked already",
        "Uses [[Polars with_columns]] and Polars with_columns again.",
    )
    found = missing_links(VaultIndex.build(memory_vault), RULES)
    hits = {(m.path.split("/")[-1], m.target) for m in found}
    assert ("Lazy evaluation.md", "Polars with_columns") in hits
    assert not any(p == "Linked already.md" for p, _ in hits)
    [lazy] = [m for m in found if m.path.endswith("Lazy evaluation.md")]
    assert "Polars with_columns builds" in lazy.excerpt


def test_titles_compare_only_the_words_that_differ() -> None:
    assert titles_alike("polars lazyframe", "polars lazyframes", 0.85)
    assert not titles_alike("sop - install knime (linux)", "sop - install uv (linux)", 0.85)
    assert not titles_alike("that 子句", "what 子句", 0.85)
    assert titles_alike("a b", "b a", 0.85)


def test_mentions_inside_links_and_code_are_not_prose() -> None:
    text = prose("see [[SOP - Set up zsh]], `SOP - Set up zsh`, [x](SOP.md)\n```\ncode\n```\nend")
    assert "zsh" not in text and "code" not in text and text.strip().endswith("end")
