"""The FastAPI app the web shell talks to (``docs/design.html``, the app shell's calls).

- ``GET /api/status``: which PC, profile and vault; versions;
- ``GET /api/counts``: the nav rail's live counts;
- ``GET /api/notes`` and ``GET /api/notes/{ref}``: the note list, and one note by id or path;
- ``GET /api/events``: server-sent events from the :class:`~.events.EventBus`;
- ``/api/changesets``: the Review screen (list, detail with dry-run checks, apply selected,
  reject, undo, move or drop an atom);
- ``/api/digest``: the Digest screen (the queue; approve to digest runs as a job whose steps
  arrive as ``job`` events; graduate, send back, graduate as-is); ``/api/jobs/{id}``;
- ``/api/inbox`` and ``POST /api/capture``: the Inbox screen (what waits there; save a capture;
  processing one runs as a job that proposes a changeset for Review);
- ``/api/search``, ``/api/index/rebuild``, ``/api/sessions``: full-text search over this PC's
  index, and the Sessions screen; ``/api/sessions/view|turn/{path}``: Chat (a turn runs as a
  job whose text, tool calls and proposals arrive as ``chat`` events);
- with ``retention``: the daily session-retention job (Handbook §16.6);
- ``/api/views/tasks``, ``/api/views/incubator``, ``/api/status/{path}``,
  ``/api/ideas/promote/{path}``: the Tasks and Incubator screens;
- ``/api/sweep``: the maintenance buttons (Sweep changes, Lint, Deep pass, Archive check) run as
  jobs; each one's last report;
- ``GET /api/files/{path}``: a note's images, for the screens that show them;
- ``/``: the built web app.

Every change goes through a changeset (``app/apply.py``). Only this PC's browser may use the
service: the Host header must be ``127.0.0.1`` or ``localhost`` (no DNS rebinding), and every POST
must carry ``X-Requested-With: notebook-assistant``, which a page on another site can't send
without a CORS preflight this service never grants. The index is rebuilt per request; a few
hundred notes take well under a second (``app/index.py``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from notebook_assistant import __version__
from notebook_assistant.adapters.anthropic_llm import AnthropicModel
from notebook_assistant.adapters.email_files import read_email
from notebook_assistant.adapters.overlay_vault import OverlayVault
from notebook_assistant.adapters.sqlite_search import SqliteSearch
from notebook_assistant.api.events import Event, EventBus
from notebook_assistant.api.jobs import Job, JobBusyError, JobResult, JobRunner, Progress
from notebook_assistant.app import chat as chatting
from notebook_assistant.app import clicks, images, inbox, maintenance, review, views
from notebook_assistant.app import digest as buttons
from notebook_assistant.app import search as finder
from notebook_assistant.app import sessions as chats
from notebook_assistant.app.browse import (
    Counts,
    NoteDetail,
    NoteSummary,
    counts,
    find_note,
    note_detail,
    summaries,
)
from notebook_assistant.app.capture import CaptureError, capture_to_inbox
from notebook_assistant.app.extract import ExtractionError
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.retention import run_retention
from notebook_assistant.app.review import ChangesetDetail, ChangesetSummary, ReviewError
from notebook_assistant.config import load_config
from notebook_assistant.domain import digest
from notebook_assistant.domain import session as session_note
from notebook_assistant.domain.capture import CapturedFile
from notebook_assistant.domain.changeset import Changeset
from notebook_assistant.domain.config import ConfigError
from notebook_assistant.domain.ids import new_note_id
from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.host import Host
from notebook_assistant.machine import SEARCH_OPTIONS, load_machine_config, save_machine_config
from notebook_assistant.ports.email import EmailReader
from notebook_assistant.ports.llm import ChatModel, LanguageModel, LLMError
from notebook_assistant.ports.search import DocKind, Hit, SearchIndex
from notebook_assistant.ports.vault import VaultError, VaultStore

HEARTBEAT_SECONDS = 15.0
RETENTION_SECONDS = 24 * 60 * 60  # session retention runs once a day (Handbook §16.6)
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
class NewSession:
    title: str  # the first question, shortened
    scope: str = "all"  # all, or a Handbook §4.1 scope


@dataclass(frozen=True)
class TurnRequest:
    text: str
    pinned: list[str] = field(default_factory=list)  # notes pinned with @, by title or path


@dataclass(frozen=True)
class Transcript:
    session: chats.SessionSummary
    turns: list[session_note.Turn]
    changesets: list[str]


@dataclass(frozen=True)
class SessionRow:
    session: chats.SessionSummary
    snippet: str | None  # where the search matched, when there's a query


@dataclass(frozen=True)
class StatusRequest:
    status: str
    produced: list[str] | None = None  # titles, for a question or learn task marked done


@dataclass(frozen=True)
class PromoteRequest:
    title: str  # the new project's title


@dataclass(frozen=True)
class ChangesetRef:
    changeset: str


@dataclass(frozen=True)
class RunRequest:
    kind: str  # one of app.maintenance.KINDS


@dataclass(frozen=True)
class FeedbackRequest:
    feedback: str = ""


@dataclass(frozen=True)
class AsIsRequest:
    kind: str | None = None  # a canvas companion note's kind (Handbook §19.5)


@dataclass(frozen=True)
class DigestQueue:
    items: list[digest.DigestItem]
    canvases: list[str]  # canvases in topic folders without an owning note (Graduate as-is)
    kinds: list[str]  # the kinds a canvas's companion note may take


@dataclass(frozen=True)
class JobView:
    id: str
    kind: str
    ref: str
    state: str
    steps: list[str]
    message: str
    changeset: str | None


def job_view(job: Job) -> JobView:
    return JobView(
        job.id, job.kind, job.ref, job.state, list(job.steps), job.message, job.changeset
    )


@dataclass(frozen=True)
class InboxView:
    items: list[inbox.InboxItem]
    origins: list[str]  # Handbook §4.1 `origin` values, for the capture form
    default_origin: str


@dataclass(frozen=True)
class CaptureView:
    paths: list[str]
    changeset: str


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
    search: str  # this PC's search option (config.yaml): keyword, or an embedding model
    search_options: list[str]


@dataclass(frozen=True)
class SearchOption:
    search: str


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
    model: Callable[[], LanguageModel] = AnthropicModel,
    emails: EmailReader = read_email,
    search: SearchIndex | None = None,
    chat: Callable[[], ChatModel] = AnthropicModel,
    retention: bool = False,
    meaning: finder.Meaning | None = None,
) -> FastAPI:
    events = bus or EventBus()
    index_cache: SearchIndex = search or SqliteSearch(":memory:")
    jobs = JobRunner(events)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(daily_retention()) if retention else None
        if meaning is not None:  # the first full pass embeds the vault in the background
            embedding = asyncio.create_task(
                asyncio.to_thread(finder.refresh_meaning, store, meaning, load_rules(), wait=True)
            )
            embedding.add_done_callback(lambda t: t.cancelled() or t.exception())
        yield
        if task is not None:
            task.cancel()

    async def daily_retention() -> None:
        """The one automatic job (Handbook §16.6): propose old sessions' deletion once a day."""
        while True:
            await asyncio.to_thread(
                run_retention, store, load_rules(), now=clock(), machine=host.machine.name
            )
            events.publish(Event("counts"))
            await asyncio.sleep(RETENTION_SECONDS)

    app = FastAPI(title="notebook-assistant", version=__version__, lifespan=lifespan)
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
            search=host.machine.search,
            search_options=list(SEARCH_OPTIONS),
        )

    @app.post("/api/machine/search", dependencies=writes)
    def set_search(request: SearchOption) -> ServiceStatus:
        """Change this PC's search option in its config.yaml; it applies after a restart."""
        if request.search not in SEARCH_OPTIONS:
            raise HTTPException(status_code=400, detail=f"one of {', '.join(SEARCH_OPTIONS)}")
        save_machine_config(
            replace(
                load_machine_config(profile=host.profile, bitwarden_found=host.machine.bitwarden),
                search=request.search,
            )
        )
        return status()

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

    def click() -> clicks.Button:
        return clicks.Button(host.machine.name, clock())

    def digest_outcome(run: Callable[[], buttons.DigestOutcome]) -> Outcome:
        try:
            outcome = run()
        except buttons.DigestError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        changed()
        return Outcome(outcome.ok, outcome.state, [] if outcome.ok else [outcome.message])

    @app.get("/api/digest")
    def digest_queue() -> DigestQueue:
        rules = load_rules()
        index = VaultIndex.build(store)
        items = [item for n in index.notes.values() if (item := digest.item_of(n, rules))]
        folders = set(rules.types[buttons.KNOWLEDGE].folders)
        canvases = [
            p.as_posix()
            for p in index.files
            if p.suffix == ".canvas"
            and p.parent.as_posix() in folders
            and index.note(p.with_suffix(".md")) is None
        ]
        return DigestQueue(
            items=sorted(items, key=lambda i: i.path),
            canvases=sorted(canvases),
            kinds=buttons.companion_kinds(rules),
        )

    @app.get("/api/digest/item/{ref:path}")
    def digest_item(ref: str) -> buttons.DigestView:
        try:
            return buttons.digest_view(store, ref, load_rules())
        except buttons.DigestError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/digest/approve/{ref:path}", dependencies=writes)
    async def approve(ref: str) -> JobView:
        rules = load_rules()

        def work(progress: Progress) -> JobResult:
            outcome = buttons.approve_to_digest(
                store,
                ref,
                model(),
                config=load_config(store),
                rules=rules,
                handbook=handbook_text(),
                click=click(),
                progress=progress,
            )
            return JobResult(outcome.ok, outcome.message)

        index = VaultIndex.build(store)
        note = find_note(index, ref)
        if note is None:
            raise HTTPException(status_code=404, detail=f"no note {ref!r}")
        if note.prop(digest.DIGEST) != rules.digest_flow[0]:
            raise HTTPException(status_code=409, detail=f"{note.title} isn't waiting in the queue")
        try:
            return job_view(jobs.start("digest", note.path.as_posix(), work))
        except JobBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> JobView:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {job_id!r}")
        return job_view(job)

    @app.post("/api/digest/graduate/{ref:path}", dependencies=writes)
    def graduate(ref: str) -> Outcome:
        return digest_outcome(
            lambda: buttons.graduate(store, ref, rules=load_rules(), click=click())
        )

    @app.post("/api/digest/send-back/{ref:path}", dependencies=writes)
    def send_back(ref: str, request: FeedbackRequest) -> Outcome:
        return digest_outcome(
            lambda: buttons.send_back(
                store, ref, request.feedback, rules=load_rules(), click=click()
            )
        )

    @app.post("/api/graduate/{ref:path}", dependencies=writes)
    def graduate_as_is(ref: str, request: AsIsRequest) -> Outcome:
        return digest_outcome(
            lambda: buttons.graduate_as_is(
                store, ref, rules=load_rules(), click=click(), kind=request.kind
            )
        )

    @app.get("/api/inbox")
    def inbox_list() -> InboxView:
        rules = load_rules()
        return InboxView(
            items=inbox.inbox_items(store, rules),
            origins=sorted(rules.common_enums["origin"]),
            default_origin=rules.default_origin,
        )

    @app.post("/api/capture", dependencies=writes)
    def capture(
        origin: Annotated[str, Form()],
        text: Annotated[str, Form()] = "",
        files: Annotated[list[UploadFile] | None, File()] = None,
    ) -> CaptureView:
        captured = [CapturedFile(f.filename or "file", f.file.read()) for f in files or []]
        try:
            outcome = capture_to_inbox(
                store,
                text=text,
                files=captured,
                origin=origin,
                rules=load_rules(),
                click=click(),
                read_email=emails,
            )
        except CaptureError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        changed()
        return CaptureView(outcome.paths, outcome.changeset)

    @app.post("/api/inbox/process/{ref:path}", dependencies=writes)
    async def process(ref: str) -> JobView:
        rules = load_rules()
        note = find_note(VaultIndex.build(store), ref)
        if note is None or note.path.parts[0] != rules.inbox:
            raise HTTPException(status_code=404, detail=f"no Inbox note {ref!r}")

        def work(progress: Progress) -> JobResult:
            try:
                result = inbox.process(
                    store,
                    ref,
                    model(),
                    config=load_config(store),
                    rules=rules,
                    handbook=handbook_text(),
                    now=clock(),
                    created_by="button:process",
                    progress=progress,
                )
            except (inbox.InboxError, ExtractionError, LLMError) as exc:
                return JobResult(False, buttons.failure_message(exc))
            count = len(result.outcomes)
            return JobResult(True, f"{count} note(s) proposed", result.changeset.id)

        try:
            return job_view(jobs.start("process", note.path.as_posix(), work))
        except JobBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/search")
    def search_notes(q: str, kind: DocKind | None = None, limit: int = 20) -> list[Hit]:
        return finder.search(
            store, index_cache, load_rules(), q, limit=min(limit, 100), kind=kind, meaning=meaning
        )

    @app.post("/api/index/rebuild", dependencies=writes)
    def rebuild_index() -> finder.Refreshed:
        return finder.rebuild(store, index_cache, load_rules(), meaning)

    @app.get("/api/sessions")
    def list_sessions(q: str = "") -> list[SessionRow]:
        rules = load_rules()
        listed = chats.list_sessions(store, rules)
        if not q.strip():
            return [SessionRow(s, None) for s in listed]
        by_path = {s.path: s for s in listed}
        hits = finder.search(
            store, index_cache, rules, q, limit=50, kind="session", meaning=meaning
        )
        return [SessionRow(by_path[h.path], h.snippet) for h in hits if h.path in by_path]

    @app.post("/api/sessions", dependencies=writes)
    def new_session(request: NewSession) -> chats.SessionSummary:
        rules = load_rules()
        if request.scope != "all" and request.scope not in rules.common_enums["scope"]:
            raise HTTPException(status_code=400, detail=f"unknown scope {request.scope!r}")
        note = chatting.start_session(
            store,
            rules,
            title=request.title.strip(),
            now=clock(),
            device=host.machine.name,
            model=load_config(store).models.chat,
            scope=request.scope,
        )
        return chats.summary(note)

    @app.get("/api/sessions/view/{ref:path}")
    def view_session(ref: str) -> Transcript:
        note = VaultIndex.build(store).note(PurePosixPath(ref))
        if note is None or not finder.is_session(note.path.as_posix(), load_rules()):
            raise HTTPException(status_code=404, detail=f"no session {ref!r}")
        proposed = note.frontmatter.get_list("changesets") if note.frontmatter else []
        return Transcript(chats.summary(note), session_note.turns(note), [str(c) for c in proposed])

    @app.post("/api/sessions/turn/{ref:path}", dependencies=writes)
    async def ask(ref: str, request: TurnRequest) -> JobView:
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="nothing to ask")
        loop = asyncio.get_running_loop()

        def emit(data: JsonObject) -> None:
            loop.call_soon_threadsafe(events.publish, Event("chat", {**data, "session": ref}))

        def work(progress: Progress) -> JobResult:
            try:
                done = chatting.answer(
                    store,
                    ref,
                    request.text,
                    pinned=request.pinned,
                    chat=chat(),
                    planner=model,
                    search_index=index_cache,
                    meaning=meaning,
                    config=load_config(store),
                    rules=load_rules(),
                    handbook=handbook_text(),
                    now=clock(),
                    emit=emit,
                )
            except (chatting.ChatError, LLMError) as exc:
                emit({"type": "error", "text": str(exc)})
                return JobResult(False, str(exc))
            return JobResult(
                True,
                f"{len(done.changesets)} change(s) proposed",
                next(iter(done.changesets), None),
            )

        try:
            return job_view(jobs.start("chat", ref, work))
        except JobBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/views/tasks")
    def tasks_view() -> views.TasksView:
        return views.tasks_view(store, load_rules(), clock().date())

    @app.get("/api/views/incubator")
    def incubator_view() -> views.IncubatorView:
        return views.incubator_view(store, load_rules())

    @app.post("/api/status/{ref:path}", dependencies=writes)
    def set_status(ref: str, request: StatusRequest) -> ChangesetRef:
        try:
            cs_id = views.set_status(
                store,
                ref,
                request.status,
                rules=load_rules(),
                click=click(),
                produced=request.produced,
            )
        except views.ViewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        changed()
        return ChangesetRef(cs_id)

    @app.post("/api/ideas/promote/{ref:path}", dependencies=writes)
    def promote(ref: str, request: PromoteRequest) -> ChangesetRef:
        try:
            cs_id = views.promote(
                store, ref, request.title.strip(), rules=load_rules(), now=clock()
            )
        except views.ViewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        changed()
        return ChangesetRef(cs_id)

    reports: dict[str, maintenance.Report] = {}

    @app.get("/api/sweep")
    def sweep_reports() -> dict[str, maintenance.Report]:
        return reports

    @app.post("/api/sweep/run", dependencies=writes)
    async def sweep_run(request: RunRequest) -> JobView:
        if request.kind not in maintenance.KINDS:
            raise HTTPException(status_code=400, detail=f"unknown run {request.kind!r}")

        def work(progress: Progress) -> JobResult:
            ctx = maintenance.Context(
                store=store,
                config=load_config(store),
                rules=load_rules(),
                handbook=handbook_text(),
                now=clock(),
                machine=host.machine.name,
                model=model,
            )
            report = maintenance.run(request.kind, ctx, progress)
            reports[request.kind] = report
            first = report.changesets[0] if report.changesets else None
            return JobResult(True, report.summary, first)

        try:  # one maintenance run at a time on this PC (docs/maintenance-job.md, Two PCs)
            return job_view(jobs.start(request.kind, "maintenance", work))
        except JobBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/files/{path:path}")
    def get_file(path: str) -> Response:
        """An image the notes embed (only image types; never the assistant's state)."""
        target = PurePosixPath(path)
        media = images.media_type(target)
        if media is None or path.startswith(load_rules().state_prefix) or not store.exists(target):
            raise HTTPException(status_code=404, detail=f"no image {path!r}")
        try:
            return Response(store.read_bytes(target), media_type=media)
        except VaultError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
