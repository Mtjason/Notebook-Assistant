"""The FastAPI app the web shell talks to (``docs/design.html``, the app shell's calls).

- ``GET /api/status``: which PC, profile and vault; versions;
- ``GET /api/counts``: the nav rail's live counts;
- ``GET /api/notes`` and ``GET /api/notes/{ref}``: the note list, and one note by id or path;
- ``GET /api/events``: server-sent events from the :class:`~.events.EventBus`;
- ``/``: the built web app.

Read-only for now: every change still goes through a changeset (``app/apply.py``). The index is
rebuilt per request; a few hundred notes take well under a second (``app/index.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from notebook_assistant import __version__
from notebook_assistant.api.events import EventBus
from notebook_assistant.app.browse import (
    Counts,
    NoteDetail,
    NoteSummary,
    counts,
    find_note,
    note_detail,
    summaries,
)
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.handbook import load_rules
from notebook_assistant.host import Host
from notebook_assistant.ports.vault import VaultStore

HEARTBEAT_SECONDS = 15.0
NOT_BUILT = (
    "<!doctype html><title>notebook-assistant</title><p>The service is running, but the web app"
    " isn't built. Run <code>npm run build</code> in <code>frontend/</code>, or install a"
    " release wheel.</p>"
)


def default_web_dir() -> Path | None:
    """The built web app: bundled in the release wheel, else ``frontend/dist`` of a checkout."""
    bundled = Path(str(resources.files("notebook_assistant") / "web"))
    checkout = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return next((d for d in (bundled, checkout) if (d / "index.html").is_file()), None)


@dataclass(frozen=True)
class ServiceStatus:
    version: str
    handbook_version: str
    machine: str
    machine_id: str
    profile: str
    watch: str
    vault: str


def create_app(
    store: VaultStore,
    host: Host,
    *,
    vault_label: str,
    web_dir: Path | None,
    bus: EventBus | None = None,
    heartbeat: float = HEARTBEAT_SECONDS,
) -> FastAPI:
    events = bus or EventBus()
    app = FastAPI(title="notebook-assistant", version=__version__)
    app.state.events = events

    @app.get("/api/status")
    def status() -> ServiceStatus:
        return ServiceStatus(
            version=__version__,
            handbook_version=load_rules().version,
            machine=host.machine.name,
            machine_id=host.machine.machine_id,
            profile=host.profile.value,
            watch=host.watch.value,
            vault=vault_label,
        )

    @app.get("/api/counts")
    def get_counts() -> Counts:
        return counts(VaultIndex.build(store), store)

    @app.get("/api/notes")
    def list_notes() -> list[NoteSummary]:
        return summaries(VaultIndex.build(store))

    @app.get("/api/notes/{ref:path}")
    def get_note(ref: str) -> NoteDetail:
        index = VaultIndex.build(store)
        note = find_note(index, ref)
        if note is None:
            raise HTTPException(status_code=404, detail=f"no note {ref!r}")
        return note_detail(index, note)

    @app.get("/api/events")
    def get_events() -> StreamingResponse:
        return StreamingResponse(events.stream(heartbeat), media_type="text/event-stream")

    if web_dir is not None and (web_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return NOT_BUILT

    return app
