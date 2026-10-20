"""The Digest buttons (Handbook §19.2, §19.5), as use cases.

Each click is your approval, so each button builds a changeset of the notes it changes and
applies it at once (``app/apply.py`` still checks base hashes, links and rules); the record is
saved, so the step shows in Review's history and can be undone there.

- :func:`approve_to_digest`: marks the note approved on this PC, reads it and its screenshots,
  drafts (a knowledge note in place; a learn task through the extraction planner, as a new
  note), checks, and writes the draft. On any failure the note goes back to the queue with
  ``digest_error``; if you edit the note meanwhile, the draft is discarded (§19.2).
- :func:`graduate`, :func:`send_back`, :func:`graduate_as_is` (a canvas without an owning note
  gets a companion note, whose ``kind`` you choose in the confirmation).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app import canvas
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.browse import find_note
from notebook_assistant.app.extract import Capture, ExtractionError, plan_extraction
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain import digest, preserve
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.frontmatter import Frontmatter
from notebook_assistant.domain.ids import content_hash, new_note_id
from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.llm import Image, JsonRequest, LanguageModel, LLMError, MediaType
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store

# Vocabulary (Handbook §3, §4.2): what a learn task and a knowledge note are called.
TASK, LEARN, KNOWLEDGE, MOC = "task", "learn", "knowledge", "moc"

IMAGE_TYPES: dict[str, MediaType] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
DRAFT_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {"body": {"type": "string", "description": "the note's new body"}},
    "required": ["body"],
    "additionalProperties": False,
}
DRAFT_INSTRUCTIONS = """\
You digest one note of an Obsidian vault into solid knowledge, following the Vault Handbook
below (§19.3 says what a draft looks like). Return the note's new body only:
- Rewrite it into the body skeleton its type needs (Handbook §8.1); start at `##`, no H1.
- Keep every piece of information the note, its screenshots and its linked notes give you.
- Read each screenshot and describe what it shows in text; cite it after each claim taken from
  it, as "(screenshot N)".
- Anything the note, its screenshots or its linked notes don't support goes in a box that starts
  with the line `{unverified}`. Don't fill gaps with confident guesses.
- Don't repeat the original note: it's kept below your draft automatically.
"""

Progress = Callable[[str], None]
Change = tuple[Note | None, Note]  # (before, after); before is None for a new note


class DigestError(ValueError):
    """The button doesn't apply to this note (not in the right state, not found, not placed)."""


@dataclass(frozen=True)
class DigestOutcome:
    ok: bool
    state: str  # the note's digest state afterwards
    message: str
    changesets: list[str]  # ids of the changesets recorded, in order


@dataclass(frozen=True)
class Button:
    """Who clicks, where, when: what every changeset a button makes records."""

    machine: str
    now: datetime

    @property
    def today(self) -> str:
        return self.now.date().isoformat()


def _note(index: VaultIndex, ref: str) -> Note:
    note = find_note(index, ref)
    if note is None:
        raise DigestError(f"no note {ref!r}")
    return note


def _state(note: Note) -> str | None:
    value = note.prop(digest.DIGEST)
    return value if isinstance(value, str) else None


def _apply_and_record(store: VaultStore, cs: Changeset, click: Button) -> str:
    cs.machine = click.machine
    cs_store.save(store, cs)
    result = apply_changeset(store, cs, now=click.now, machine=click.machine)
    cs_store.save(store, result.changeset, with_diff=False)
    if not result.ok:
        raise DigestError(result.error or "apply failed")
    return cs.id


def _write(index: VaultIndex, before: Note, after: Note, label: str) -> Operation:
    stored = index.text(before.path)
    if stored is None:
        raise DigestError(f"{before.path} isn't in the vault")
    return Operation(
        "write", before.path, content=after.render(), base_hash=content_hash(stored), label=label
    )


def _commit(
    store: VaultStore,
    index: VaultIndex,
    changes: list[Change],
    *,
    reason: str,
    button: str,
    click: Button,
) -> str:
    """Apply the changes as one changeset and save its record; :class:`DigestError` if apply
    refuses. Returns the changeset's id."""
    ops = [
        Operation("create", after.path, content=after.render(), label="new note")
        if before is None
        else _write(index, before, after, button)
        for before, after in changes
    ]
    created = click.now.isoformat(timespec="seconds")
    cs = Changeset(reason=reason, created_by=f"button:{button}", created=created, ops=ops)
    return _apply_and_record(store, cs, click)


