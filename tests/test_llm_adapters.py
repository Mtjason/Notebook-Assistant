"""The language-model adapters: the scripted fake, and the Claude API adapter (no network)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import anthropic
import httpx2
import pytest
from anthropic.types import Message, TextBlock, Usage

from notebook_assistant.adapters.anthropic_llm import AnthropicModel
from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.ports.llm import JsonRequest, LLMError

REQUEST = JsonRequest(
    model="claude-test",
    system=("instructions", "handbook"),
    prompt="the capture",
    schema={"type": "object"},
    max_tokens=1000,
)


def message(text: str | None, stop_reason: str = "end_turn", **extra: Any) -> Message:
    content = [TextBlock(type="text", text=text)] if text is not None else []
    return Message.model_construct(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-test",
        content=content,
        stop_reason=stop_reason,
        usage=Usage(input_tokens=1, output_tokens=1),
        **extra,
    )


class FakeClient:
    """Just enough of ``anthropic.Anthropic`` for the adapter: ``messages.stream``."""

    def __init__(self, result: Message | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    @contextmanager
    def stream(self, **kwargs: Any) -> Iterator[Any]:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        final = self.result

        class Stream:
            def get_final_message(self) -> Message:
                return final

        yield Stream()


def model_with(result: Message | Exception) -> tuple[AnthropicModel, FakeClient]:
    client = FakeClient(result)
    return AnthropicModel(cast(anthropic.Anthropic, client)), client


# ----- scripted fake


def test_scripted_model_answers_in_order_and_records_requests() -> None:
    model = ScriptedModel([{"n": 1}, {"n": 2}])
    assert model.complete_json(REQUEST) == {"n": 1}
    assert model.complete_json(REQUEST) == {"n": 2}
    assert model.requests == [REQUEST, REQUEST]


def test_scripted_model_raises_scripted_errors_and_runs_out_loudly() -> None:
    model = ScriptedModel([LLMError("refused")])
    with pytest.raises(LLMError, match="refused"):
        model.complete_json(REQUEST)
    with pytest.raises(LLMError, match="no response left"):
        model.complete_json(REQUEST)


# ----- Claude API adapter


def test_request_uses_structured_output_and_caches_the_system_prefix() -> None:
    model, client = model_with(message('{"atoms": []}'))
    assert model.complete_json(REQUEST) == {"atoms": []}
    call = client.calls[0]
    assert call["model"] == "claude-test" and call["max_tokens"] == 1000
    schema_format = {"type": "json_schema", "schema": {"type": "object"}}
    assert call["output_config"] == {"format": schema_format}
    assert [block["text"] for block in call["system"]] == ["instructions", "handbook"]
    assert "cache_control" not in call["system"][0]
    assert call["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert call["messages"] == [{"role": "user", "content": "the capture"}]


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (message(None, "refusal"), "declined the request (no category)"),
        (message('{"a"', "max_tokens"), "cut off at max_tokens"),
        (message(None), "has no text"),
        (message("not json"), "not valid JSON"),
        (message("[1, 2]"), "not a JSON object"),
    ],
)
def test_unusable_answers_become_llm_errors(reply: Message, error: str) -> None:
    model, _ = model_with(reply)
    with pytest.raises(LLMError, match=re.escape(error)):
        model.complete_json(REQUEST)


def test_api_and_connection_failures_become_llm_errors() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    rate_limited = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )
    model, _ = model_with(rate_limited)
    with pytest.raises(LLMError, match="Claude API error 429"):
        model.complete_json(REQUEST)
    model, _ = model_with(anthropic.APIConnectionError(message="offline", request=request))
    with pytest.raises(LLMError, match="can't reach the Claude API"):
        model.complete_json(REQUEST)
