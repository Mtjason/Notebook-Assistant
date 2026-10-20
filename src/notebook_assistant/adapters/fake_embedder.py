"""A deterministic embedder for tests: each word hashed into a few dimensions, so texts sharing
words are close. No model, no download."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

DIMS = 64


class HashEmbedder:
    name = "hash-test"

    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []  # (how many texts, query?)

    def embed(self, texts: Sequence[str], *, query: bool) -> list[list[float]]:
        self.calls.append((len(texts), query))
        out: list[list[float]] = []
        for text in texts:
            v = [0.0] * DIMS
            for word in re.findall(r"\w+", text.lower()):
                v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMS] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out
