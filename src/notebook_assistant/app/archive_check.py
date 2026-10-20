"""The Archive check button (Handbook §16.6): archive candidates (§13), stale tasks (§17.6) and
the Incubator check (§18.4). Ages count from a note's ``updated`` date.

- :func:`archive_candidates`: notes whose type and status have been unchanged long enough to be
  archived (the §13 ages); :func:`archive_changeset` proposes moving one to the archive folder,
  mirrored, with ``status: archived``, ``archived`` and ``archive_reason`` (§13). A container's
  hub moves with its whole folder; a single note moves link-safely (§5.2).
- :func:`review_items`: what the weekly and monthly reviews ask you about, without proposing a
  change by themselves: `waiting` tasks to nudge, learn tasks and ideas untouched for long.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.app.rename import plan_move
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.domain.tasks import live_statuses

# Vocabulary (Handbook §4.3, §13, §17): statuses and property names these checks read or set.
ARCHIVED, WAITING, TASK, IDEA, LEARN = "archived", "waiting", "task", "idea", "learn"


@dataclass(frozen=True)
class Candidate:
    path: str
    title: str
    type: str
    status: str
    days: int  # since `updated`
    reason: str  # the `archive_reason` it would get


@dataclass(frozen=True)
class ReviewItem:
    path: str
    title: str
    kind: str  # "nudge" (waiting task), "learn" (untouched learn task), "idea" (untouched idea)
    days: int
    suggestion: str


def age_in_days(note: Note, today: date) -> int | None:
    """Days since the note's ``updated`` date, or None when it has none."""
    value = note.prop("updated")
    try:
        updated = date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    return (today - updated).days if updated else None


def _live(note: Note, rules: Rules) -> bool:
    top = note.path.parts[0] if note.path.parts else ""
    return not is_state_path(note.path) and top != rules.archive_root


def archive_candidates(index: VaultIndex, rules: Rules, today: date) -> list[Candidate]:
    found: list[Candidate] = []
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        rule = rules.review.archive.get(note.type or "")
        status = str(note.prop("status") or "")
        days = age_in_days(note, today)
        if rule is None or not _live(note, rules) or status not in rule.statuses:
            continue
        if days is not None and days >= rule.days:
            reason = f"{status} for {rule.days}+ days"
            found.append(
                Candidate(note.path.as_posix(), note.title, str(note.type), status, days, reason)
            )
    return found


def review_items(index: VaultIndex, rules: Rules, today: date) -> list[ReviewItem]:
    r = rules.review
    live_tasks, live_ideas = live_statuses(rules, TASK), live_statuses(rules, IDEA)
    items: list[ReviewItem] = []
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        days = age_in_days(note, today)
        if days is None or not _live(note, rules):
            continue
        status, kind = note.prop("status"), note.prop("kind")
        path, title = note.path.as_posix(), note.title
        if note.type == TASK and status == WAITING and days > r.waiting_nudge_days:
            items.append(ReviewItem(path, title, "nudge", days, "ask again or drop it"))
        elif (
            note.type == TASK
            and kind == LEARN
            and status in live_tasks
            and days >= r.learn_untouched_days
        ):
            items.append(ReviewItem(path, title, "learn", days, "move to someday, or drop it"))
        elif note.type == IDEA and status in live_ideas and days >= r.idea_untouched_days:
            items.append(ReviewItem(path, title, "idea", days, "park it, or drop it"))
    return items


def _archived(text: str, path: PurePosixPath, reason: str, today: str) -> str:
    note = Note.parse(path, text)
    fm = note.ensure_frontmatter()
    for key, value in (("status", ARCHIVED), ("archived", today), ("archive_reason", reason)):
        fm.set(key, value)
    fm.set("updated", today)
    return note.render()


def _container_folder(index: VaultIndex, path: PurePosixPath, rules: Rules) -> PurePosixPath | None:
    """The hub's container folder when ``path`` is a hub (`<root>/<Name>/<Name>.md`, §2.1)."""
    roots = rules.container_roots
    if len(path.parts) == 3 and path.parts[0] in roots and path.parts[1] == path.stem:
        return path.parent
    return None


def archive_changeset(
    index: VaultIndex, candidate: Candidate, rules: Rules, *, now: datetime, created_by: str
) -> Changeset:
    today = now.date().isoformat()
    src = PurePosixPath(candidate.path)
    reason = f"Archive {candidate.title}: {candidate.reason} (Handbook §13)"
    folder = _container_folder(index, src, rules)
    if folder is None:
        cs = plan_move(
            index,
            src,
            PurePosixPath(rules.archive_root) / src,
            reason=reason,
            created_by=created_by,
            now=now,
        )
        move = cs.ops[0]
        text = move.content if move.content is not None else index.text(src)
        assert text is not None and move.dest is not None
        cs.ops[0] = Operation(
            "move",
            move.path,
            dest=move.dest,
            content=_archived(text, move.dest, candidate.reason, today),
            base_hash=move.base_hash,
            label="archive",
        )
        return cs
    ops: list[Operation] = []
    for path in sorted(p for p in index.files if p.parent == folder or folder in p.parents):
        dest = PurePosixPath(rules.archive_root) / path
        text = index.text(path)
        content = _archived(text, dest, candidate.reason, today) if path == src and text else None
        ops.append(
            Operation(
                "move",
                path,
                dest=dest,
                content=content,
                base_hash=content_hash(text) if text is not None else None,
                label="archive" if path == src else "archive with its container",
            )
        )
    return Changeset(
        reason=reason, created_by=created_by, created=now.isoformat(timespec="seconds"), ops=ops
    )
