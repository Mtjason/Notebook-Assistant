---
type: project-doc
project: "[[Obsidian note assistant]]"
status: draft
created: 2026-09-26
updated: 2026-09-27
aliases: [Maintenance job, 定期整理, Sweep job]
---

# Maintenance job design

This is the implementation behind Handbook §16. Summary: you write raw notes anywhere, and when you click **Sweep changes** the job detects what changed and proposes changesets that bring the vault back into compliance with the handbook. **It never runs on its own** (Handbook §16.6); the only automatic job is daily session retention.

## Pipeline

```
Detect → Settle → Lint → Triage → Transform → Validate → Queue → (you approve) → Apply → Record
```

| Stage | Uses AI? | What it does |
|---|---|---|
| **Detect** | No | Walk the vault and hash every `.md` and `.canvas` file. Compare against each note's `assistant_hash` and the snapshots in `99-System/Assistant/`: new, edited (hash changed), moved (known hash at a new path), deleted. |
| **Settle** | No | Skip files still being written (settle time: Handbook §16.2). |
| **Lint** | No | Check the invariants I-1…I-6, required properties, enum values, tag registry, unique titles and orphans for **every** note. This is cheap, so it runs on all notes. |
| **Triage** | No | Route each changed or non-compliant note to a handler (table below). Mechanical violations get deterministic fixes, with no AI involved. |
| **Transform** | Yes | For notes that need judgment: send the note (plus the diff, for edits), the handbook, the tag registry, the MOC list and the top-k related notes (for dedupe and links) to Claude. It returns a **structured changeset**: a list of typed operations, not free text. For raw captures this goes through the **extraction planner** (see *Extraction: digesting and splitting captures*). |
| **Validate** | No | Reject the changeset if it fails: the schema check, the invariant check on the *resulting* state, or the content-preservation check (below). |
| **Queue** | No | Store the proposal with the note's **base hash** (its fingerprint at the time the proposal was made). Surface it on the Review screen (`design.html`). |
| **Apply** | No | Only after approval, and only if the note's current hash still equals the base hash (otherwise the proposal is stale). Renames and moves rewrite every link to the note in the same operation, and the invariant checker verifies no link broke. |
| **Record** | No | Write the new `assistant_hash` and snapshot into the vault and mark the changeset record `applied`; the changelog is a view over those records (Handbook §15.9). |

`top-k related notes` means the k most similar existing notes found by search (keyword plus embeddings), usually k = 5–10.

## Triage handlers

| Case | Detection | Handler |
|---|---|---|
| New raw note | No `type` in frontmatter | Full classification → possibly several new notes, plus a rename/move |
| Raw text appended to an organized note | Diff against the last snapshot shows added hunks | Integrate the added hunks only |
| In-place edit of an organized note | Diff shows modified lines | Lint only; no rewording |
| User move | Known hash at a new path, and the folder type ≠ `type` | Propose a `type` change, or flag `needs_review` |
| Deletion | Hash vanished | Repoint or remove dangling links |
| Mechanical lint violation | Lint | Deterministic fix, grouped into one batch |
| Deep pass | **Deep pass** button | Merge candidates (Handbook §8.2), missing links, contradictions, image descriptions |

A **diff** is the line-by-line difference between two versions of a file. A **hunk** is one contiguous block of changed lines.

## Extraction: digesting and splitting captures

Correctly digesting a capture and **splitting it into the right notes** is a core requirement, as important as not losing content. A capture that lands as one blob, or whose general lesson is buried inside one specific note, is knowledge you'll never find again. Rules: Handbook §3.1 (mixed notes, one capture → many notes, **instance vs. principle**), §19.3 (drafts generalize) and §19.6 (direct captures are digested right away).

**One planner, every entry point.** `app/extract.py` is shared by every path that turns raw material into notes, so they all split the same way:
- a capture pasted or dropped into chat, or `/digest` (§19.6: runs immediately);
- **Approve to digest** (§19.2);
- the Inbox (`feat/capture`) and emails;
- **Sweep changes** on a new raw note, or raw text added to an organized note.

### Steps

| # | Step | AI? | What it does |
|---|---|---|---|
| 1 | **Segment** | Yes | Break the capture into **atoms**: one procedure step, one explanation, one fact, one credential, one task, one general rule. An atom is the smallest piece that could be looked up on its own. |
| 2 | **Classify** | Yes | Run each atom through the decision order (§3): its type, and its topic folder (§2.3). |
| 3 | **Generalize** | Yes | For every explanation, ask: *does this hold beyond this one case?* If yes, it's a **principle** atom headed for a `knowledge` note. The specific case keeps only what's unique to it. Example: the curl flag explanation holds for every `curl … \| sh` installer, not just uv. |
| 4 | **Match** | No, then yes | Find existing notes for each atom: titles, aliases, `key` / `service` (§15.3), then top-k search. Prefer **patching**: a new section, new rows in a collection (§8.3), or a `## History` line (§9.1). Create a note only when nothing fits. |
| 5 | **Plan** | — | Output a **split plan**: atom → target note (new or existing) → operation → role (`instance` / `principle` / `extracted`). Plus the links: instance → principle, principle → instance (as an example), both → MOC. |
| 6 | **Verify** | Partly | Claims the capture got wrong or left incomplete are corrected **only** with a cited source (e.g. official docs), and the correction is noted in `## History`. Anything unsupported goes in a `> [!question] Unverified` box. `origin: ai-chat` stays until you verify it. |
| 7 | **Validate** | No | Deterministic checks on the whole plan: **coverage** (every atom lands in exactly one note; the content-preservation check runs across the set of result notes, not per note), **no duplicated explanation** (a principle's text isn't repeated in the instance note), **links resolve both ways**, and invariants on every resulting note. Failing plans are discarded and retried once. |

