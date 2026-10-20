"""Long work in the background (docs/architecture.md §3.5, design.html "How data moves"): a
request starts a job and returns its id at once; the work runs in a worker thread, and every
step reaches the page as a ``job`` event on the bus. One job per note at a time (per-note lock),
so a second click on a running item is refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from notebook_assistant.api.events import Event, EventBus
from notebook_assistant.domain.ids import new_ulid
from notebook_assistant.domain.jsontypes import JsonObject, JsonValue
from notebook_assistant.domain.names import name_key

Progress = Callable[[str], None]


@dataclass
class Job:
    id: str
    kind: str  # e.g. "digest"
    ref: str  # the note it works on (its vault path)
    state: str = "running"  # running | done | failed
    steps: list[str] = field(default_factory=list)
    message: str = ""

    def event(self) -> Event:
        data: JsonObject = {
            "id": self.id,
            "kind": self.kind,
            "ref": self.ref,
            "state": self.state,
            "steps": list[JsonValue](self.steps),
            "message": self.message,
        }
        return Event("job", data)


@dataclass(frozen=True)
class JobResult:
    ok: bool
    message: str


class JobBusyError(RuntimeError):
    """A job is already running on that note."""


class JobRunner:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def running_on(self, ref: str) -> Job | None:
        key = name_key(ref)
        return next(
            (j for j in self._jobs.values() if name_key(j.ref) == key and j.state == "running"),
            None,
        )

    def start(self, kind: str, ref: str, work: Callable[[Progress], JobResult]) -> Job:
        """Run ``work`` in a worker thread; must be called from the service's event loop."""
        if self.running_on(ref) is not None:
            raise JobBusyError(f"{ref} is already being worked on")
        job = Job(id=f"job-{new_ulid()}", kind=kind, ref=ref)
        self._jobs[job.id] = job
        loop = asyncio.get_running_loop()

        def step(text: str) -> None:
            loop.call_soon_threadsafe(self._step, job, text)

        async def run() -> None:
            try:
                result = await asyncio.to_thread(work, step)
            except Exception as exc:  # the job's failure is reported, never lost
                result = JobResult(False, f"{type(exc).__name__}: {exc}")
            job.state, job.message = ("done" if result.ok else "failed"), result.message
            self._bus.publish(job.event())
            self._bus.publish(Event("counts"))

        task = loop.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self._bus.publish(job.event())
        return job

    def _step(self, job: Job, text: str) -> None:
        job.steps.append(text)
        self._bus.publish(job.event())
