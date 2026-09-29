"""Validate a split plan against its capture and the handbook (docs/maintenance-job.md,
Extraction, step 7). Deterministic: the model proposes, this code decides.

:func:`check_plan` returns every problem found (empty means the plan may be proposed):

- **atoms** are verbatim excerpts of the capture, and each lands where its role says: one note,
  a correction at least one, filler none (it's dropped and listed on the review card);
- **coverage:** nothing of the capture is lost across the resulting notes (Handbook §16.4 rule 1),
  and every created note carries at least one atom;
- **no duplicated explanation:** a principle's text appears only in the note it lands in;
- **links both ways:** every instance note links to every principle note and back (§3.1), and
  every link the plan writes resolves;
- **corrections** cite a source outside the capture, in the notes they correct (step 6);
- **provenance:** created notes keep the capture's ``origin``, have ``aliases`` (§15 rule 5) and,
  for the type §19.6 names, its digest state; the plan never sets the assistant's own properties;
- **topic gaps:** a note waiting on a handbook gap is in the Inbox and flagged (§0.3, §2.2), and a
  proposed topic is new and named by such a note;
- **rules:** no resulting note gains a handbook violation (§0.1, §4, §5, §6).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from notebook_assistant.domain import preserve
from notebook_assistant.domain.invariants import VaultFacts, new_violations
from notebook_assistant.domain.links import Resolver, find_links
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.plan_notes import ASSISTANT_PROPERTIES, Outcome
from notebook_assistant.domain.split_plan import NoteOp, Role, SplitPlan


@dataclass(frozen=True)
class PlanContext:
    """What the checks compare the plan with."""

    capture: str
    origin: str  # the capture's origin (Handbook §4.1)
    facts: VaultFacts  # rules, and title counts *including* the notes the plan creates
    paths: tuple[PurePosixPath, ...]  # every file once the plan is applied
    similarity: float  # checks.preservation_similarity


def check_plan(plan: SplitPlan, outcomes: Mapping[str, Outcome], ctx: PlanContext) -> list[str]:
    """Every problem with ``plan``; ``outcomes`` are its resulting notes by ``name_key(title)``."""
    return [
        *_atoms_are_excerpts(plan, ctx),
        *_atoms_land(plan, outcomes),
        *_nothing_lost(plan, outcomes, ctx),
        *_no_duplicated_principle(plan, outcomes, ctx),
        *_links_both_ways(plan, outcomes, ctx),
        *_links_resolve(outcomes, ctx),
        *_corrections_cited(plan, outcomes, ctx),
        *_provenance(outcomes, ctx),
        *_topic_gap(plan, outcomes, ctx),
        *_rules(outcomes, ctx),
    ]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _atoms_are_excerpts(plan: SplitPlan, ctx: PlanContext) -> list[str]:
    capture = _squash(ctx.capture)
    return [
        f"atom {a.id}: its text is not a verbatim excerpt of the capture"
        for a in plan.atoms
        if not a.text.strip() or _squash(a.text) not in capture
    ]


def _atoms_land(plan: SplitPlan, outcomes: Mapping[str, Outcome]) -> list[str]:
    problems: list[str] = []
    for atom in plan.atoms:
        count = len(atom.notes)
        if atom.role is Role.FILLER and count:
            problems.append(f"atom {atom.id}: filler is dropped, so it lands in no note")
        elif atom.role is Role.CORRECTION and not count:
            problems.append(f"atom {atom.id}: a correction must land in the notes it corrects")
        elif atom.role not in (Role.FILLER, Role.CORRECTION) and count != 1:
            problems.append(f"atom {atom.id}: must land in exactly one note, not {count}")
        for title in atom.notes:
            if plan.note(title) is None:
                problems.append(f"atom {atom.id}: lands in {title!r}, which the plan doesn't list")
    for note in plan.notes:
        if note.op is NoteOp.CREATE and not plan.atoms_for(note.title):
            problems.append(f"{note.title}: a created note must carry at least one atom")
    return problems


def _nothing_lost(plan: SplitPlan, outcomes: Mapping[str, Outcome], ctx: PlanContext) -> list[str]:
    kept = ctx.capture
    for atom in plan.atoms:
        if atom.role is Role.FILLER:
            kept = kept.replace(atom.text, "")
    report = preserve.check(kept, [o.added for o in outcomes.values()], similarity=ctx.similarity)
    return (
        []
        if report.ok
        else [f"content lost: {report.summary()}"]
        + [
            f"  missing: {item}"
            for item in (*report.missing_exact, *report.missing_numbers, *report.missing_text)
        ]
    )


def _no_duplicated_principle(
    plan: SplitPlan, outcomes: Mapping[str, Outcome], ctx: PlanContext
) -> list[str]:
    problems: list[str] = []
    for atom in plan.atoms:
        if atom.role is not Role.PRINCIPLE:
            continue
        home = {name_key(t) for t in atom.notes}
        for key, outcome in outcomes.items():
            if key in home:
                continue
            if preserve.shared_units(atom.text, outcome.added, similarity=ctx.similarity):
                problems.append(
                    f"atom {atom.id}: principle text repeated in {outcome.planned.title}"
                    " (link to the principle note instead)"
                )
    return problems


def _links_to(outcome: Outcome, target: Outcome, resolver: Resolver) -> bool:
    text = outcome.after.render()
    return any(resolver.resolve(link, outcome.after.path) == target.after.path
               for link in find_links(text))  # fmt: skip


def _links_both_ways(
    plan: SplitPlan, outcomes: Mapping[str, Outcome], ctx: PlanContext
) -> list[str]:
    def notes_with(role: Role) -> list[Outcome]:
        keys = {name_key(t) for a in plan.atoms if a.role is role for t in a.notes}
        return [outcomes[k] for k in sorted(keys) if k in outcomes]

    resolver = Resolver(ctx.paths)
    problems: list[str] = []
    for instance in notes_with(Role.INSTANCE):
        for principle in notes_with(Role.PRINCIPLE):
            if instance is principle:
                continue
            for a, b in ((instance, principle), (principle, instance)):
                if not _links_to(a, b, resolver):
                    problems.append(f"{a.planned.title} doesn't link to {b.planned.title} (§3.1)")
    return problems


def _links_resolve(outcomes: Mapping[str, Outcome], ctx: PlanContext) -> list[str]:
    resolver = Resolver(ctx.paths)
    return [
        f"{o.planned.title}: link to {link.target!r} points nowhere"
        for o in outcomes.values()
        for link in find_links(o.added)
        if resolver.resolve(link, o.after.path) is None
    ]


def _corrections_cited(
    plan: SplitPlan, outcomes: Mapping[str, Outcome], ctx: PlanContext
) -> list[str]:
    problems: list[str] = []
    for atom in plan.atoms:
        if atom.role is not Role.CORRECTION:
            if atom.citation:
                problems.append(f"atom {atom.id}: only corrections cite a source")
            continue
        if not re.match(r"https?://\S+$", atom.citation):
            problems.append(f"atom {atom.id}: a correction needs a source URL (else Unverified)")
            continue
        if atom.citation in ctx.capture:
            problems.append(f"atom {atom.id}: the capture's own references don't verify it")
        for title in atom.notes:
            outcome = outcomes.get(name_key(title))
            if outcome is not None and atom.citation not in outcome.added:
                problems.append(f"atom {atom.id}: {title} doesn't cite {atom.citation}")
    return problems


def _provenance(outcomes: Mapping[str, Outcome], ctx: PlanContext) -> list[str]:
    digest_type, digest_state = ctx.facts.rules.direct_capture_digest
    problems: list[str] = []
    for outcome in outcomes.values():
        title = outcome.planned.title
        reserved = sorted({k for k, _ in outcome.planned.properties} & ASSISTANT_PROPERTIES)
        if reserved:
            problems.append(f"{title}: sets {', '.join(reserved)}, which the assistant manages")
        if outcome.before is not None:
            continue
        props = outcome.after.props
        if props.get("origin") != ctx.origin:
            problems.append(f"{title}: origin must stay {ctx.origin!r} (§12)")
        if not props.get("aliases"):
            problems.append(f"{title}: needs aliases in both languages (§15 rule 5)")
        if props.get("type") == digest_type and props.get("digest") != digest_state:
            problems.append(
                f"{title}: a new {digest_type} note gets digest: {digest_state} (§19.6)"
            )
    return problems


def _topic_gap(plan: SplitPlan, outcomes: Mapping[str, Outcome], ctx: PlanContext) -> list[str]:
    rules = ctx.facts.rules
    problems: list[str] = []
    gaps: list[str] = []
    for outcome in outcomes.values():
        gap = outcome.after.prop("handbook_gap")
        if not gap:
            continue
        gaps.append(str(gap))
        if outcome.after.path.parent.as_posix() != rules.inbox:
            problems.append(
                f"{outcome.planned.title}: waits on a handbook gap, so it goes to the Inbox"
            )
        if outcome.after.prop("needs_review") is not True:
            problems.append(
                f"{outcome.planned.title}: waits on a handbook gap, so needs_review: true"
            )
    proposal = plan.topic_proposal
    if proposal is not None:
        if proposal.folder in rules.topics:
            problems.append(f"topic {proposal.folder!r} already exists; file the note there (§2.2)")
        if not any(proposal.folder in gap for gap in gaps):
            problems.append(f"topic {proposal.folder!r} is proposed but no note waits on it (§2.2)")
    return problems


def _rules(outcomes: Mapping[str, Outcome], ctx: PlanContext) -> list[str]:
    return [
        f"{o.planned.title}: {v.code} {v.message} ({v.section})"
        for o in outcomes.values()
        for v in new_violations(o.before, o.after, ctx.facts)
    ]
