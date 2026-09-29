"""The extraction planner: one capture becomes a pending changeset with its split map.

Every path that turns raw material into notes goes through here (docs/maintenance-job.md,
Extraction). The model does steps 1-6 (segment, classify, generalize, match, plan, verify) in one
structured answer, a split plan (:mod:`notebook_assistant.domain.split_plan`); code does step 7:
it builds the resulting notes, checks them (:mod:`notebook_assistant.domain.plan_checks`) and
compiles them into changeset operations. A failing plan is sent back once with its problems;
if the second one fails too, :class:`ExtractionError` lists them.

What the model sees: the instructions and the handbook (a stable, cached prefix), then a
catalog of every note, the full text of the notes most related to the capture (so it patches
instead of duplicating, Handbook §15 rule 3), and the capture.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.ids import content_hash, new_note_id
from notebook_assistant.domain.invariants import VaultFacts
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.plan_checks import PlanContext, check_plan
from notebook_assistant.domain.plan_notes import Outcome, build_outcomes
from notebook_assistant.domain.split_plan import (
    PLAN_SCHEMA,
    PlanFormatError,
    Role,
    SplitPlan,
    parse_plan,
)
from notebook_assistant.ports.llm import JsonRequest, LanguageModel

ATTEMPTS = 2  # a failing plan is retried once (docs/maintenance-job.md, Extraction, step 7)

INSTRUCTIONS = """\
You are the extraction planner of a note assistant for an Obsidian vault. The Vault Handbook
follows; it is the only authority on where notes go and what they contain. Obey it exactly.

Turn the capture into a split plan (docs: segment, classify, generalize, match, plan, verify):

1. Segment the capture into atoms: the smallest pieces worth looking up on their own. An atom's
   `text` is copied verbatim from the capture.
2. Classify each atom with the decision order (Handbook §3) and the topic folders (§2.3).
3. Generalize (§3.1, instance vs. principle): an explanation that holds beyond this one case is a
   `principle` for a knowledge note; the specific case is an `instance` and keeps only what is
   specific to it. Items of another type are `extracted` (§3.1, mixed notes). Conversational
   filler that carries no information is `filler`: it is dropped and listed for review.
4. Match: prefer patching an existing note (§15 rule 3) over creating one. The catalog lists every
   note; related notes are shown in full. Patch by adding content under `##` headings.
5. Plan: every atom lands in exactly one note (a correction in every note it corrects, filler in
   none). Instance notes link to principle notes and back (§3.1); notes link to their MOC (§7).
6. Verify: correct a claim only with a source outside the capture (e.g. official docs): add a
   `correction` atom quoting the corrected excerpt, with the source URL as `citation`, and write
   the correction and URL into each corrected note and its history line. Anything you cannot
   support goes in a `> [!question] Unverified` callout. The capture's own references are not
   verification.

Hard requirements (a plan that breaks one is rejected):
- Nothing is lost: every sentence, list item, code span, URL, number and link of the capture
  (except filler) appears, verbatim or nearly so, in the content the plan writes. Restructure,
  add headings and explanations freely, but keep the capture's own words.
- A principle's text appears only in the note it lands in; other notes link to it.
- Created notes: `folder` is their vault folder; `properties` follow Handbook §4, including
  `aliases` in both languages (§15 rule 5), the capture's `origin`, and the digest state §19.6
  gives new notes from a direct capture. The body starts at `##` (no H1, §8.1).
- Never set `id`, `created`, `updated` or `assistant_hash`; the assistant manages them.
- `history` lines are plain text; the date is added for you.
- A capture that fits no topic (§2.2): its note goes to the Inbox with `needs_review: true` and a
  `handbook_gap` naming the proposed topic folder, and `topic_proposal` drafts the §2.3 row.
  Otherwise `topic_proposal` is null.
- Every link you write must point to a note in the catalog or one the plan creates.
"""


class ExtractionError(Exception):
    """The model's plans kept failing the checks."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("the split plan failed its checks:\n" + "\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Capture:
    text: str
    origin: str  # Handbook §4.1 `origin` of the material
    name: str  # what it's called in the changeset's reason, e.g. a file name


