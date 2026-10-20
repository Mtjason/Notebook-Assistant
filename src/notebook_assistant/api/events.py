"""The in-process event bus (docs/architecture.md §3.1, §3.5): jobs publish, the page listens.

Each subscriber gets its own queue, so a slow page never holds up a job. Events reach the
browser as server-sent events (:func:`sse`): a one-way stream over plain HTTP.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from notebook_assistant.domain.jsontypes import JsonObject


@dataclass(frozen=True)
class Event:
    kind: str  # e.g. "job", "counts"
    data: JsonObject = field(default_factory=dict)


def sse(event: Event) -> str:
    """One server-sent event, as the browser's EventSource reads it."""
    return f"event: {event.kind}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[Event]] = set()

    @property
    def listeners(self) -> int:
        return len(self._queues)

    def publish(self, event: Event) -> None:
        for queue in list(self._queues):
            queue.put_nowait(event)

    async def stream(self, heartbeat: float) -> AsyncGenerator[str]:
        """Events as SSE text, with a comment line every ``heartbeat`` seconds of silence so
        proxies and the browser keep the connection open."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._queues.add(queue)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield sse(event)
        finally:
            self._queues.discard(queue)
