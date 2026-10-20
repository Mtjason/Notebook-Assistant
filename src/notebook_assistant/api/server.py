"""The FastAPI app the web shell talks to (``docs/design.html``, the app shell's calls).

- ``GET /api/status``: which PC, profile and vault; versions;
- ``GET /api/counts``: the nav rail's live counts;
- ``GET /api/notes`` and ``GET /api/notes/{ref}``: the note list, and one note by id or path;
- ``GET /api/events``: server-sent events from the :class:`~.events.EventBus`;
- ``/api/changesets``: the Review screen (list, detail with dry-run checks, apply selected,
  reject, undo, move or drop an atom);
- ``/``: the built web app.

Every change goes through a changeset (``app/apply.py``). Only this PC's browser may use the
service: the Host header must be ``127.0.0.1`` or ``localhost`` (no DNS rebinding), and every POST
must carry ``X-Requested-With: notebook-assistant``, which a page on another site can't send
without a CORS preflight this service never grants. The index is rebuilt per request; a few
hundred notes take well under a second (``app/index.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from notebook_assistant import __version__
from notebook_assistant.adapters.overlay_vault import OverlayVault
from notebook_assistant.api.events import Event, EventBus
from notebook_assistant.app import review
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
from notebook_assistant.app.review import ChangesetDetail, ChangesetSummary, ReviewError
from notebook_assistant.config import load_config
from notebook_assistant.domain.changeset import Changeset
from notebook_assistant.domain.config import ConfigError
from notebook_assistant.domain.ids import new_note_id
from notebook_assistant.handbook import load_rules
from notebook_assistant.host import Host
from notebook_assistant.ports.vault import VaultStore

HEARTBEAT_SECONDS = 15.0
LOCAL_HOSTS = ("127.0.0.1", "localhost")
CLIENT_HEADER = "notebook-assistant"  # the X-Requested-With value the web app sends on POSTs
NOT_BUILT = (
    "<!doctype html><title>notebook-assistant</title><p>The service is running, but the web app"
    " isn't built. Run <code>npm run build</code> in <code>frontend/</code>, or install a"
    " release wheel.</p>"
)


def default_web_dir() -> Path | None:
    """The built web app inside the package (``npm run build`` in ``frontend/`` puts it there,
    and the release wheel ships it); None when it isn't built."""
    web = Path(str(resources.files("notebook_assistant") / "web"))
    return web if (web / "index.html").is_file() else None


@dataclass(frozen=True)
class ApplyRequest:
    ops: list[int] | None = None  # indices of the operations to apply; None applies all


@dataclass(frozen=True)
class MoveRequest:
    note: str | None = None  # the planned note to move the atom to; None drops it


@dataclass(frozen=True)
class Outcome:
    ok: bool
    status: str  # the changeset's status afterwards
    problems: list[str]


def require_client(x_requested_with: str | None = Header(default=None)) -> None:
    """Refuse requests that didn't come from the web app (no cross-site POSTs)."""
    if x_requested_with != CLIENT_HEADER:
        raise HTTPException(status_code=403, detail=f"missing X-Requested-With: {CLIENT_HEADER}")


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
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> FastAPI:
    events = bus or EventBus()
    app = FastAPI(title="notebook-assistant", version=__version__)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    app.state.events = events
    writes = [Depends(require_client)]

    def load_changeset(cs_id: str) -> Changeset:
        try:
            return review.load(store, cs_id)
        except ReviewError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def changed() -> None:
        events.publish(Event("counts"))

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

    @app.get("/api/changesets")
    def list_changesets(status: str = "pending") -> list[ChangesetSummary]:
        return review.list_changesets(store, pending=status == "pending")

    @app.get("/api/changesets/{cs_id}")
    def get_changeset(cs_id: str) -> ChangesetDetail:
        return review.changeset_detail(
            store, load_changeset(cs_id), now=clock(), sandbox=OverlayVault
        )

    @app.post("/api/changesets/{cs_id}/apply", dependencies=writes)
    def apply(cs_id: str, request: ApplyRequest) -> Outcome:
        cs = load_changeset(cs_id)
        try:
            result = review.apply_selected(
                store, cs, request.ops, now=clock(), machine=host.machine.name
            )
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        changed()
        problems = [result.error] if result.error else []
        return Outcome(result.ok, result.changeset.status.value, problems)

    @app.post("/api/changesets/{cs_id}/reject", dependencies=writes)
    def reject(cs_id: str) -> Outcome:
        cs = load_changeset(cs_id)
        try:
            review.reject(store, cs)
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        changed()
        return Outcome(True, cs.status.value, [])

    @app.post("/api/changesets/{cs_id}/revert", dependencies=writes)
    def revert(cs_id: str) -> Outcome:
        result = review.undo(store, load_changeset(cs_id), now=clock())
        changed()
        problems = [result.error] if result.error else []
        return Outcome(result.ok, result.changeset.status.value, problems)

    @app.post("/api/changesets/{cs_id}/atoms/{atom_id}", dependencies=writes)
    def move(cs_id: str, atom_id: str, request: MoveRequest) -> Outcome:
        cs = load_changeset(cs_id)
        try:
            config = load_config(store)
            problems = review.move_atom_in(
                store, cs, atom_id, request.note, config=config, now=clock(), new_id=new_note_id
            )
        except (ReviewError, ConfigError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Outcome(not problems, cs.status.value, problems)

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
