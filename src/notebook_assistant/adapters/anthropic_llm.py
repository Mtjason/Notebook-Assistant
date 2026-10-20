"""The language-model port on the Claude API (Anthropic Python SDK).

- **Structured output:** the answer is constrained to the request's JSON schema
  (``output_config.format``), so it always parses.
- **Prompt caching:** the system blocks (instructions, the handbook) are a stable prefix; the last
  one carries the cache breakpoint.
- **Streaming**, because extraction answers can be long and ``max_tokens`` is large; in a chat
  the text reaches the page word by word (:meth:`AnthropicModel.converse`, with tools).
- The SDK already retries rate limits, server errors and dropped connections; whatever still
  fails, and any refusal or cut-off answer, becomes :class:`~notebook_assistant.ports.llm.LLMError`.

Credentials come from the environment (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile),
never from the vault.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import anthropic
from anthropic.types import (
    Base64ImageSourceParam,
    ContentBlockParam,
    ImageBlockParam,
    Message,
    MessageParam,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)

from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.ports.llm import (
    ChatMessage,
    ChatReply,
    ChatRequest,
    JsonRequest,
    LLMError,
    ToolCall,
)


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
                messages=[{"role": "user", "content": _content(request)}],
                output_config={"format": {"type": "json_schema", "schema": dict(request.schema)}},
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"can't reach the Claude API: {exc}") from exc
        return _answer(message)

    def converse(self, request: ChatRequest, on_text: Callable[[str], None]) -> ChatReply:
        system: list[TextBlockParam] = [{"type": "text", "text": text} for text in request.system]
        if system:
            system[-1]["cache_control"] = {"type": "ephemeral"}
        tools: list[ToolParam] = [
            {"name": t.name, "description": t.description, "input_schema": dict(t.schema)}
            for t in request.tools
        ]
        try:
            with self._client.messages.stream(
                model=request.model,
                max_tokens=request.max_tokens,
                system=system,
                tools=tools,
                messages=[_message(m) for m in request.messages],
            ) as stream:
                for text in stream.text_stream:
                    on_text(text)
                message = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"can't reach the Claude API: {exc}") from exc
        if message.stop_reason == "refusal":
            raise LLMError("the model declined the request")
        calls = tuple(
            ToolCall(b.id, b.name, _json_object(b.input))
            for b in message.content
            if b.type == "tool_use"
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        usage = message.usage
        return ChatReply(text, calls, usage.input_tokens, usage.output_tokens)

    def count_models(self) -> int:
        """How many models these credentials can use: free, and proves both reach and login."""
        try:
            return sum(1 for _ in self._client.models.list())
        except anthropic.AuthenticationError as exc:
            raise LLMError("not logged in: run `ant auth login` or set ANTHROPIC_API_KEY") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"can't reach the Claude API: {exc}") from exc


def _json_object(value: object) -> JsonObject:
    """A tool call's input as JSON data (the SDK types it loosely)."""
    data = json.loads(json.dumps(value))
    return data if isinstance(data, dict) else {}


def _message(message: ChatMessage) -> MessageParam:
    """A conversation message in the API's shape: text first, then tool calls or results."""
    blocks: list[ContentBlockParam] = []
    if message.text:
        blocks.append({"type": "text", "text": message.text})
    for call in message.tool_calls:
        use: ToolUseBlockParam = {
            "type": "tool_use",
            "id": call.id,
            "name": call.name,
            "input": dict[str, object](call.input),
        }
        blocks.append(use)
    for result in message.tool_results:
        answer: ToolResultBlockParam = {
            "type": "tool_result",
            "tool_use_id": result.call_id,
            "content": result.content,
            "is_error": result.is_error,
        }
        blocks.append(answer)
    return {"role": message.role, "content": blocks}


def _content(request: JsonRequest) -> str | list[ContentBlockParam]:
    """The user turn: each image with its label, then the prompt (plain text when no images)."""
    if not request.images:
        return request.prompt
    blocks: list[ContentBlockParam] = []
    for image in request.images:
        source: Base64ImageSourceParam = {
            "type": "base64",
            "media_type": image.media_type,
            "data": base64.standard_b64encode(image.data).decode("ascii"),
        }
        block: ImageBlockParam = {"type": "image", "source": source}
        blocks.append(block)
        blocks.append({"type": "text", "text": image.label})
    blocks.append({"type": "text", "text": request.prompt})
    return blocks


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