The split plan is typed data, not prose. The model proposes it; code validates and turns it into changeset operations. Where each part lives: the plan's shape and roles in `domain/split_plan.py`, the step-7 checks in `domain/plan_checks.py`, turning planned notes into notes in `domain/plan_notes.py`, and the planner in `app/extract.py` (each module's docstring is the reference). When the changeset is applied, the handbook rules are checked once more (`app/apply.py`), whatever produced it.

### Review card

A capture's changeset opens with its **split map**: the capture on the left, the notes it produced on the right, one line per atom with its role and whether it's new or a patch. Per-note diffs follow. You can reassign an atom to a different note, or reject one, before applying.

### Worked example: the uv install answer (2026-09-27)

Capture: a pasted AI answer explaining `curl -LsSf https://astral.sh/uv/install.sh | sh` and `source ~/.bashrc`.

| Atom | Role | Went to |
|---|---|---|
| Install uv, reload PATH, verify | instance | `SOP - Install uv (Linux)` (patch: step, Gotchas, Related, History) |
| What `-L -s -S -f`, `\|` and `sh` do, and why | principle | `curl pipe to shell install` (new knowledge note, Systems) |
| Why `source` is needed after installing, bash vs. zsh | principle | same note |
| One-line entries for the flags, `\| sh`, `source` | extracted | `Bash commands` (rows added to the collection) |
| "source ~/.bashrc" is imprecise; the installer prints `source $HOME/.local/bin/env` | correction | Both notes, citing the uv installation docs |

The first pass missed the principle note: it filed everything under uv. That's exactly the failure this section exists to prevent.

### Tests

- **Fixture captures** under `tests/fixtures/captures/`, each with an expected split plan (target notes, roles, links). The uv answer is the first case.
- **Assertions:** every atom covered, the principle note exists and is linked both ways, no explanation duplicated, existing notes patched rather than duplicated.
- **Digestion eval set:** prompt or model changes are judged by the difference they make on the whole set, like the golden vault tests. `notebook-assistant eval-extract --vault tests/fixtures/vault --captures tests/fixtures/captures` plans every capture with the real model on an in-memory copy of the vault and scores it against `expected.yaml`; the unit tests replay a recorded answer (`plan.json`) instead, so they need no API key.

## State

All job state lives in the vault: see `architecture.md` §4.1.

## Two PCs, no coordinator

Both PCs run the same service. Correctness never depends on only one of them running:

- **Clicks run where you click.** Approve to digest immediately sets `digest: approved` and `digest_runner: <machine>` plus a start time. The other PC sees that and skips the item. A run that hasn't finished within `coordination.stale_run_minutes` (`Config.md`, `architecture.md` §4.1.1) counts as abandoned, and either PC may retry it.
- **Sweeps run where you click them.** A sweep writes `sweep_runner: <machine>` into its run record; if the other PC shows a sweep running, the button is disabled there until it finishes or goes stale (the same limit).
- **The daily retention job takes a lease.** Before running, a PC writes itself into `Lease.md` with an expiry time, and a PC that sees an unexpired lease held by the other skips it.
- **Duplicates are harmless anyway.** Sync lag can let both PCs act within the same few seconds. Every write carries a base-hash check (is the note unchanged since the job read it?), and proposals are deduplicated by fingerprint. A double run therefore produces one result, never a conflict.

## Content-preservation check

Before any proposal reaches you, it must pass a check that nothing was lost:

1. Split the original into atomic units: sentences, list items, table cells, code blocks, URLs, numbers, embeds and wikilinks.
2. Every **code block, URL, number, embed and link** must appear **exactly** somewhere in the resulting note(s).
3. Every **sentence or list item** must match some sentence in the result above the similarity threshold (`checks.preservation_similarity` in `Config.md`, `architecture.md` §4.1.1; normalized, so reformatting is fine but dropped content is not).
4. Any failure discards the proposal and logs it. The note is retried once; after that it's flagged `needs_review`.

This check is deterministic code. It doesn't rely on the model saying it kept everything.

## Loop and conflict safety

- The job's own writes update `assistant_hash` at apply time, so they're never detected as user edits.
- Base-hash check at apply time: if you edited the note after the proposal was made, the proposal is discarded as stale.
- **Both PCs run the service**; see *Two PCs, no coordinator*.
- A note flagged `assistant: skip` is filtered out at Detect.

## Runtime, distribution and build order

See `architecture.md` §5.4 (release and install) and §5.4.1 (feature branches).

## Digest button flow


```
Web UI  [Approve to digest] ──POST /digest {path, base_hash}──▶ local service
                                                                │ set digest: approved, digest_runner: <this PC>
                                                                │ gather note + screenshots + linked notes
                                                                │ Claude call (Handbook §19.3 rules)
                                                                │ content-preservation + base-hash checks
        progress ◀──────────── server-sent events ──────────────┤
                                                                ▼
                                             write draft, set digest: review
        [Approve to graduate] ──▶ status: evergreen, origin: own, MOC link, close learn task
        [Send back] + feedback ──▶ digest: pending, digest_feedback
        [Graduate as-is] ──▶ (placement proposal if unplaced, confirmed in the same dialog) → status: evergreen, graduated_via: direct; canvas → companion note
```

**Server-sent events** (SSE) are a one-way HTTP stream the service uses to push progress to the page.
