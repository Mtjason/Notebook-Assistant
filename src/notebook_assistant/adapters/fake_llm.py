"""A scripted language model for tests and dry runs: returns prepared answers in order."""

from __future__ import annotations

from collections.abc import Iterable

from notebook_assistant.ports.llm import JsonObject, JsonRequest, LLMError


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
