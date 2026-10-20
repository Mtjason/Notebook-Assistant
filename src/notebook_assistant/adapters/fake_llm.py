"""Scripted language models for tests and dry runs: prepared answers, in order."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.ports.llm import ChatReply, ChatRequest, JsonRequest, LLMError


class ScriptedModel:
    """Answers each request with the next scripted response and records the request.

    A scripted :class:`LLMError` is raised instead of returned, to test failure handling.
    """

    def __init__(self, responses: Iterable[JsonObject | LLMError]) -> None:
        self._responses = list(responses)
        self.requests: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest) -> JsonObject:
        self.requests.append(request)
        if not self._responses:
            raise LLMError("the scripted model has no response left")
        response = self._responses.pop(0)
        if isinstance(response, LLMError):
            raise response
        return response


class ScriptedChat:
    """Answers each conversation step with the next scripted reply, streaming its text in words,
    and records the requests (so tests can check what the model was shown)."""

    def __init__(self, replies: Iterable[ChatReply | LLMError]) -> None:
        self._replies = list(replies)
        self.requests: list[ChatRequest] = []

    def converse(self, request: ChatRequest, on_text: Callable[[str], None]) -> ChatReply:
        self.requests.append(request)
        if not self._replies:
            raise LLMError("the scripted chat has no reply left")
        reply = self._replies.pop(0)
        if isinstance(reply, LLMError):
            raise reply
        for word in reply.text.split(" "):
            on_text(word + " ")
        return reply