@dataclass
class Extraction:
    plan: SplitPlan
    outcomes: dict[str, Outcome]
    changeset: Changeset
    attempts: int = 1
    rejected: list[list[str]] = field(default_factory=list)  # problems of discarded plans


# --------------------------------------------------------------------------- the request


def _words(text: str) -> set[str]:
    """Search terms: Latin words of 3+ letters and pairs of CJK characters."""
    latin = {w.casefold() for w in re.findall(r"[A-Za-z][\w.-]{2,}", text)}
    cjk = re.findall(r"[㐀-鿿]+", text)
    return latin | {run[i : i + 2] for run in cjk for i in range(len(run) - 1)}


def related_notes(index: VaultIndex, text: str, limit: int) -> list[Note]:
    """The ``limit`` notes sharing the most search terms with ``text`` (none that share none).

    A keyword stand-in for the per-PC search index (docs/architecture.md §5.4.1, branch 9)."""
    terms = _words(text)
    scored: list[tuple[int, str, Note]] = []
    for note in index.notes.values():
        if is_state_path(note.path):
            continue
        aliases = (
            " ".join(str(a) for a in note.frontmatter.get_list("aliases"))
            if note.frontmatter
            else ""
        )
        score = len(terms & _words(f"{note.title} {aliases} {note.body}"))
        if score:
            scored.append((score, note.path.as_posix(), note))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [note for _, _, note in scored[:limit]]


def catalog(index: VaultIndex) -> str:
    """One line per note: title, type, folder and aliases, for matching (Handbook §15 rule 3)."""
    lines = []
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        if is_state_path(note.path):
            continue
        aliases = note.frontmatter.get_list("aliases") if note.frontmatter else []
        extra = f" | aliases: {', '.join(str(a) for a in aliases)}" if aliases else ""
        lines.append(f"- {note.title} | {note.type or 'no type'} | {note.path.parent}{extra}")
    return "\n".join(lines)


def build_request(
    capture: Capture,
    index: VaultIndex,
    *,
    config: Config,
    handbook: str,
    feedback: list[str],
) -> JsonRequest:
    related = related_notes(index, capture.text, config.extraction.related_notes)
    shown = "\n\n".join(f"### {n.path.as_posix()}\n\n{n.render()}" for n in related)
    parts = [
        f"## Catalog of existing notes\n\n{catalog(index)}",
        f"## Related notes, in full\n\n{shown or '(none)'}",
        f"## The capture (origin: {capture.origin})\n\n{capture.text}",
    ]
    if feedback:
        problems = "\n".join(f"- {p}" for p in feedback)
        parts.append(f"## Your previous plan was rejected; fix these problems\n\n{problems}")
    return JsonRequest(
        model=config.models.transform,
        system=(INSTRUCTIONS, handbook),
        prompt="\n\n".join(parts),
        schema=PLAN_SCHEMA,
        max_tokens=config.limits.max_tokens_per_job,
    )


# --------------------------------------------------------------------------- checking


def _existing(index: VaultIndex) -> dict[str, Note]:
    out: dict[str, Note] = {}
    for note in sorted(index.notes.values(), key=lambda n: n.path.as_posix()):
        if not is_state_path(note.path):
            out.setdefault(name_key(note.title), note)
    return out


def evaluate(
    plan: SplitPlan,
    index: VaultIndex,
    capture: Capture,
    *,
    config: Config,
    today: str,
    new_id: Callable[[], str],
) -> tuple[dict[str, Outcome], list[str]]:
    """The plan's resulting notes and every problem with them (empty = the plan may be proposed)."""
    outcomes, problems = build_outcomes(plan, _existing(index), today=today, new_id=new_id)
    base = index.facts()
    counts = base.title_counts.copy()
    created = [o.after.path for o in outcomes.values() if o.before is None]
    counts.update(name_key(PurePosixPath(p).stem) for p in created)
    ctx = PlanContext(
        capture=capture.text,
        origin=capture.origin,
        facts=VaultFacts(base.rules, counts, base.registered_tags),
        paths=(*index.files, *created),
        similarity=config.checks.preservation_similarity,
    )
    return outcomes, problems + check_plan(plan, outcomes, ctx)


