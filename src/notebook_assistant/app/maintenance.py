"""The four maintenance buttons (Handbook §16.6), each run as one call returning a uniform
:class:`Report` for the Settings screen: what it found, and the pending changesets it proposed
for the Review screen. Nothing is applied here (§15.1).

- ``changes``: Sweep changes (:mod:`app.sweep`);
- ``lint``: Lint (:mod:`app.lint`), its fixes and report as one batch;
- ``deep``: Deep pass (:mod:`app.deep_pass`), findings only;
- ``archive``: Archive check (:mod:`app.archive_check`), one changeset per candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from notebook_assistant.app import archive_check, deep_pass, lint, sweep
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.llm import LanguageModel
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store
from notebook_assistant.store import runs

Kind = Literal["changes", "lint", "deep", "archive"]
KINDS: tuple[Kind, ...] = ("changes", "lint", "deep", "archive")
Progress = Callable[[str], None]


@dataclass(frozen=True)
class Row:
    path: str
    label: str  # what kind of finding, e.g. "I-3", "proposed", "duplicate"
    detail: str


@dataclass(frozen=True)
class Report:
    kind: str
    ran_at: str
    summary: str
    rows: list[Row]
    changesets: list[str]  # pending changesets it proposed


@dataclass(frozen=True)
class Context:
    store: VaultStore
    config: Config
    rules: Rules
    handbook: str
    now: datetime
    machine: str
    model: Callable[[], LanguageModel]  # only Sweep changes calls the model


def _changes(ctx: Context, progress: Progress) -> Report:
    result = sweep.sweep_changes(
        ctx.store,
        ctx.model(),
        config=ctx.config,
        rules=ctx.rules,
        handbook=ctx.handbook,
        now=ctx.now,
        machine=ctx.machine,
        progress=progress,
    )
    rows = [Row(p, "proposed", f"changeset {cs}") for p, cs in result.proposed.items()]
    rows += [
        Row(p, "still being edited", "left for the next run (§16.2)") for p in result.unsettled
    ]
    rows += [Row(p, "already proposed", "waiting on Review") for p in result.already_proposed]
    rows += [Row(p, "can't be planned", why) for p, why in result.blocked.items()]
    rows += [Row(p, "failed", why) for p, why in result.failed.items()]
    return _report(ctx, "changes", result.summary, rows, list(result.proposed.values()))


def _lint(ctx: Context, progress: Progress) -> Report:
    progress("Checking every note")
    report, cs = lint.lint_changeset(
        VaultIndex.build(ctx.store), now=ctx.now, created_by="sweep:lint"
    )
    cs.machine = ctx.machine
    cs_store.save(ctx.store, cs)
    rows = [Row(f.path, f.code, f"{f.message} (Handbook {f.section})") for f in report.findings]
    summary = f"{report.notes} notes, {len(report.findings)} finding(s), {report.fixable} fixable"
    return _report(ctx, "lint", summary, rows, [cs.id])


def _deep(ctx: Context, progress: Progress) -> Report:
    index = VaultIndex.build(ctx.store)
    progress("Looking for duplicates")
    dupes = deep_pass.duplicate_candidates(index, ctx.rules, ctx.config.checks.duplicate_similarity)
    progress("Looking for missing links")
    missing = deep_pass.missing_links(index, ctx.rules)
    rows = [Row(d.a, "duplicate?", f"{d.b}: {d.why}") for d in dupes]
    rows += [
        Row(m.path, "missing link", f"names [{m.target}] without linking: “{m.excerpt}”")
        for m in missing
    ]
    summary = f"{len(dupes)} duplicate candidate(s), {len(missing)} missing link(s)"
    return _report(ctx, "deep", summary, rows, [])


def _archive(ctx: Context, progress: Progress) -> Report:
    index = VaultIndex.build(ctx.store)
    today = ctx.now.date()
    progress("Looking for archive candidates (§13)")
    ids: list[str] = []
    rows: list[Row] = []
    for candidate in archive_check.archive_candidates(index, ctx.rules, today):
        cs = archive_check.archive_changeset(
            index, candidate, ctx.rules, now=ctx.now, created_by="sweep:archive"
        )
        cs.machine = ctx.machine
        cs_store.save(ctx.store, cs)
        ids.append(cs.id)
        rows.append(Row(candidate.path, "archive", f"{candidate.reason}; changeset {cs.id}"))
    progress("Reviewing tasks and ideas (§17.6, §18.4)")
    items = archive_check.review_items(index, ctx.rules, today)
    rows += [Row(i.path, i.kind, f"untouched {i.days} days: {i.suggestion}") for i in items]
    summary = f"{len(ids)} to archive, {len(items)} to review"
    return _report(ctx, "archive", summary, rows, ids)


def _report(ctx: Context, kind: str, summary: str, rows: list[Row], ids: list[str]) -> Report:
    if kind != "changes":  # Sweep changes logs its own run
        runs.append(ctx.store, ctx.now, ctx.machine, kind, summary)
    return Report(kind, ctx.now.isoformat(timespec="seconds"), summary, rows, ids)


RUNNERS: dict[str, Callable[[Context, Progress], Report]] = {
    "changes": _changes,
    "lint": _lint,
    "deep": _deep,
    "archive": _archive,
}


def run(kind: str, ctx: Context, progress: Progress = lambda step: None) -> Report:
    """Run one maintenance button; ``ValueError`` for an unknown kind."""
    runner = RUNNERS.get(kind)
    if runner is None:
        raise ValueError(f"unknown maintenance run {kind!r}; one of {', '.join(KINDS)}")
    return runner(ctx, progress)
