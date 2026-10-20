"""Filing the Inbox note a capture came from, in the same changeset as its planned notes
(Handbook §12, §10). Recomputed whenever the plan is recompiled, so it always lists the notes the
plan produces now.

- A capture that keeps a ``source`` note: the Inbox note becomes that note in its folder, linking
  the extracted notes (I-5), with its attachments renamed after it (§10).
- A short typed capture: the Inbox note is removed, and the capture date's daily note (created if
  missing) logs links to the extracted notes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain import capture
from notebook_assistant.domain.changeset import CaptureSource, Operation
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.note import Note, title_of
from notebook_assistant.domain.plan_notes import Outcome
from notebook_assistant.domain.rules import Rules


class FilingError(ValueError):
    """The Inbox note to file is gone, or its plan produced no note."""


def scope_of(outcomes: Mapping[str, Outcome]) -> str:
    """The ``scope`` most of the plan's notes have (ties: the first note's), for the source or
    daily note filed with them."""
    scopes = [str(o.after.prop("scope")) for o in outcomes.values() if o.after.prop("scope")]
    if not scopes:
        raise FilingError("the plan produced no note with a scope")
    counts = Counter(scopes)
    return max(scopes, key=lambda s: counts[s])


def attachment_renames(index: VaultIndex, inbox: Note, title: str, rules: Rules) -> dict[str, str]:
    """``{old name: new name}`` for the files the Inbox note embeds from the attachments folder
    under its own title, renamed after the source note (§10)."""
    prefix = f"{inbox.title} - "
    renames: dict[str, str] = {}
    for link in find_links(inbox.body):
        target = index.resolver.resolve(link, inbox.path) if link.embed else None
        if (
            target is not None
            and target.parent.as_posix() == rules.capture.attachments
            and target.name.startswith(prefix)
            and inbox.title != title
        ):
            renames[target.name] = f"{title} - {target.name[len(prefix) :]}"
    return renames


def _write(index: VaultIndex, before: Note | None, after: Note, label: str) -> Operation:
    if before is None:
        return Operation("create", after.path, content=after.render(), label=label)
    stored = index.text(before.path)
    assert stored is not None, "the note comes from the index"
    return Operation(
        "write", before.path, content=after.render(), base_hash=content_hash(stored), label=label
    )


def filing_ops(
    index: VaultIndex, source: CaptureSource, outcomes: Mapping[str, Outcome], *, today: str
) -> list[Operation]:
    assert source.inbox is not None and source.cites is not None, "only Inbox captures are filed"
    rules = index.facts().rules
    inbox = index.note(source.inbox)
    stored = index.text(source.inbox)
    if inbox is None or stored is None:
        raise FilingError(f"{source.inbox} is no longer in the Inbox")
    extracted = [o.after.title for o in outcomes.values()]
    scope = scope_of(outcomes)
    folder = PurePosixPath(rules.capture.attachments)
    if source.cites.parent.as_posix() == rules.types[capture.SOURCE].folders[0]:
        title = title_of(source.cites)
        renames = attachment_renames(index, inbox, title, rules)
        note = capture.source_note(
            inbox,
            title,
            rules=rules,
            scope=scope,
            today=today,
            extracted=extracted,
            renames=renames,
        )
        moves = [
            Operation("move", folder / old, dest=folder / new, label="rename attachment")
            for old, new in renames.items()
        ]
        return [
            *moves,
            Operation(
                "move",
                inbox.path,
                dest=note.path,
                content=note.render(),
                base_hash=content_hash(stored),
                label="source note",
            ),
        ]
    daily = index.note(source.cites)
    logged = capture.daily_logged(
        daily, source.cites, rules=rules, scope=scope, today=today, extracted=extracted
    )
    return [
        Operation("delete", inbox.path, base_hash=content_hash(stored), label="processed capture"),
        _write(index, daily, logged, "log the capture"),
    ]
