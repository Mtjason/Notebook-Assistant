"""The digestion queue's state changes on one note (Handbook §19), as pure functions.

Each function takes a note and returns the note as the button leaves it; the app turns the
difference into a changeset (``app/digest.py``). Values (states, what graduating sets, the
boxes) come from the parsed handbook (:class:`~notebook_assistant.domain.rules.Rules`); only
property names appear here.

- :func:`item_of`: the note as a queue item, or None if it isn't in the queue;
- :func:`approved` → :func:`drafted_in_place` (knowledge notes) or :func:`draft_linked` (learn
  tasks) → :func:`graduated` (and :func:`task_closed`); :func:`sent_back` returns it to the
  queue; :func:`failed` records why a run didn't finish;
- :func:`graduated_as_is`: §19.5, no draft;
- :func:`with_original` / :func:`original_of`: the folded box that keeps the original (§19.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules

RUNNER, STARTED, ERROR = "digest_runner", "digest_started", "digest_error"
DIGEST, REASON, DRAFT, FEEDBACK = "digest", "digest_reason", "digest_draft", "digest_feedback"


@dataclass(frozen=True)
class DigestItem:
    path: str
    title: str
    type: str | None
    state: str
    reasons: list[str]
    error: str | None
    feedback: str | None
    draft: str | None  # the draft note's link, for a learn task
    runner: str | None


def _copy(note: Note) -> Note:
    return Note.parse(note.path, note.render())


def _set(note: Note, today: str, **props: object) -> Note:
    """A copy with ``props`` set (None deletes) and ``updated`` = today."""
    copy = _copy(note)
    fm = copy.ensure_frontmatter()
    for key, value in props.items():
        if value is None:
            fm.delete(key)
        else:
            fm.set(key, value)
    fm.set("updated", today)
    return copy


def item_of(note: Note, rules: Rules) -> DigestItem | None:
    state = note.prop(DIGEST)
    if not isinstance(state, str) or state not in rules.digest_flow:
        return None
    fm = note.frontmatter
    reasons = [str(r) for r in fm.get_list(REASON)] if fm else []
    error, feedback, draft, runner = (note.prop(k) for k in (ERROR, FEEDBACK, DRAFT, RUNNER))
    return DigestItem(
        path=note.path.as_posix(),
        title=note.title,
        type=note.type,
        state=state,
        reasons=reasons,
        error=str(error) if error else None,
        feedback=str(feedback) if feedback else None,
        draft=str(draft) if draft else None,
        runner=str(runner) if runner else None,
    )


def approved(note: Note, rules: Rules, *, runner: str, started: str, today: str) -> Note:
    """§19.2 step 2 starts: ``digest: approved`` and which PC runs it, since when."""
    return _set(
        note, today, **{DIGEST: rules.digest_flow[1], RUNNER: runner, STARTED: started, ERROR: None}
    )


def failed(note: Note, rules: Rules, *, error: str, today: str) -> Note:
    """Back in the queue with the reason the run didn't finish (§19.2, button behaviour)."""
    return _set(
        note, today, **{DIGEST: rules.digest_flow[0], ERROR: error, RUNNER: None, STARTED: None}
    )


def with_original(draft: str, original: str, rules: Rules) -> str:
    """The draft, then the original kept verbatim in the folded box (§19.3)."""
    quoted = "\n".join(f"> {line}" if line else ">" for line in original.strip("\n").split("\n"))
    return f"{draft.strip()}\n\n{rules.digestion.original_box}\n{quoted}\n"


def original_of(body: str, rules: Rules) -> str | None:
    """The original kept in the box, or None when the body has no box."""
    head = rules.digestion.original_box
    start = body.find(head + "\n")
    if start < 0:
        return None
    lines: list[str] = []
    for line in body[start + len(head) + 1 :].split("\n"):
        if not line.startswith(">"):
            break
        lines.append(line[2:] if line.startswith("> ") else line[1:])
    return "\n".join(lines).strip("\n") + "\n"


def drafted_in_place(note: Note, draft: str, rules: Rules, *, today: str) -> Note:
    """A knowledge note rewritten as ``draft`` with its original kept below (§19.3)."""
    original = original_of(note.body, rules) or note.body
    copy = _set(note, today, **{DIGEST: rules.digest_flow[2], RUNNER: None, STARTED: None})
    copy.body = with_original(draft, original, rules)
    return copy


def draft_linked(task: Note, draft_title: str, rules: Rules, *, today: str) -> Note:
    """A learn task whose draft is a new note: linked as ``digest_draft`` (§19.3)."""
    return _set(
        task,
        today,
        **{DIGEST: rules.digest_flow[2], DRAFT: f"[[{draft_title}]]", RUNNER: None, STARTED: None},
    )


def graduated(note: Note, rules: Rules, *, today: str) -> Note:
    """Solid knowledge (§19.2, step 4a): what the handbook says graduating sets."""
    props: dict[str, object] = dict(rules.digestion.graduate)
    props.update({DIGEST: rules.digest_flow[-1], REASON: None, FEEDBACK: None, ERROR: None})
    return _set(note, today, **props)


def task_closed(task: Note, produced_title: str, rules: Rules, *, today: str) -> Note:
    """The learn task is done, with ``produced`` linking the note it led to (§19.2, §17.1)."""
    d = rules.digestion
    return _set(
        task,
        today,
        **{
            "status": d.task_done,
            d.produced: [f"[[{produced_title}]]"],
            DIGEST: rules.digest_flow[-1],
            REASON: None,
            FEEDBACK: None,
            DRAFT: None,
        },
    )


def sent_back(note: Note, feedback: str, rules: Rules, *, today: str) -> Note:
    """Back to the queue with your feedback; an in-place draft is replaced by the original."""
    copy = _set(note, today, **{DIGEST: rules.digest_flow[0], FEEDBACK: feedback.strip() or None})
    original = original_of(copy.body, rules)
    if original is not None:
        copy.body = original
    return copy


def graduated_as_is(note: Note, rules: Rules, *, today: str) -> Note:
    """§19.5: finished as it is; the content isn't touched."""
    props: dict[str, object] = dict(rules.digestion.as_is)
    props.update({REASON: None, FEEDBACK: None, ERROR: None, DRAFT: None})
    return _set(note, today, **props)


def links_to(note: Note, title: str) -> bool:
    key = name_key(title)
    targets = (link.target.split("/")[-1].removesuffix(".md") for link in find_links(note.render()))
    return any(name_key(target) == key for target in targets)


def moc_linking(moc: Note, title: str, *, today: str) -> Note | None:
    """The MOC with a line linking ``title`` added at the end, or None if it links it already
    (§19.2: graduating links the note from its MOC)."""
    if links_to(moc, title):
        return None
    copy = _set(moc, today)
    copy.body = f"{copy.body.rstrip()}\n- [[{title}]]\n"
    return copy