def _titled(index: VaultIndex, title: str) -> Note | None:
    key = name_key(title.split("/")[-1].removesuffix(".md"))
    return next((n for n in index.notes.values() if name_key(n.title) == key), None)


def _moc_change(index: VaultIndex, note: Note, today: str) -> list[Change]:
    """The note's topic MOC, linking it, if it doesn't yet (§19.2: linked from its MOC)."""
    topic = note.prop("topic")
    links = find_links(str(topic)) if topic else []
    moc = _titled(index, links[0].target) if links else None
    linked = digest.moc_linking(moc, note.title, today=today) if moc else None
    return [(moc, linked)] if moc is not None and linked is not None else []


def screenshots(store: VaultStore, index: VaultIndex, note: Note) -> list[Image]:
    """The images the note embeds, in order, labelled "screenshot N: <file>" (§19.3)."""
    images: list[Image] = []
    for link in find_links(note.body):
        target = index.resolver.resolve(link, note.path) if link.embed else None
        media = IMAGE_TYPES.get(target.suffix.lower()) if target else None
        if target is not None and media is not None:
            label = f"screenshot {len(images) + 1}: {target.name}"
            images.append(Image(label, media, store.read_bytes(target)))
    return images


def draft_request(
    note: Note, images: list[Image], *, config: Config, rules: Rules, handbook: str
) -> JsonRequest:
    feedback = note.prop(digest.FEEDBACK)
    parts = [f"## The note: {note.path.as_posix()}\n\n{note.render()}"]
    if feedback:
        parts.append(f"## Your earlier draft was sent back with this feedback\n\n{feedback}")
    return JsonRequest(
        model=config.models.digest,
        system=(DRAFT_INSTRUCTIONS.format(unverified=rules.digestion.unverified_box), handbook),
        prompt="\n\n".join(parts),
        schema=DRAFT_SCHEMA,
        max_tokens=config.limits.max_tokens_per_job,
        images=tuple(images),
    )


def is_learn_task(note: Note) -> bool:
    """A learn task's draft is a new note; any other note is drafted in place (§19.3)."""
    return note.type == TASK and note.prop("kind") == LEARN


def approve_to_digest(
    store: VaultStore,
    ref: str,
    model: LanguageModel,
    *,
    config: Config,
    rules: Rules,
    handbook: str,
    click: Button,
    progress: Progress = lambda step: None,
) -> DigestOutcome:
    """§19.2 step 2, right away: approve, read, draft, check, write the draft."""
    index = VaultIndex.build(store)
    note = _note(index, ref)
    if _state(note) != rules.digest_flow[0]:
        raise DigestError(f"{note.title} isn't waiting in the digest queue")
    progress(f"Approved on {click.machine}")
    started = click.now.isoformat(timespec="seconds")
    approved = digest.approved(
        note, rules, runner=click.machine, started=started, today=click.today
    )
    recorded = [
        _commit(
            store,
            index,
            [(note, approved)],
            reason=f"Approve to digest {note.title}",
            button="approve-to-digest",
            click=click,
        )
    ]
    try:
        index = VaultIndex.build(store)
        current = _note(index, ref)
        images = screenshots(store, index, current)
        progress(f"Reading the note and {len(images)} screenshot(s)")
        if is_learn_task(current):
            progress("Planning the knowledge note")
            recorded.append(
                _draft_learn_task(store, index, current, model, config, rules, handbook, click)
            )
        else:
            progress("Drafting")
            recorded.append(
                _draft_in_place(
                    store, index, current, images, model, config, rules, handbook, click
                )
            )
    except (LLMError, ExtractionError, DigestError) as exc:
        message = failure_message(exc)
        index = VaultIndex.build(store)
        latest = _note(index, ref)
        back = digest.failed(latest, rules, error=message, today=click.today)
        recorded.append(
            _commit(
                store,
                index,
                [(latest, back)],
                reason=f"Digest failed: {note.title}",
                button="digest-failed",
                click=click,
            )
        )
        return DigestOutcome(False, rules.digest_flow[0], message, recorded)
    progress("Draft ready")
    return DigestOutcome(True, rules.digest_flow[2], "draft ready to review", recorded)


