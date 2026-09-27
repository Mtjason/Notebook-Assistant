---
type: project-doc
project: "[[Obsidian note assistant]]"
status: draft
created: 2026-09-27
updated: 2026-09-27
aliases: [notebook-assistant architecture, 架構設計]
---

# notebook-assistant: architecture

Three parts: a **web UI** (chat plus approval screens), a **backend** that owns every runtime tool, and a **data layer** that keeps all durable state in the vault. It complements *Maintenance job design* (sweep, digestion, file operations) and the Vault Handbook (the rules).

---

## 1. Principles

1. **The vault is the database.** Anything that can't be recomputed lives in the vault as Markdown. Anything that can be recomputed (search index, embeddings, link graph, tree) is a local cache that can be deleted at any time.
2. **One tool registry.** Every capability is defined once as a typed tool. The chat agent, the HTTP API and the background jobs all call the same tool, so behavior can't drift between them.
3. **Read freely, write by proposal.** Tools that change the vault only produce changesets. Changesets are applied only through the approval path, which runs the checks: invariants, content preservation, base hash, link integrity.
4. **The domain has no I/O.** Rules, note model and changeset logic are pure code. Files, Claude, Bitwarden and the index are adapters behind interfaces, so each can be swapped or faked in tests.
5. **Both PCs are equal.** No machine-local state except caches and per-machine settings (vault path, API key, `bw` available).

---

## 2. Frontend

### 2.1 Layout

```
┌───────────┬──────────────────────────────────────┬─────────────────────┐
│ Nav       │ Main                                 │ Context panel       │
│           │                                      │                     │
│ Chat      │  Chat thread (streaming)             │ Notes cited in the  │
│ Inbox (3) │   answer with [[citations]]          │ current answer      │
│ Digest(32)│   ┌ Changeset card ───────────┐      │  - preview          │
│ Review    │   │ move  …   [✓] [✗]          │      │  - Open in Obsidian │
│ Incubator │   │ patch …   [✓] [✗]          │      │                     │
│ Tasks     │   │ [Apply selected]           │      │ Pinned notes (@)    │
│           │   └───────────────────────────┘      │                     │
│ Sessions  │  ┌ composer ──────────────────────┐   │ Scope: All ▾        │
│  today    │  │ @note  /command  📎 drop files │   │                     │
│  earlier  │  └───────────────────────────────┘   │                     │
└───────────┴──────────────────────────────────────┴─────────────────────┘
```

### 2.2 Chat

| Feature | Behavior |
|---|---|
| Ask | Answers come from your notes first, with every claim citing a note (`[[…]]`). Clicking a citation opens a preview in the context panel, with **Open in Obsidian** |
| Request actions | "Merge these two Kedro notes", "Turn this thread into an SOP", "Archive everything about the PC purchase". The agent answers with a **Changeset card**, the same component as the Review screen: approve or reject each operation, then Apply |
| `@` mentions | Pin notes as context: `@Polars LazyFrame`. Autocompletes titles and aliases in both languages |
| `/` commands | `/capture`, `/find`, `/digest <note>`, `/summarize <folder>`, `/sop`, `/undo` |
| Drop files | Screenshots, PDFs, emails. Saved to `Attachments/` and captured as a `source` note (Handbook §12), then usable in the conversation |
| Paste to digest | Knowledge pasted into chat (or `/digest`) is digested **immediately** (Handbook §19.6): the extraction planner splits it into every note it yields, including the general principle behind a specific case (§3.1). The result is one changeset card with a split map (*Maintenance job design*, Extraction) |
| Scope | All / Work / Personal / a folder. Limits both retrieval and actions |
| Save to vault | On any answer. Creates a knowledge draft (`digest: review`) with `source` pointing to the session |
| Credentials | Credential cards with **Copy username** / **Copy password**. The secret goes from Bitwarden to the clipboard and is never shown or sent to the model |
| Sessions | Listed in the sidebar and read from the vault, so a conversation started on the work PC continues on the personal PC |

### 2.3 Rendering

