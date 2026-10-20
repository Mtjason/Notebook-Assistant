"""The language-model port: one request in, one JSON object out.

The planners never talk to a model API directly. They build a :class:`JsonRequest` (which model,
the stable instructions, the per-call prompt, and the JSON schema the answer must match) and get
back the parsed object. Adapters: the Claude API, and a scripted fake for tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from notebook_assistant.domain.jsontypes import JsonObject, JsonValue


class LLMError(Exception):
    """The model gave no usable answer: an API error, a refusal, or a cut-off response."""


MediaType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]


@dataclass(frozen=True)
class Image:
    """A picture the model reads with the prompt, e.g. a note's screenshot (Handbook §19.3)."""

    label: str  # how the prompt refers to it, e.g. "screenshot 1: Confusion matrix - 1.png"
    media_type: MediaType
    data: bytes


@dataclass(frozen=True)
class JsonRequest:
    """One structured request.

    ``system`` blocks are the stable prefix (instructions, the handbook): identical across calls,
    so an adapter may cache them. ``prompt`` is what changes per call.
    """

    model: str
    system: tuple[str, ...]
    prompt: str
    schema: Mapping[str, JsonValue]
    max_tokens: int
    images: tuple[Image, ...] = ()  # sent before the prompt, each followed by its label


class LanguageModel(Protocol):
    def complete_json(self, request: JsonRequest) -> JsonObject:
        """The model's answer, parsed; it matches ``request.schema``. Raises :class:`LLMError`."""
        ...
