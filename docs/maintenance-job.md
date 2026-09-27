---
type: project-doc
project: "[[Obsidian note assistant]]"
status: draft
created: 2026-09-26
updated: 2026-09-26
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
| **Settle** | No | Skip files modified less than 30 minutes ago. |
| **Lint** | No | Check the invariants I-1…I-6, required properties, enum values, tag registry, unique titles and orphans for **every** note. This is cheap, so it runs on all notes. |
| **Triage** | No | Route each changed or non-compliant note to a handler (table below). Mechanical violations get deterministic fixes, with no AI involved. |
| **Transform** | Yes | For notes that need judgment: send the note (plus the diff, for edits), the handbook, the tag registry, the MOC list and the top-k related notes (for dedupe and links) to Claude. It returns a **structured changeset**: a list of typed operations, not free text. |
| **Validate** | No | Reject the changeset if it fails: the schema check, the invariant check on the *resulting* state, or the content-preservation check (below). |
| **Queue** | No | Store the proposal with the note's **base hash** (its fingerprint at the time the proposal was made). Surface it in the sidebar review UI. |
| **Apply** | No | Only after approval, and only if the note's current hash still equals the base hash (otherwise the proposal is stale). Renames and moves rewrite every link to the note in the same operation, and the invariant checker verifies no link broke. |
| **Record** | No | Write the new `assistant_hash` and snapshot into the vault and append to `99-System/Changelog.md`. |

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
| Deep pass | **Deep pass** button | Duplicate candidates, missing links, contradictions, image descriptions |

A **diff** is the line-by-line difference between two versions of a file. A **hunk** is one contiguous block of changed lines.

## State: everything lives in the vault

The assistant is **stateless**. Any installation on any PC can pick up exactly where another left off, because all state is in the vault and travels with Obsidian Sync.

| State | Where | Format |
|---|---|---|
| Per-note workflow (digest, review, needs_review, sensitive) | The note's own properties | YAML frontmatter |
| Processed fingerprint | `assistant_hash` property on each note: hash of the last approved body | frontmatter |
| Last approved content (for "integrate only what you added") | `99-System/Assistant/Snapshots/<note-id>.md` | Markdown |
| Changesets (pending, applied, rejected, reverted), with diffs and reverse operations for undo | `99-System/Assistant/Changesets/YYYY-MM/<id>.md` | frontmatter + JSON block of operations + unified diffs (see *Assistant architecture* §4) |
| Chat sessions | `99-System/Assistant/Sessions/YYYY/MM/<date time title>.md` | append-only transcript |
| Run log | `99-System/Assistant/Runs/YYYY-MM.md` | one line per run |
| Retention lease (which PC runs the daily session-retention job) | `99-System/Assistant/Lease.md` | holder, expires |
| Shared settings (model per task, spend cap, retention) | `99-System/Assistant/Config.md` | frontmatter (see *Assistant architecture* §4.1.1) |

**Rules**
- **No dot-folders** (e.g. `.assistant/`). Obsidian Sync skips hidden folders other than `.obsidian`, so state there wouldn't reach the other PC.
- **Only Markdown.** State files are `.md`, so they sync even if "sync all other file types" is off. They're also readable by you.
- `99-System/Assistant/` is added to Obsidian's *Excluded files*, so snapshots and proposals don't clutter search or graph view.
- **Per-machine settings are not state.** The vault path, the API key (an environment variable, never in the vault), and whether `bw` is installed stay on each PC. Features that need something missing (e.g. Bitwarden on the TI PC) switch off on that machine only.

## Two PCs, no coordinator

Both PCs run the same service. Correctness never depends on only one of them running:

- **Clicks run where you click.** Approve to digest immediately sets `digest: approved` and `digest_runner: <machine>` plus a start time. The other PC sees that and skips the item. A run that hasn't finished within 15 minutes counts as abandoned, and either PC may retry it.
- **Sweeps run where you click them.** A sweep writes `sweep_runner: <machine>` into its run record; if the other PC shows a sweep running, the button is disabled there until it finishes or goes stale (15 minutes).
- **The daily retention job takes a lease.** Before running, a PC writes itself into `Lease.md` with an expiry time, and a PC that sees an unexpired lease held by the other skips it.
- **Duplicates are harmless anyway.** Sync lag can let both PCs act within the same few seconds. Every write carries a base-hash check (is the note unchanged since the job read it?), and proposals are deduplicated by fingerprint. A double run therefore produces one result, never a conflict.

## Content-preservation check

Before any proposal reaches you, it must pass a check that nothing was lost:

1. Split the original into atomic units: sentences, list items, table cells, code blocks, URLs, numbers, embeds and wikilinks.
2. Every **code block, URL, number, embed and link** must appear **exactly** somewhere in the resulting note(s).
3. Every **sentence or list item** must match some sentence in the result with a similarity of at least 0.9 (normalized, so reformatting is fine but dropped content is not).
4. Any failure discards the proposal and logs it. The note is retried once; after that it's flagged `needs_review`.

This check is deterministic code. It doesn't rely on the model saying it kept everything.

## Loop and conflict safety

- The job's own writes update `assistant_hash` at apply time, so they're never detected as user edits.
- Base-hash check at apply time: if you edited the note after the proposal was made, the proposal is discarded as stale.
- **Both PCs run the service**; see *Two PCs, no coordinator*.
- A note flagged `assistant: skip` is filtered out at Detect.

## Runtime and distribution

- **One GitHub repo**, installed the same way on both PCs. For example: `uv tool install git+https://github.com/<you>/notebook-assistant`.
  - `uv tool install` installs a Python command-line app into its own isolated environment.
- **One command:** `notebook-assistant serve --vault "<path>"`. It starts the local service and the web UI on `http://localhost:<port>`. Windows Task Scheduler starts it at login.
- **The frontend is prebuilt and shipped inside the Python package**, so the TI PC needs Python/uv but not Node.js.
- **AI calls** go to Claude via the API. The handbook and tag registry form a fixed prompt prefix, so prompt caching applies.
- **Bitwarden** is used through the `bw` CLI, only on machines where it's installed and unlocked. Secrets are always piped to the clipboard and never returned to the UI or the model (see the earlier Bitwarden design).

## Build order

One feature branch at a time, in the order listed in *Assistant architecture* §5.4.1:

1. core vault;
2. service shell;
3. review;
4. digest;
5. capture (including `.eml`/`.msg`);
6. sweep and retention;
7. views;
8. search;
9. chat;
10. embeddings.

## UI: an independent local web app (not an Obsidian plugin)

The assistant's UI is a local web app served by the service. Obsidian stays the editor and reader of notes.

| Need | Web app | Obsidian plugin |
|---|---|---|
| Rich rendering (Markdown, HTML, charts, side-by-side diffs) | Full control. HTML output renders in a sandboxed iframe | Limited to Obsidian's views |
| Bitwarden actions | The service calls `bw` directly | Possible, but each action must go through Obsidian |
| Works with Obsidian closed | Yes | No |
| Same on both PCs, one install | Yes | Needs installing per vault plus the service anyway |
| Opening a note | `obsidian://open?vault=…&file=…` deep links | Native |
| Link-safe renames and moves | The service rewrites links itself (the same logic the migration used, verified by its checker) | Native through Obsidian's API |

A tiny Obsidian plugin can be added later for "open this note in the assistant", but nothing depends on it.

### Screens

1. **Digest:** per-item **Approve to digest**, then **Approve to graduate** / **Send back**. Shows live progress, and a before/after view with screenshots next to the draft.
2. **Review:** proposals from the sweep and capture, with accept/reject per operation and "accept all mechanical fixes".
3. **Ask:** chat over the vault. Answers cite notes (clicking opens them in Obsidian) and credential cards have a Copy button (Bitwarden).
4. **Incubator and Tasks:** the same data as the Bases views, rendered richer.

### Button flow

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
