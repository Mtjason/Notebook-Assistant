"""The language-model port: one request in, one JSON object out.

The planners never talk to a model API directly. They build a :class:`JsonRequest` (which model,
the stable instructions, the per-call prompt, and the JSON schema the answer must match) and get
back the parsed object. Chat holds a conversation with tools instead (:class:`ChatModel`): each
step streams text and may call tools, whose results go back in the next step. Adapters: the Claude
API, and scripted fakes for tests.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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


# --------------------------------------------------------------------------- conversations


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call: its name, what it does, and its input's JSON schema."""

    name: str
    description: str
    schema: Mapping[str, JsonValue]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: JsonObject


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ChatMessage:
    """One message: a user's text (or tool results), or the model's text and tool calls."""

    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system: tuple[str, ...]  # stable prefix, cached like JsonRequest.system
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...]
    max_tokens: int


@dataclass(frozen=True)
class ChatReply:
    text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: int
    output_tokens: int


class ChatModel(Protocol):
    def converse(self, request: ChatRequest, on_text: Callable[[str], None]) -> ChatReply:
        """One model step: streams its text to ``on_text`` as it arrives, and returns the whole
        reply, with any tool calls the loop must answer. Raises :class:`LLMError`."""
        ...
