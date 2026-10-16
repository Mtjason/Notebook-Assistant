---
type: project-doc
project: "[[Obsidian note assistant]]"
status: draft
created: 2026-10-17
updated: 2026-10-17
aliases: [Two-stage classification check, 分類不確定性檢查]
---

# Proposal: two-stage check on classification uncertainty

**Status: deferred. Not part of the proof of concept.** Nothing here is built or binding. When this
is picked up, it becomes a handbook amendment (Handbook §15) plus changes to
`maintenance-job.md` and `architecture.md`, and this file is deleted, so there is still one source
for each fact.

## Problem

The extraction planner (`maintenance-job.md`, Extraction) lets the model decide where each piece of
a capture goes. Code enforces the hard rules, and every changeset waits for approval, but nothing
tells you *which* placements were close calls. Handbook §0.3 says an uncertain classification goes
to the Inbox for you to decide, without defining how "uncertain" is measured, so today the model
judges that for itself.

Evidence, from the first real eval run on 2026-10-17 (`uv-install-answer` fixture, `claude-sonnet-5`):
the model filed the general `curl … | sh` note under Software instead of Systems. Both are
defensible from Handbook §2.3 (Systems covers the shell; tie-breaker 3 sends installing a tool to
Software). It made the call without hesitation, and nothing flagged it for review.

## Design

Measure uncertainty in two stages: a cheap signal on every capture, and an expensive check only
when the cheap one fires.

```
capture → plan (1 call) → stage 1: signal from the plan itself
             │
    low ─────┴──────── high
     │                    │
  propose normally     stage 2: self-consistency (plan again N times)
                          │
                 placements agree ───── placements differ
                          │                    │
                  propose normally      ask: note → Inbox (Handbook §0.3),
                  (marked "checked")    review card shows the competing placements
```

**Stage 1: the plan shows its work.** Each atom in the split plan also states the rule that decided
its placement (a Handbook §3 row or tie-breaker) and its runner-up placement, if any. The signal is
high when the atom needed Handbook §2.3 tie-breaker 4 ("still two candidates"), names a runner-up,
or two rules point to different folders. It costs no extra model call.

**Stage 2: self-consistency.** Plan the same capture again N more times, with the same or a
different model, and compare where each atom lands. If they agree, propose normally; otherwise the
note waits in the Inbox with `needs_review` and `handbook_gap`, and the review card lists each
placement with how many runs chose it.

**Always a review card.** "Propose normally" still means a pending changeset you approve. The
stages only decide between *propose* and *ask*, never between *ask* and *apply*.

## Configuration

New `Config.md` settings (their defaults would go in `src/notebook_assistant/default_config.md`):

| Setting | Meaning |
|---|---|
| `uncertainty.enabled` | Run the stages at all |
| `uncertainty.extra_runs` | N, the number of extra plans stage 2 makes |
| `uncertainty.model` | Model for the extra runs (empty: the planner's own model) |
| `uncertainty.agreement` | Share of runs that must agree on a placement for it to pass |

## How we'd know it works

Uncertainty is only useful if it's **calibrated**: high where the model is wrong, low where it's
right. The digestion eval (`maintenance-job.md`, Tests) measures both per atom:

- **Missed errors:** wrong placements that stage 1 rated low. They'd be proposed without a
  warning, so the target is zero.
- **Needless questions:** captures that stage 2 sends to you although the placements were right.
- **First test case:** on the 2026-10-17 run, the Software vs Systems placement must trip stage 1.

Calibration on one capture proves little, so this waits until the fixture set holds several real
captures from test checkpoint 1 (`architecture.md` §5.4.2).

## Open questions

- Is stage 1 a separate field per atom (`rule`, `runner_up`), or one per planned note?
- Does stage 2 compare atom placements only, or also create vs patch?
- How is the cost shown before a stage-2 run, given the monthly spend cap in `Config.md`?
