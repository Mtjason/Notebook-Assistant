"""Splitting notes into passages for embeddings."""

from __future__ import annotations

from notebook_assistant.domain.chunks import MAX_CHARS, chunks


def test_short_notes_are_one_passage_with_their_title() -> None:
    assert chunks("Uv", "## Install\n\ncurl it\n\nthen source") == [
        "Uv\n\n## Install\n\ncurl it\n\nthen source"
    ]
    assert chunks("Empty", "") == ["Empty"]


def test_long_notes_are_packed_by_paragraph_and_cut_when_needed() -> None:
    paragraph = "word " * 100  # 500 characters
    parts = chunks("T", "\n\n".join([paragraph] * 5) + "\n\n" + "x" * (MAX_CHARS * 2))
    assert all(len(p) <= MAX_CHARS + 3 for p in parts)
    assert len(parts) >= 4 and all(p.startswith("T\n\n") for p in parts)
    assert "".join(parts).count("word") == 500
