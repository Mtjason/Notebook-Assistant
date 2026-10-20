"""The Lint button (Handbook §16.6; §14: the lint report): every rule check on every note, no
AI, and the mechanical fixes for what code can fix without judgment, grouped into one pending
changeset you accept at once (§16.5) together with this month's report note.

Fixed mechanically (§16.3, lint row): a missing ``updated`` (set to today) and a tag whose
spelling differs from the registry's only in case. Everything else is reported for you.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.invariants import check_note, is_checked
from notebook_assistant.domain.note import NOTE_SUFFIX, Note

UPDATED, TAGS = "updated", "tags"


@dataclass(frozen=True)
class Finding:
    path: str
    code: str  # a Violation code, "link" for a link to nothing, "parse" for bad frontmatter
    message: str
    section: str


@dataclass(frozen=True)
class LintReport:
    notes: int  # notes checked
    findings: list[Finding]
    fixable: int  # findings the batch fixes

    @property
    def by_code(self) -> dict[str, int]:
        return dict(sorted(Counter(f.code for f in self.findings).items()))


def lint_vault(index: VaultIndex) -> list[Finding]:
    """Every violation (§0.1, §4, §5, §6), link to nothing, and unreadable frontmatter."""
    facts = index.facts()
    findings: list[Finding] = []
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        for v in check_note(note, facts):
            findings.append(Finding(note.path.as_posix(), v.code, v.message, v.section))
    for source, link in index.broken:
        if is_checked(source, facts.rules) and not is_state_path(source):
            findings.append(
                Finding(
                    source.as_posix(), "link", f"link to {link.target!r} points to nothing", "§7"
                )
            )
    for path, error in sorted(index.unparseable.items()):
        if is_checked(PurePosixPath(path), facts.rules):
            findings.append(Finding(path, "parse", " ".join(error.split()), "§4"))
    return findings


def fixed(note: Note, registry: frozenset[str] | None, today: str) -> Note | None:
    """``note`` with its mechanical fixes, or None when it needs none."""
    fm = note.frontmatter
    if fm is None or not note.type:
        return None
    copy = Note.parse(note.path, note.render())
    cfm = copy.ensure_frontmatter()
    changed = False
    if not fm.get(UPDATED):
        cfm.set(UPDATED, today)
        changed = True
    if registry:
        by_key = {t.casefold(): t for t in registry}
        tags = [str(t).lstrip("#") for t in fm.get_list(TAGS)]
        respelled = [t if t in registry else by_key.get(t.casefold(), t) for t in tags]
        if respelled != tags:
            cfm.set(TAGS, respelled)
            changed = True
    return copy if changed else None


def report_note(path: PurePosixPath, report: LintReport, *, today: str) -> str:
    """The month's lint report (§14), a `system` note listing what's left after the fixes."""
    lines = [
        "---",
        "type: system",
        "scope: personal",
        "status: active",
        f"created: {today}",
        f"updated: {today}",
        "---",
        f"## Lint {today}",
        "",
        f"{report.notes} notes checked · {len(report.findings)} finding(s)"
        f" · {report.fixable} fixed mechanically in the same changeset",
        "",
        "| Note | Code | Problem | Rule |",
        "|---|---|---|---|",
    ]
    for f in report.findings:
        title = PurePosixPath(f.path).name.removesuffix(NOTE_SUFFIX)
        # one table row each; no wikilink in a message, so the report never links to nothing
        problem = " ".join(f.message.split()).replace("|", "\\|").replace("[[", "[ [")
        lines.append(f"| [[{title}]] | {f.code} | {problem} | Handbook {f.section} |")
    return "\n".join(lines) + "\n"


def lint_changeset(
    index: VaultIndex, *, now: datetime, created_by: str
) -> tuple[LintReport, Changeset]:
    """The report, and one pending changeset: every mechanical fix plus the report note."""
    today = now.date().isoformat()
    findings = lint_vault(index)
    registry = index.tag_registry()
    ops: list[Operation] = []
    fixable = 0
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        if is_state_path(note.path) or not is_checked(note.path, index.facts().rules):
            continue
        after = fixed(note, registry, today)
        stored = index.text(note.path)
        if after is None or stored is None:
            continue
        fixable += 1
        ops.append(
            Operation(
                "write",
                note.path,
                content=after.render(),
                base_hash=content_hash(stored),
                label="mechanical fix",
            )
        )
    report = LintReport(len(index.notes), findings, fixable)
    month = now.strftime("%Y-%m")
    path = PurePosixPath(index.facts().rules.review.lint_report.replace("YYYY-MM", month))
    text = report_note(path, report, today=today)
    existing = index.text(path)
    ops.append(
        Operation("create", path, content=text, label="lint report")
        if existing is None
        else Operation(
            "write", path, content=text, base_hash=content_hash(existing), label="lint report"
        )
    )
    cs = Changeset(
        reason=f"Lint: {fixable} mechanical fix(es) and the {month} report",
        created_by=created_by,
        created=now.isoformat(timespec="seconds"),
        ops=ops,
    )
    return report, cs