def failure_message(exc: Exception) -> str:
    """One readable line; an edit made while digesting is named as such (§19.2)."""
    text = str(exc)
    if "changed since the proposal" in text:
        return "the note changed while it was being digested; the draft was discarded"
    return text.splitlines()[0] if text else type(exc).__name__


def _draft_in_place(
    store: VaultStore,
    index: VaultIndex,
    note: Note,
    images: list[Image],
    model: LanguageModel,
    config: Config,
    rules: Rules,
    handbook: str,
    click: Button,
) -> str:
    request = draft_request(note, images, config=config, rules=rules, handbook=handbook)
    body = model.complete_json(request).get("body")
    if not isinstance(body, str) or not body.strip():
        raise DigestError("the model returned no draft")
    drafted = digest.drafted_in_place(note, body, rules, today=click.today)
    similarity = config.checks.preservation_similarity
    report = preserve.check(note.body, [drafted.body], similarity=similarity)
    if not report.ok:
        raise DigestError(f"the draft lost content: {report.summary()}")
    return _commit(
        store,
        index,
        [(note, drafted)],
        reason=f"Draft {note.title}",
        button="digest-draft",
        click=click,
    )


def _draft_learn_task(
    store: VaultStore,
    index: VaultIndex,
    task: Note,
    model: LanguageModel,
    config: Config,
    rules: Rules,
    handbook: str,
    click: Button,
) -> str:
    """A learn task's raw capture becomes a new knowledge note (§19.3), through the planner;
    the task is linked to it as ``digest_draft`` in the same changeset."""
    origin = str(task.prop("origin") or rules.default_origin)
    capture = Capture(task.body, origin, task.title)
    result = plan_extraction(
        capture,
        index,
        model,
        config=config,
        handbook=handbook,
        now=click.now,
        created_by="button:digest-draft",
        new_id=new_note_id,
    )
    drafts = [o.after for o in result.outcomes.values() if o.after.type == KNOWLEDGE]
    if not drafts:
        raise DigestError("the plan made no knowledge note for the task")
    cs = result.changeset
    key = name_key(task.path.as_posix())
    planned = next((op for op in cs.ops if name_key(op.path.as_posix()) == key), None)
    base = Note.parse(task.path, planned.content) if planned and planned.content else task
    linked = digest.draft_linked(base, drafts[0].title, rules, today=click.today)
    link_op = _write(index, task, linked, "link the draft")
    cs.ops = [link_op if op is planned else op for op in cs.ops]
    if planned is None:
        cs.ops.append(link_op)
    return _apply_and_record(store, cs, click)


def graduate(store: VaultStore, ref: str, *, rules: Rules, click: Button) -> DigestOutcome:
    """§19.2 step 4a: solid knowledge; a learn task is closed with ``produced``."""
    index = VaultIndex.build(store)
    note = _note(index, ref)
    if _state(note) != rules.digest_flow[2]:
        raise DigestError(f"{note.title} has no draft ready to graduate")
    draft_link = note.prop(digest.DRAFT)
    changes: list[Change]
    if draft_link:
        links = find_links(str(draft_link))
        draft = _titled(index, links[0].target) if links else None
        if draft is None:
            raise DigestError(f"{note.title}'s draft {draft_link} isn't in the vault")
        done = digest.graduated(draft, rules, today=click.today)
        closed = digest.task_closed(note, draft.title, rules, today=click.today)
        changes = [(draft, done), (note, closed), *_moc_change(index, done, click.today)]
    else:
        done = digest.graduated(note, rules, today=click.today)
        changes = [(note, done), *_moc_change(index, done, click.today)]
    cs = _commit(
        store, index, changes, reason=f"Graduate {note.title}", button="graduate", click=click
    )
    return DigestOutcome(True, rules.digest_flow[-1], "graduated", [cs])