# --------------------------------------------------------------------------- the changeset


def _cell(text: str, limit: int = 60) -> str:
    flat = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def split_map(plan: SplitPlan, outcomes: dict[str, Outcome]) -> str:
    """The review card's split map: each atom, its role, and where it lands (new or patch)."""

    def target(title: str) -> str:
        outcome = outcomes.get(name_key(title))
        kind = "new" if outcome is not None and outcome.before is None else "patch"
        return f"[[{title}]] ({kind})"

    rows = [
        f"| {a.id} | {a.role.value} | {', '.join(target(t) for t in a.notes)} | {_cell(a.text)} |"
        for a in plan.atoms
        if a.role is not Role.FILLER
    ]
    parts = [
        "### Split map\n\n| Atom | Role | Lands in | Excerpt |\n|---|---|---|---|\n"
        + "\n".join(rows)
    ]
    filler = [f"- {_cell(a.text, 120)}" for a in plan.atoms if a.role is Role.FILLER]
    if filler:
        parts.append("### Dropped as filler\n\n" + "\n".join(filler))
    proposal = plan.topic_proposal
    if proposal is not None:
        parts.append(
            "### Handbook amendment draft (§2.2): a new §2.3 topic\n\n"
            "| Folder | Answers | Examples | Not here |\n|---|---|---|---|\n"
            f"| `{proposal.folder}/` | {_cell(proposal.answers, 200)} | "
            f"{_cell(proposal.examples, 200)} | {_cell(proposal.not_here, 200)} |"
        )
    return "\n\n".join(parts)


def compile_changeset(
    outcomes: dict[str, Outcome],
    index: VaultIndex,
    *,
    reason: str,
    created_by: str,
    now: datetime,
    review: str,
) -> Changeset:
    """Create operations for new notes, base-hash-guarded writes for patched ones."""
    ops: list[Operation] = []
    for outcome in outcomes.values():
        after = outcome.after
        if outcome.before is None:
            ops.append(Operation("create", after.path, content=after.render(), label="new note"))
            continue
        stored = index.text(outcome.before.path)
        assert stored is not None, "a patched note comes from the index"
        ops.append(
            Operation(
                "write",
                outcome.before.path,
                content=after.render(),
                base_hash=content_hash(stored),
                label="add to note",
            )
        )
    return Changeset(
        reason=reason,
        created_by=created_by,
        created=now.isoformat(timespec="seconds"),
        ops=ops,
        review=review,
    )


# --------------------------------------------------------------------------- the planner


def plan_extraction(
    capture: Capture,
    index: VaultIndex,
    model: LanguageModel,
    *,
    config: Config,
    handbook: str,
    now: datetime,
    created_by: str,
    new_id: Callable[[], str] = new_note_id,
) -> Extraction:
    """Plan, check and compile; raises :class:`ExtractionError` (or ``LLMError``)."""
    today = now.date().isoformat()
    feedback: list[str] = []
    rejected: list[list[str]] = []
    for attempt in range(1, ATTEMPTS + 1):
        request = build_request(capture, index, config=config, handbook=handbook, feedback=feedback)
        try:
            plan = parse_plan(model.complete_json(request))
        except PlanFormatError as exc:
            feedback = [f"the plan is malformed: {exc}"]
            rejected.append(feedback)
            continue
        outcomes, problems = evaluate(
            plan, index, capture, config=config, today=today, new_id=new_id
        )
        if problems:
            feedback = problems
            rejected.append(problems)
            continue
        changeset = compile_changeset(
            outcomes,
            index,
            reason=f"Digest {capture.name}",
            created_by=created_by,
            now=now,
            review=split_map(plan, outcomes),
        )
        return Extraction(plan, outcomes, changeset, attempt, rejected)
    raise ExtractionError(feedback)
