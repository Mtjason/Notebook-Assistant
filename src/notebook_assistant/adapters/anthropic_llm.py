"""The language-model port on the Claude API (Anthropic Python SDK).

- **Structured output:** the answer is constrained to the request's JSON schema
  (``output_config.format``), so it always parses.
- **Prompt caching:** the system blocks (instructions, the handbook) are a stable prefix; the last
  one carries the cache breakpoint.
- **Streaming**, because extraction answers can be long and ``max_tokens`` is large.
- The SDK already retries rate limits, server errors and dropped connections; whatever still
  fails, and any refusal or cut-off answer, becomes :class:`~notebook_assistant.ports.llm.LLMError`.

Credentials come from the environment (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile),
never from the vault.
"""

from __future__ import annotations

import json

import anthropic
from anthropic.types import Message, TextBlockParam

from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.ports.llm import JsonRequest, LLMError


class AnthropicModel:
    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client if client is not None else anthropic.Anthropic()

    def complete_json(self, request: JsonRequest) -> JsonObject:
        system: list[TextBlockParam] = [{"type": "text", "text": text} for text in request.system]
        if system:
            system[-1]["cache_control"] = {"type": "ephemeral"}
        try:
            with self._client.messages.stream(
                model=request.model,
                max_tokens=request.max_tokens,
                system=system,
                messages=[{"role": "user", "content": request.prompt}],
                output_config={"format": {"type": "json_schema", "schema": dict(request.schema)}},
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"can't reach the Claude API: {exc}") from exc
        return _answer(message)


def _answer(message: Message) -> JsonObject:
    """The parsed JSON of a finished message, or :class:`LLMError` saying why there is none."""
    if message.stop_reason == "refusal":
        category = message.stop_details.category if message.stop_details else None
        raise LLMError(f"the model declined the request ({category or 'no category'})")
    if message.stop_reason == "max_tokens":
        raise LLMError("the answer was cut off at max_tokens (raise limits.max_tokens_per_job)")
    text = next((block.text for block in message.content if block.type == "text"), None)
    if text is None:
        raise LLMError(f"the answer has no text (stop reason {message.stop_reason})")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"the answer is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("the answer is not a JSON object")
    return data