def send_back(
    store: VaultStore, ref: str, feedback: str, *, rules: Rules, click: Button
) -> DigestOutcome:
    """§19.2 step 4b: back to the queue with your feedback for the next draft."""
    index = VaultIndex.build(store)
    note = _note(index, ref)
    if _state(note) != rules.digest_flow[2]:
        raise DigestError(f"{note.title} has no draft to send back")
    back = digest.sent_back(note, feedback, rules, today=click.today)
    cs = _commit(
        store,
        index,
        [(note, back)],
        reason=f"Send back {note.title}",
        button="send-back",
        click=click,
    )
    return DigestOutcome(True, rules.digest_flow[0], "sent back", [cs])


def graduate_as_is(
    store: VaultStore, ref: str, *, rules: Rules, click: Button, kind: str | None = None
) -> DigestOutcome:
    """§19.5: finished as it is. A canvas gets a companion note holding its state; ``kind`` is
    that note's kind, chosen in the confirmation (it can't be guessed, Handbook §4)."""
    index = VaultIndex.build(store)
    if PurePosixPath(ref).suffix == ".canvas":
        return _graduate_canvas(
            store, index, PurePosixPath(ref), rules=rules, click=click, kind=kind
        )
    note = _note(index, ref)
    if note.type is None or (note.type == KNOWLEDGE and not note.prop("topic")):
        raise DigestError(f"{note.title} isn't placed yet (no type or topic); place it first")
    done = digest.graduated_as_is(note, rules, today=click.today)
    changes = [(note, done), *_moc_change(index, done, click.today)]
    cs = _commit(
        store,
        index,
        changes,
        reason=f"Graduate {note.title} as is",
        button="graduate-as-is",
        click=click,
    )
    return DigestOutcome(True, rules.digest_flow[-1], "graduated as is", [cs])


def companion_kinds(rules: Rules) -> list[str]:
    """The kinds a canvas's companion note may take (Handbook §4.2, knowledge)."""
    return sorted(rules.types[KNOWLEDGE].enums.get("kind", frozenset()))


def _graduate_canvas(
    store: VaultStore,
    index: VaultIndex,
    path: PurePosixPath,
    *,
    rules: Rules,
    click: Button,
    kind: str | None,
) -> DigestOutcome:
    """The canvas's owning note graduates; without one, a companion note is created next to it
    with a summary built only from the canvas's own text cards (§19.5, §10)."""
    stored = index.path_of(path)
    text = index.text(path) if stored else None
    if stored is None or text is None:
        raise DigestError(f"no canvas {path}")
    owner = index.note(stored.with_suffix(".md"))
    if owner is not None:
        return graduate_as_is(store, owner.path.as_posix(), rules=rules, click=click)
    moc = next(
        (n for n in index.notes.values() if n.type == MOC and n.path.parent == stored.parent), None
    )
    if moc is None:
        raise DigestError(f"{stored.name} isn't in a topic folder with a MOC; place it first")
    if kind not in companion_kinds(rules):
        raise DigestError(f"choose the companion note's kind: {', '.join(companion_kinds(rules))}")
    cards = [card.strip().split("\n")[0] for card in canvas.text_nodes(canvas.load(text))]
    shown = [c for c in cards if c][:30]
    summary = f"Cards: {' · '.join(shown)}" if shown else "A canvas without text cards."
    props = {
        "id": new_note_id(),
        "type": KNOWLEDGE,
        "kind": kind,
        "scope": moc.prop("scope"),
        "created": click.today,
        "updated": click.today,
        "topic": f"[[{moc.title}]]",
    }
    body = f"## Summary\n\n{summary}\n\n![[{stored.name}]]\n"
    companion = Note(stored.with_suffix(".md"), body, Frontmatter.from_dict(props))
    done = digest.graduated_as_is(companion, rules, today=click.today)
    changes: list[Change] = [(None, done), *_moc_change(index, done, click.today)]
    cs = _commit(
        store,
        index,
        changes,
        reason=f"Graduate {stored.name} as is",
        button="graduate-as-is",
        click=click,
    )
    return DigestOutcome(True, rules.digest_flow[-1], "companion note created and graduated", [cs])