- **Obsidian-flavored Markdown:**
  - `[[wikilinks]]` and `![[embeds]]` (images and notes)
  - callouts, and properties shown as a header block
  - tasks, tables, footnotes
- **Code** highlighted with Shiki (a syntax-highlighting library using VS Code's grammars).
- **Math** with KaTeX (a fast LaTeX math renderer), since the statistics notes use formulas.
- **Mermaid** diagrams.
- **HTML output** (charts, reports the agent generates) in a sandboxed iframe.

### 2.4 Stack

- **React + TypeScript**, built with **Vite** (a fast bundler).
- **TanStack Query**, a server-state caching library, for data fetching.
- **unified/remark** Markdown pipeline with custom plugins for wikilinks, embeds and callouts.
- **Streaming** over server-sent events (SSE); a WebSocket isn't needed because the browser only sends ordinary requests.
- **Packaging:** the build output is bundled into the Python package, so neither PC needs Node.js.

---

## 3. Backend

### 3.1 Layers (ports and adapters)

**Ports and adapters** (hexagonal architecture): the core defines interfaces ("ports"), and the outside world plugs in through implementations ("adapters").

```
            ┌──────────────── api/ (FastAPI: HTTP + SSE) ────────────────┐
            │                                                            │
  jobs/ ───▶│  app/ use cases: Ask · Capture · Classify · Digest ·       │
 (buttons,  │                  Graduate · ApplyChangeset · Undo · Sweep  │
  retention)│        │ calls                                             │
            │        ▼                                                   │
            │  tools/ registry (typed tools, permission tier per tool)   │
            │        │ uses                                              │
            │        ▼                                                   │
            │  domain/ pure: Note · Changeset · Operation · Handbook     │
            │          rules · invariants · content-preservation · links │
            └────────┬───────────────────────────────────────────────────┘
                     │ ports (interfaces)
     ┌───────────────┼──────────────┬──────────────┬──────────────┐
     ▼               ▼              ▼              ▼              ▼
 VaultStore      LLM            Index          SecretStore     EventBus
 (filesystem)   (Claude API)   (SQLite FTS5   (Bitwarden CLI) (in-process
                                + vectors)                     → SSE)
```

### 3.2 Package layout

```
notebook-assistant/
├─ pyproject.toml
├─ src/notebook_assistant/
│  ├─ domain/          names.py · frontmatter.py · note.py · links.py · schema.py (handbook as data)
│  │                   · invariants.py · preserve.py · changeset.py · ids.py        (pure, no I/O)
│  ├─ app/             index.py (files + link graph) · rename.py · apply.py (+undo) · canvas.py
│  │                   · later: extract.py (split planner, shared) · ask.py · capture.py · classify.py · digest.py · graduate.py · sweep.py
│  ├─ tools/           registry.py · read/ · propose/ · external/     (one file per tool)
│  ├─ agent/           loop.py (tool-use loop) · prompts/ · context.py (retrieval, prompt-cache layout)
│  ├─ ports/           vault.py · later: llm.py · index.py · secrets.py · events.py   (interfaces)
│  ├─ adapters/        fs_vault.py · memory_vault.py · later: claude.py · sqlite_index.py · bitwarden_cli.py · email_import.py · sse.py
│  ├─ platform/        detect.py · profiles.py · clipboard/ · opener/ · autostart/ · watch.py   (the only OS-aware code, §5)
│  ├─ store/           changesets.py · snapshots.py · runs.py · lease.py · later: sessions.py   (vault-backed state)
│  ├─ jobs/            runner.py (async queue, per-note locks) · retention.py (the only scheduled job)
│  ├─ api/             routes/ · schemas.py · sse.py
│  ├─ web/             built frontend (static)
│  └─ config.py        per-machine settings (pydantic-settings)
├─ frontend/           React source
└─ tests/              unit · contract (both adapters) · property-based · golden (your vault, local only) · e2e
```

### 3.3 Tool registry

Every tool is a class with a Pydantic input/output schema, a description (which also becomes its Claude tool definition), and a **tier**:

| Tier | Examples | Rule |
|---|---|---|
| `read` | `search`, `read_note`, `read_image`, `tree`, `backlinks`, `query_properties`, `read_session` | Always allowed |
| `propose` | `propose_create`, `propose_patch`, `propose_move`, `propose_merge`, `propose_archive` | Return a changeset; nothing is written |
| `apply` | `apply_changeset`, `undo_changeset` | Only through the approval endpoint, never callable by the model |
| `external` | `bw_copy_password`, `bw_find_item` | The model sees metadata only; secrets never enter the context |

**New capabilities are added as new tool files and registered through Python entry points** (a packaging mechanism that lets installed code announce plugins). The core never changes to add one, which is what keeps it scalable.

### 3.4 Agent loop

- A plain **tool-use loop** on the Anthropic Python SDK: the model calls tools, and the loop runs them and feeds back the results until the model answers. The loop is ~150 lines we own and can test, which is simpler than a heavier framework.
- **Context layout for prompt caching:**
  - handbook, tool definitions and tag registry → fixed prefix, cached;
  - session summary and pinned notes → next;
  - retrieved notes and the current turn → last.
- **Retrieval:**
  - hybrid search: keyword (BM25 with jieba tokenization for Chinese) plus vectors;
  - then link expansion: pull in the MOC, backlinks and the notes' own sources;
  - then a token budget.
- **Guardrails:**
  - a tool-call limit per turn;
  - the model can't call `apply` tools;
  - notes marked `sensitive` are shown to the model with secret values masked.

### 3.5 Jobs and concurrency

- An **asyncio job queue** in the service. **Only your clicks enqueue note jobs** (digest, graduate, sweep, lint, deep pass, archive check). The one scheduled job is daily session retention (Handbook §16.6).
- **File changes never start processing.** The file watcher only keeps the per-PC search index and the UI counts fresh.
- **Per-note locks** prevent two jobs touching the same note.
- **Every job is idempotent** (running it twice gives the same result) and records a run line in the vault.
- **Progress events** go on the event bus → SSE → UI.
- **Two PCs** coordinate as described in *Maintenance job design*: click runs where clicked (`digest_runner`), the daily retention job takes the lease, base-hash checks make double runs harmless.

### 3.6 Quality bar

- **Domain:** 100% unit-tested. Rules are data plus small functions, one per handbook rule, each naming its section (`§4.2`).
- **Extraction tests:** fixture captures with expected split plans, plus a digestion eval set (*Maintenance job design*, Extraction). Splitting correctly is a requirement, not a nice-to-have.
- **Golden tests:** run locally against your real vault (`NA_REAL_VAULT`): every note passes the handbook checks, and every untouched note re-renders byte-identically. Rule or prompt changes are judged by the difference they make there.
- **Property-based tests** for link rewriting (random renames must never break a link). Property-based testing generates many random inputs to check that a stated property always holds.
- **Contract tests** per adapter, so the fake and real vault/LLM/index behave the same.
- Type-checked with mypy (strict), linted with ruff, CI on GitHub Actions.
- **Cost and token accounting** per session and per job, recorded in the vault.

---

## 4. Data: what lives where

### 4.1 In the vault (durable, synced)

```
99-System/Assistant/
├─ Config.md                     shared settings: model per task, spend cap, retention (§4.1.1)
├─ Preferences.md                conventions learned from your approvals/rejections — readable, editable
├─ Sessions/2026/09/2026-09-27 0251 Frontend and backend design.md
├─ Changesets/2026-09/cs-01J8….md   every proposal: pending / applied / rejected / reverted
├─ Snapshots/<note-id>.md        last approved body per note (for diffs and "what did you add")
├─ Runs/2026-09.md               one line per job run
└─ Lease.md                      which PC runs the daily retention job
```

#### 4.1.1 `Config.md`: everything tunable is configuration

Models, limits and toggles are read from this note at startup and whenever it changes, never hard-coded. Editing it goes through a changeset like any other note.

```yaml
---
type: system
kind: config
models:                       # one entry per task; any model ID the API accepts
  classify: claude-haiku-4-5-20251001     # triage, placement, lint explanations
  transform: claude-sonnet-5              # sweep restructuring, capture extraction
  digest: claude-opus-5-5                 # screenshots + drafting (§19)
  chat: claude-sonnet-5
  fallback: claude-sonnet-5               # used if a configured model is unavailable
limits:
  monthly_spend_usd: 30       # AI jobs pause when reached; the UI shows month-to-date cost
  max_tokens_per_job: 60000
retention:
  sessions_days: 90
sweep:
  mode: manual                # manual only (Handbook §16.6)
  settle_minutes: 30
capture:
  email_formats: [eml, msg]
---
```

Per-machine settings (vault path, profile, `features.bitwarden`, search option) stay in the local config file, not here.

**Sessions** (one file per conversation):

```yaml
---
type: system
kind: session
id: ses-01J8…
title: Frontend and backend design
started: 2026-09-27T02:51+08:00
device: personal-pc
model: claude-…
scope: all
notes_cited: ["[[Polars LazyFrame dt error]]", …]
changesets: ["[[cs-01J8…]]"]
tokens: {in: 48210, out: 6120}
---
## 02:51 · You
…
## 02:52 · Assistant
… answer with [[citations]] …
> [!tool]- search("polars dt")      ← folded; the tool call and a short result summary
```

- **Append-only:** each turn is added at the end and never rewritten. That keeps Obsidian Sync merges trivial if both PCs touch the same file.
- **Linked both ways:** because sessions link the notes they cite, each note's backlinks show "discussed in" sessions.
- **Summaries for long sessions:** these get a rolling `## Summary` block that the agent reads instead of the full transcript.
- **Searchable everywhere.** Sessions appear in Obsidian's search and in the assistant's retrieval. Only `Changesets/`, `Snapshots/` and `Runs/` are hidden from Obsidian search (excluded files).
- **Kept 90 days.** A daily retention job queues deletion of sessions older than 90 days as one batch you approve. It is the only automatic job.
  - Anything worth keeping should be saved with **Save to vault** before then.
  - A changeset that came from a deleted session keeps its title and date as plain text, so the record of why a change was made survives.

**Changesets** replace the separate Proposals and Rejections files. One note per changeset holds:
- `status`, `created_by` (a session, the sweep, or a button) and `base_hash` of every target;
- the operations as a fenced JSON block;
- a unified diff per note, so you can read exactly what changed;
- the **reverse operations**. **Undo** replays them if the note is still at the post-change hash; otherwise it proposes a merge.

`Changelog.md` becomes a Bases view over applied changesets instead of a hand-appended file.

### 4.2 On each PC (derived cache, rebuildable)

`index.sqlite` in the OS cache directory (§5.1: `%LOCALAPPDATA%\notebook-assistant\` on Windows, `~/.cache/…` on Linux and WSL, `~/Library/Caches/…` on macOS), built from the vault:
- **Full-text index:** SQLite FTS5 with jieba-segmented Chinese.
- **Vectors (optional, per PC):** sqlite-vec, a SQLite extension for vector search. See §4.3 for the embedding model.
- **Link graph:** outgoing links, backlinks, embeds.
- **Tree and properties table:** folder tree, type, status, topic, digest per note.

It's rebuilt incrementally from file mtimes and content hashes (a full rebuild of ~200 notes takes seconds). Deleting it loses nothing.

**Why the tree and index aren't stored in the vault:**
- They can be recomputed from the vault.
- A stored copy would go stale between syncs.
- Embeddings are large binary data that would bloat Obsidian Sync.
- Both PCs writing the same index file would conflict.

If you want a human-readable map, the assistant can regenerate a read-only `Vault map` note nightly.

---

### 4.3 Search and embeddings (CPU only)

v1 ships keyword search. Meaning-based search is an optional add-on that each PC can switch on for itself.

| Option | Size on disk | RAM while indexing | First index of the vault on a laptop CPU* | Quality (Chinese + English) |
|---|---|---|---|---|
| Keyword only: BM25 + jieba (v1 default) | a few MB | < 200 MB | seconds | exact terms only; aliases in both languages cover a lot |
| multilingual-e5-small, int8 ONNX | ~120 MB | ~0.5 GB | about 1–3 min | good |
| bge-m3, int8 ONNX | ~0.6 GB | ~1.5–2 GB | about 5–15 min | best of these |

\*Estimates for ~1,000 chunks (≈ 200 notes). After the first run only changed notes are re-embedded, so day-to-day cost is seconds. The service measures the real numbers on each PC at setup.

- **Embeddings are computed per PC** (they're cache, not state), so each machine can choose. For example: bge-m3 on the personal PC, e5-small or keyword-only on the work PC.
- Models run on the CPU with ONNX Runtime, a lightweight inference engine; no GPU or PyTorch needed.
- Retrieval merges keyword and vector results (reciprocal rank fusion) when vectors are on. It works identically, just keyword-only, when they're off.

## 5. Platforms, development and release

One codebase runs on four hosts. It detects the host at startup and picks a **profile**, a named set of adapters (the swappable implementations behind the `ports/` interfaces). Nothing outside `platform/` and `adapters/` may check which OS it's running on.

### 5.1 Supported hosts

| Profile | When it's chosen | Vault access | Change detection | Clipboard | Open in Obsidian | Start at login |
|---|---|---|---|---|---|---|
| `windows` | `sys.platform == "win32"` | native NTFS | `watchfiles`, which uses ReadDirectoryChangesW (Windows' change-notification API) | Win32 clipboard API | `os.startfile("obsidian://…")` | Task Scheduler (`schtasks`) |
| `wsl-drvfs` | Linux, the kernel string contains `microsoft`, and the vault is under `/mnt/<drive>/` | drvfs over 9P (WSL's bridge to Windows drives; slow for many small files) | **polling** by mtime and hash, because inotify, Linux's change notifications, doesn't see edits made by Windows programs | `clip.exe`, or PowerShell `Set-Clipboard` for non-ASCII | `explorer.exe "obsidian://…"` | Windows Task Scheduler running `wsl.exe -d <distro> -- notebook-assistant serve …` |
| `linux` | Linux, and either not WSL or the vault is on a Linux filesystem | native | `watchfiles`, using inotify | `wl-copy` (Wayland) or `xclip` (X11) | `xdg-open` | systemd user unit, a background service tied to your login |
| `macos` | `sys.platform == "darwin"` | native APFS | `watchfiles`, using FSEvents (macOS's change-notification API) | `pbcopy` | `open` | launchd LaunchAgent, macOS's per-user startup service |

**Every profile also:**
- runs Bitwarden through the `bw` CLI found on `PATH` (`bw.exe` on Windows). It's disabled on that machine if missing;
- keeps its cache in the OS cache directory, via `platformdirs` (a library that returns the standard per-OS folders):
  - `%LOCALAPPDATA%\notebook-assistant\` on Windows
  - `~/.cache/notebook-assistant/` on Linux and WSL; never on `/mnt/c`, because SQLite locking over 9P is unreliable
  - `~/Library/Caches/notebook-assistant/` on macOS

**Overriding detection:** `--profile` or `VA_PROFILE=` overrides it, for example to force polling on a network drive.

### 5.2 Vault rules that don't depend on the host

The vault can sync to any OS later, so file operations apply the **strictest combined rules** on every host, including Linux:

- **Forbidden in names:**
  - the characters `< > : " / \ | ? *`;
  - control characters;
  - a trailing dot or space;
  - Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`).
- **Case-insensitive uniqueness.** NTFS and APFS (the default macOS setup) are case-insensitive, so `Note.md` and `note.md` count as the same name even on ext4 (case-sensitive Linux).
- **Unicode normalized to NFC.** NFC is the composed form; macOS can return filenames in NFD, the decomposed form. Names are normalized before comparing or storing, so `é` stored two ways is still one name.
- **Length:** names ≤ 100 characters, and vault-relative paths ≤ 200 characters. This keeps Windows under its 260-character path limit.
- **Paths are stored vault-relative, with `/`.** Use `PurePosixPath` for stored paths and `pathlib` for disk access. Never string concatenation.
- **Always UTF-8.** Every `open()` passes `encoding="utf-8"`, and the launcher sets `PYTHONUTF8=1` (Python's UTF-8 mode). Traditional-Chinese Windows otherwise defaults to cp950 (Big5) and would corrupt 中文 notes. A lint rule, meaning an automated code check, rejects any `open()` without an encoding.
- **Line endings:** each file keeps the ones it has. Use `newline=""` on read and write, and LF for new files.
- **Atomic writes:** write a temp file in the same folder, then `os.replace` it over the original. Temp names use an extension Obsidian and Sync ignore. On Windows, a `PermissionError` (Obsidian, Sync or antivirus holding the file) is retried with backoff. If it keeps failing, the note is marked busy and retried on the next run.

### 5.3 Machine identity

Each installation generates a `machine_id` (a UUID plus a friendly name such as `personal-pc`) on first run and stores it in its per-machine config. It isn't derived from the hostname, so a WSL install and a Windows install on the same PC are different machines to the lease and `digest_runner` logic, and both stay correct.

### 5.4 Development and release

```
Any dev machine (WSL today)      GitHub Actions                      Every PC
───────────────────────────      ──────────────                      ────────
code + tests against a    push   matrix: ubuntu · windows · macos
fixture vault            ─────▶  1. lint + unit + contract tests      tag v0.x.y
(never the real vault)           2. build the frontend (Node) ──────▶ uv tool install <wheel URL>
                                 3. build one py3-none-any wheel      notebook-assistant autostart install
                                    with the frontend inside
                                 4. install the wheel on each OS
                                    and run a smoke test
                                 5. attach the wheel to a GitHub Release
```

- **A wheel** is a prebuilt Python package file. `py3-none-any` means it's pure Python for any OS. Compiled dependencies (onnxruntime, sqlite-vec, pydantic-core) publish their own wheels for Windows, Linux and macOS (x86-64 and ARM).
- **No Node is needed on target machines.** Installing from a release wheel, rather than `git+https://…`, avoids building the frontend on the target.
- **Private repo:** release downloads need a GitHub token on each PC.
- **The fixture vault** (`tests/fixtures/vault/`) is small and synthetic: it covers every link form, a canvas, a code-tree file, an archive note and a CRLF note. **Your real notes never go into the repository.** The golden tests run against your vault locally when `NA_REAL_VAULT` points at it, and they are read-only. `.gitattributes` marks the fixtures `-text`, so git never rewrites their line endings.
- **Contract tests** run each adapter against the same expectations on every OS, e.g. rename-with-link-rewrite, case-only renames, NFD input, a locked file.
- **One feature branch at a time:** `feat/<name>` off `main`, merged by pull request only when CI is green on all three OSes. Releases are tags on `main`.

### 5.4.1 Feature branches, in order

| # | Branch | Delivers |
|---|---|---|
| 1 | `feat/core-vault` | Note model, frontmatter, handbook rules as code, invariant checker, content-preservation check, link-safe rename/move, vault-backed store (changesets, snapshots, runs, lease) |
| 2 | `feat/service-shell` | FastAPI service, SSE, web app shell (nav, top bar, context panel, Markdown renderer), platform profiles, `doctor`, CI and release wheel |
| 3 | `feat/review` | Changesets end to end: Review screen, diff view, apply with base-hash check, undo. Changesets can carry a typed **split plan**; the Review screen shows it as the split map, and reassigning or rejecting an atom recompiles the plan into operations in code (no model call) |
| 4a | `feat/extract` | Extraction planner (`app/extract.py`: segment, classify, generalize, match, plan, verify, validate), LLM port with a fake for tests, split-plan schema, validators (coverage, no duplicated explanation, links both ways), fixture captures and an eval runner. CLI `notebook-assistant digest --text <file>` for paste-to-digest before chat exists. **Test checkpoint 2 follows this branch** |
| 4b | `feat/digest` | Digest screen on top of the planner: Approve to digest (note + screenshots), Approve to graduate, Send back, Graduate as-is |
| 5 | `feat/capture` | Inbox: text, screenshots, `.eml` and `.msg` → Markdown source notes, split through the extraction planner into placement proposals |
| 6 | `feat/sweep` | Manual Sweep changes, Lint, Deep pass, Archive check; daily session retention |
| 7 | `feat/views` | Tasks and Incubator screens |
| 8 | `feat/search` | Per-PC index (FTS5 + jieba), global search, Sessions screen |
| 9 | `feat/chat` | Chat with citations and changeset cards; credential cards on the personal PC |
| 10 | `feat/embeddings` | Optional CPU embeddings per PC |

### 5.4.2 Test checkpoints with you

Short hands-on sessions (20–30 min) right after the branch that first makes something usable, so problems surface before later branches build on them. Each pull request carries a checklist; findings go into a test-log note in `99-System/Assistant/` and are fixed in a small follow-up branch before the next feature branch.

| # | After | What you test | Where |
|---|---|---|---|
| 1 | 2 `service-shell` | Install the wheel, `doctor`, open the app, browse notes, approve and undo a rename, start at login | Both PCs (the TI one first) |
| 2 | 4a `extract` | Digest real captures with `notebook-assistant digest`: is the split right (atoms, instance vs. principle, patch vs. create)? | Personal PC, then TI |
| 3 | 6 `sweep` | Inbox with raw notes, `.eml`, `.msg`, screenshots; hand edits then Sweep and Lint; two-PC sync | Both |
| 4 | 9 `chat` | A week of normal use: chat, search, sessions, paste-to-digest, credential cards (personal PC) | Both |

### 5.5 CLI

| Command | Does |
|---|---|
| `notebook-assistant serve --vault <path>` | Starts the service and web UI on `127.0.0.1:<port>` (local-only) |
| `notebook-assistant doctor` | Checks the host: the detected profile, a write test in the vault, the encoding, the file-watch mode, `bw` status, whether `api.anthropic.com` is reachable, and a benchmark of the chosen search option |
| `notebook-assistant autostart install\|remove` | Registers the service with the profile's start-at-login mechanism |
| `notebook-assistant update` | Installs the latest release wheel |
| `notebook-assistant index rebuild` | Rebuilds the per-PC cache |

### 5.6 Current machines

- **Personal PC:** `windows` for daily use; `wsl-drvfs` or `linux` with the fixture vault for development. Bitwarden enabled.
- **Work PC:** `windows` only. WSL is blocked from the user profile there, and nothing needs WSL on that machine. Bitwarden disabled (`features.bitwarden: false`); credential cards show the note's non-secret fields only.
- **Future Linux or Mac:** install the same wheel. `doctor` confirms the profile; no code changes are needed.

## 6. Decisions

| Decision | Choice |
|---|---|
| UI | Standalone local web app; Obsidian stays the editor |
| State | All durable state in the vault; per-PC caches only |
| Sessions in search | Yes: visible in Obsidian search and to the agent |
| Session retention | 90 days; a daily job queues deletion for approval (the only automatic job) |
| Note processing | Manual only: nothing runs on a timer or on file changes |
| Models and limits | Configuration in `Config.md`, one model per task, monthly spend cap (§4.1.1) |
| Email capture | `.eml` and `.msg` converted to Markdown source notes |
| Digesting and splitting | One shared extraction planner for chat, Digest, Inbox and Sweep. Captures are split into atoms; a general principle taught through a specific case gets its own knowledge note, linked both ways (Handbook §3.1, §19.6) |
| Meeting audio | Not supported; meetings are text only |
| Bitwarden | Personal PC only |
| Build order | Feature branches 1–10, with 4 split into 4a `extract` and 4b `digest` (§5.4.1); chat last |
| Embeddings | v1 keyword only; optional CPU embeddings per PC (§4.3) |
| Platforms | One codebase, host profiles `windows` · `wsl-drvfs` · `linux` · `macos`, detected at startup (§5) |
| Vault file rules | Strictest combined rules (Windows + macOS + Linux) on every host |
| Distribution | One `py3-none-any` wheel per release, built and tested by CI on Windows, Linux and macOS |
| Work PC | Native Windows; no WSL |
