---
type: system
title: Vault Handbook
version: "2.13"
scope: personal
status: active
created: 2026-09-26
updated: 2026-09-28
aliases: [Handbook, 筆記手冊, 分類規則, Vault rules, Golden rule]
---

# Vault Handbook

This is the **golden rule** of the vault: every note, and every change to a note, must obey it. It is written for two readers:
- **You**, when you're unsure where something goes.
- **The note assistant**, which must follow it for every change it proposes.

Nothing is placed ad hoc. When a case isn't covered, the fallback rule (§0.3) applies and the handbook gets amended (§15). A rule is never bent for a single note.

**Single source of truth.** This file, `docs/handbook.md` in the Notebook-Assistant repository, is the only copy of the rules. The vault holds a link to it, never a copy. The assistant's code reads its rules from the tables in this file (§0.1, §2.1, §2.3, §3, §4, §5), so there is no second, hand-written schema. Every other document refers to a rule by its section number instead of restating it.

---

## 0. The contract

### 0.1 Invariants: every note, always

Every file in the vault satisfies all of these. The lint (§14) checks each one mechanically.

| # | Invariant |
|---|---|
| I-1 | It has exactly one `type` from the list in §4. |
| I-2 | It sits in the folder of its type (§2), or inside a container folder that allows that type (§2.1). |
| I-3 | It has every **required** property for its type (§4), with values from the allowed vocabulary. |
| I-4 | Its title is **unique vault-wide** and follows its type's naming pattern (§5). |
| I-5 | It has **at least one outbound link**: to its MOC, project/area, or source (§7). Exceptions: `00-Inbox/`, `01-Daily/`, `90-Views/`, `98-Templates/`, `99-System/`, and code-tree files (§11). A link inside a property (e.g. `topic`) counts. |
| I-6 | Its folder is at most **3 levels** below the vault root. Code folders inside projects are exempt (§11). |

**Scope:** the invariants apply to every Markdown note except those in `00-Inbox/`, `90-Views/`, `98-Templates/`, `Attachments/` and `99-System/Assistant/`. The Inbox holds unprocessed captures, Views and Templates hold Obsidian's own files, and `99-System/Assistant/` holds the assistant's machine-managed state (changesets, sessions, snapshots, run logs).

A note that breaks an invariant is non-compliant. It gets fixed or flagged; it is never left silently broken.

### 0.2 Precedence when rules conflict

**§0 invariants > §3 decision order > §3 tie-breakers > everything else.** If two rules still conflict, it's a handbook gap (§0.3).

### 0.3 Fallback: nothing is ever unclassifiable

If no rule decides where something goes, or the assistant's classification is uncertain:
1. It stays in (or goes to) `00-Inbox/` with `needs_review: true` and `handbook_gap: "<what the rules didn't cover>"`.
2. You decide the placement.
3. **The handbook is amended** so the same case is decided by a rule next time (§15). Once the rule exists, the note is placed.

---

## 1. Principles

1. **One note = one thing.** Tables are *views* generated from notes (with Bases), not hand-maintained lists. The exception is collections (§8.3).
2. **Folders say *type*. Properties say everything else. Links say how notes relate.** The only topic folders are one level inside `60-Knowledge/`.
3. **Shallow beats deep** (I-6).
4. **Findable in both languages.** Titles keep key technical terms in English; `aliases` carry the Chinese and English names.
5. **Provenance is kept** (`source:`, `origin:`).
6. **Archive before delete.** Deletion is limited to the cases in §8.4.
7. **Newer information updates notes; it doesn't fork them.** One truth per thing, with history kept inside the note (§9).

---

## 2. Folder map

```
00-Inbox/          Unprocessed captures, and anything flagged needs_review. Target: empty.
01-Daily/          Daily notes (YYYY-MM-DD). The capture log.
10-Tasks/          One note per task.
15-Incubator/      Ideas still forming: no goal or done condition yet. One folder per idea when it has several files.
20-Projects/       One container folder per project (has an end).
25-Areas/          One container folder per area (ongoing responsibility, no end).
30-SOPs/           Procedures: "how do I do X".
40-Reference/
  ├─ Credentials/  Access info per service.
  ├─ Resources/    Pointers to external things.
  ├─ Facts/        Single values you look up.
  └─ People/       Who someone is and what to ask them about.
50-Meetings/       Meeting and conversation records.
60-Knowledge/      Understanding: concepts, snippets, troubleshooting, collections, course notes.
  ├─ ML/  Data Science/  Statistics/  Software/  Systems/
  ├─ Semiconductor/  CS/  English/
70-Sources/        Original raw material after processing.
80-Writing/        Things you author for others: essays, story banks, drafts, posts.
90-Views/          Bases dashboards.
95-Archive/        Retired notes; mirrors the top-level folders.
98-Templates/      Obsidian note templates only, one per type.
99-System/         Link to the handbook, tag registry, lint reports, and the assistant's state (`Assistant/`).
Attachments/       All embedded files (images, PDFs…). Nothing else.
```

### 2.1 Container folders

`15-Incubator/<Name>/`, `20-Projects/<Name>/` and `25-Areas/<Name>/` are **containers**:
- Each has a hub note with the same name (`<Name>.md`, type `idea`, `project` or `area`).
- Besides the hub, a container may hold only **`project-doc`** notes, **`log`** notes, **canvases/drawings** belonging to it, and **code** (§11).
- Tasks, meetings, SOPs, facts and knowledge notes stay in their own folders and link to the hub via `project:` or `area:`.
- **Writing tied to one project** (e.g. application essays) lives in the container as `project-doc`. Standalone, reusable writing lives in `80-Writing/`.

### 2.2 Adding folders

**A new topic folder in `60-Knowledge/`** is proposed as soon as the first note needs it: when a capture fits none of the §2.3 topics, the assistant drafts an amendment adding a row to the §2.3 table (folder, what it answers, examples, what's not there), with its MOC. Until that amendment is merged, the note waits in `00-Inbox/` with `needs_review: true` and `handbook_gap` naming the proposed topic (§0.3); it is placed once the rule exists. A note that fits an existing topic never gets a new folder.

No other new top-level or sub-folders are created without amending this handbook.

### 2.3 Topic folders in `60-Knowledge/`

Pick the folder by **the question the note answers**, not by the tool it mentions.

| Folder | Answers | Examples | Not here |
|---|---|---|---|
| `ML/` | How a model is built, trained, evaluated or explained | Random forest, Shapley values, confusion matrix, Apriori, ML project layout | The data wrangling before modelling → Data Science |
| `Data Science/` | How to inspect, clean, reshape, query or visualize data | pandas, Polars, DataFrame joins, SQL queries, data profiling | Installing or configuring pandas or Polars → Software |
| `Statistics/` | Probability and statistics as mathematics, independent of any library | Distributions, CDF/PDF, Beta and Gamma functions, hypothesis tests | Metrics used to judge a model → ML |
| `Software/` | How to write, structure, configure, test or package code, and how to use frameworks and developer tools | Python packaging, uv and pip, environment managers, Kedro, Dagster, Next.js, testing tools, Claude Code | Using a data library to manipulate data → Data Science |
| `Systems/` | How the machine, OS, shell, network or security works | Bash, SSH, git, Docker, environment variables, HTTP, vulnerability scans | Language-specific tooling → Software |
| `Semiconductor/` | How fab processes, equipment and industry standards work | CMP pads, SEMI E10 states | ML on fab data → ML, with `scope: work` |
| `CS/` | Algorithms, data structures and computing theory | 2-3-4 trees, complexity | Code for one specific library → Software |
| `English/` | English grammar, vocabulary and speaking | Conditionals, phrase collections | Essays you write → `80-Writing/` |

**Tie-breakers, in order:**
1. **Model vs. data:** anything about a model's behaviour or quality is ML; anything about the dataset before modelling is Data Science.
2. **Math vs. practice:** a formula or theorem is Statistics; applying it to judge a model is ML, and applying it to describe a dataset is Data Science.
3. **Usage vs. setup:** using a library to do the work goes to the folder of that work; installing, configuring or troubleshooting the library itself goes to Software (or Systems, if it's an OS-level problem).
4. **Still two candidates:** choose the folder whose MOC you'd open first to look for it, and link the note from the other MOC.

The topic's MOC link in `topic` always matches the folder (I-2).

---

## 3. Where does a note go? (decision order)

Ask these questions **in order**; the first "yes" wins.

| # | Question | Type → Folder |
|---|---|---|
| 1 | Unprocessed, or uncertain? | → `00-Inbox/` (§0.3) |
| 2 | Something to do, find out, or learn, with a "done" condition? Includes open questions, things to study, and someday-ideas | `task` → `10-Tasks/` (§17) |
| 3a | Something you're still thinking through or constructing, with **no clear goal, roadmap or done condition yet**? | `idea` → `15-Incubator/` (§18) |
| 3 | A multi-step effort **with an end**? | `project` hub → `20-Projects/<Name>/` |
| 4 | An ongoing responsibility or life domain **with no end** (a standard to maintain)? | `area` hub → `25-Areas/<Name>/` |
| 5 | A design doc, plan, spec or essay that only makes sense inside one project/area? | `project-doc` → that container |
| 6 | A dated record of an activity (practice session, experiment run, debugging session, study log)? | `log` → its container, or `01-Daily/` if it has none |
| 7 | Steps to *reproduce an outcome* ("how do I install / set up / apply for X")? | `sop` → `30-SOPs/` |
| 8 | Login or access information? | `credential` → `40-Reference/Credentials/` |
| 9 | A single value to look up (path, ID, hostname, room, setting, date)? | `fact` → `40-Reference/Facts/` |
| 10 | A pointer to something external (URL, product, doc, dataset, course)? | `resource` → `40-Reference/Resources/` |
| 11 | About a person? | `person` → `40-Reference/People/` |
| 12 | A record of a meeting or conversation? | `meeting` → `50-Meetings/` |
| 13 | Something you author for an audience, reusable beyond one project (essay, story bank, speech, post)? | `writing` → `80-Writing/` |
| 14 | An explanation, snippet, fix, list of like items, or course material? | `knowledge` → `60-Knowledge/<Topic>/` |
| 15 | The original raw material something was extracted from? | `source` → `70-Sources/` |
| — | None of the above | → fallback (§0.3) |

The assistant also maintains three structural types that this decision order never assigns:

| Structural type | Folder |
|---|---|
| Daily note (§10) | `daily` → `01-Daily/` |
| Map of content (§7) | `moc` → `60-Knowledge/<Topic>/` |
| System note (this handbook's link, tag registry, lint reports) | `system` → `99-System/` |

### 3.1 Tie-breakers

- **Mixed notes** (one note containing several types, e.g. setup steps + a password + a hostname + an explanation):
  - The **primary purpose** decides the note's type.
  - Every embedded item of a *different* type that you'd look up on its own (credential, fact, person) is **extracted into its own note and linked**.
  - Explanations that serve the procedure stay inline.
- **Project vs. area:** the test is whether you can say when it's done. "Apply to grad school" is a project. "English ability" and "career" are areas. A project may belong to an area (`area:` on the project hub).
- **Project material vs. general knowledge:** it goes in the container only if it's meaningless outside the project. Otherwise it goes in `60-Knowledge/` and the hub links to it.
- **SOP vs. snippet:** an SOP has an outcome and ordered steps; a snippet is a reusable piece you adapt. If it's both, the SOP links to the snippet.
- **Fact vs. resource:** a fact *is* the value; a resource *points to* something.
- **Fact vs. task for dates:** a date you must act on is a task with `due`. A date that's only informational (exam date, contract end) is a fact.
- **Unfinished learning capture vs. knowledge:** a note that mostly lists things to look into, or fragments from a video, course or article you haven't digested yet, is not knowledge. It becomes a `learn` task (§17) that carries the raw capture as its context, with a checklist of what's left and a "done when" line. It's finished when the understanding is written into a knowledge note and linked in `produced`. A `knowledge` note with `status: seed` must already explain something, even if roughly.
- **Writing vs. knowledge:** writing is *your* output for an audience. Knowledge is understanding for *your own* use. A framework for writing speeches is knowledge; a speech you wrote is writing.
- **Obsidian templates vs. other templates:** `98-Templates/` holds only templates used by Obsidian's Templates plugin. Code templates and document templates (e.g. a project README template) are `knowledge` with `kind: snippet`.
- **One capture, many notes:** a single inbox item may produce several notes of different types. Each lands in its own folder, and all link to the same `source` when there is one. A pasted AI answer has none (§12), so its notes link to each other instead.
- **Instance vs. principle:** when a capture teaches a general rule through one concrete case (installing uv with `curl -LsSf … | sh` also teaches the general `curl … | sh` install pattern), record **both**: the concrete case as its own type (usually an `sop` or a `fact`), and the general rule as a `knowledge` note in its topic folder. The concrete note keeps only what is specific to it and links to the general note for the explanation. The general note uses the case as an example and links back. If a general note already exists, patch it instead of creating a new one (§15.3).

---

## 4. Properties (frontmatter)

**Frontmatter** is the `---`-delimited YAML block at the top of a note; Obsidian shows it as *Properties*, and Bases queries it.

- Property **keys** are English, lowercase, `snake_case`.
- **Enum values** (fixed-vocabulary values) are English; free-text values may be any language.
- **Required** properties (marked \*) must be present. If a required value is unknown, the note gets `needs_review: true`, never a guessed value. The exception is task defaults (§17.3).
- **Optional** properties are omitted when unknown, not left empty.
- Dates are `YYYY-MM-DD`. Links in properties are quoted: `"[[Note]]"`.

### 4.1 Common to every note

```yaml
type: *         # see §4.2
scope: *        # work | personal — see rule below
status: *       # see §4.3
created: *      # see §9.2 for migrated notes
updated: *
aliases:        # other names, both languages
tags:           # max 3, from the registry (§6)
source:         # "[[70-Sources/…]]" or "[[YYYY-MM-DD]]"
origin:         # own | ai-chat | web | colleague | course  (default: own)
needs_review:   # true only while flagged (§0.3)
assistant:      # skip — the maintenance job never proposes changes to this note (§16.4)
digest:         # pending | approved | review | graduated — digestion queue (§19)
id:             # assigned by the assistant the first time it changes the note; never edit (§5.2)
assistant_hash: # fingerprint of the last approved content; managed by the assistant (§16.1)
```

**Scope rule:** use `scope: work` if the information is only valid or usable inside your employer: internal hostnames, internal processes, internal tools, colleagues. Everything else is `personal`, **even if you learned it at work**. For example, Dagster concepts are `personal`, while the work VM hostname is `work`.

`origin: ai-chat` marks unverified AI-generated content. Change it to `own` once you've verified it.

### 4.2 Per type

**`topic`** is always a link to the topic's MOC, e.g. `topic: "[[MOC - Software]]"`. It is required on `knowledge` and allowed on every other type. It's how MOCs find their notes and how most notes satisfy I-5.

| Type | Required extra fields | Optional |
|---|---|---|
| `task` | `kind: action\|question\|learn`, `priority: p1\|p2\|p3` | `due`, `project`, `area`, `topic`, `waiting_on`, `recurrence` (e.g. `monthly`); learn tasks: `resource`, `outcome`, `effort`; question/learn tasks when done: `produced` (links to the resulting notes) |
| `idea` | `question` (what you're trying to figure out) | `next_step`, `promoted_to` |
| `project` | `started` | `area`, `ended`, `repo` |
| `area` | — | `review_every` (e.g. `quarterly`) |
| `project-doc` | `project`, `area` or `idea` | `kind: design\|plan\|spec\|essay\|notes` |
| `log` | `date` | `project`, `area` |
| `sop` | `domain`, `trigger`, `last_verified` | `platform: [linux, windows, mac]`, `est_time` |
| `credential` | `service` | `url`, `username`, `auth`, `sensitive: true` |
| `fact` | `key`, `value` | `context` |
| `resource` | `kind: doc\|tool\|product\|dataset\|repo\|course\|paper\|link` | `url` |
| `person` | — | `org`, `team`, `role`, `ask_about` |
| `meeting` | `date` | `attendees`, `project`, `area`, `decisions` |
| `writing` | `kind: essay\|story\|speech\|post\|draft` | `audience`, `project` |
| `knowledge` | `kind: concept\|snippet\|troubleshooting\|collection\|course-note`, `topic` | `platform`; troubleshooting notes add `symptom`, `fix` |
| `source` | `kind: text\|email\|chat\|image\|meeting-audio\|transcript\|file`, `captured` | `processed` |
| `moc` | `topic` | — |
| `daily` | `date` | — |
| `system` | — | `version` |

`domain` values for SOPs: `dev-env | IT | finance | facilities | admin | fab-tools | study | personal-admin`.

**Credentials:** secret values may stay in the note for now. Any note containing one gets `sensitive: true`, and the assistant never quotes those values in chat.

### 4.3 Allowed `status` values

| Type | Lifecycle |
|---|---|
| `task` | `someday → todo → doing → waiting → done` / `dropped` → `archived` |
| `idea` | `exploring → shaping → promoted` / `parked` / `dropped` → `archived` |
| `project` | `active → paused → done` / `dropped` → `archived` |
| `area` | `active → dormant` → `archived` |
| `project-doc`, `writing` | `draft → final` → `archived` |
| `sop` | `draft → active → stale → deprecated` → `archived` |
| `knowledge` | `seed → evergreen → deprecated` → `archived` |
| `credential`, `fact`, `resource`, `person` | `active → retired` → `archived` |
| `log`, `meeting`, `source`, `daily`, `moc`, `system` | `active` (archived only together with their container) |

- **someday:** an idea you might do, not committed.
- **seed:** rough or unverified. **evergreen:** refined and reliable.
- **stale:** an SOP not verified in more than 6 months.
- **deprecated:** superseded or no longer applicable.
- **dormant:** an area you're not actively maintaining right now.

---

## 5. Naming

| Type | Pattern | Example |
|---|---|---|
| task | Verb phrase; questions end with `？`; learn tasks start with `Learn` | `Submit OMSCS transcript`, `Why does import fail without __init__？`, `Learn Kedro hooks` |
| idea / project / area | Short name; container folder and hub share it | `Self-healing AI agent`, `RDBMS projector`, `English` |
| project-doc | Descriptive name | `Multi-source alignment design` |
| log | `YYYY-MM-DD <topic>` | `2026-06-20 Reading practice` |
| sop | `SOP - <verb> <object>` | `SOP - Install uv`, `SOP - 採購辦公設備` |
| credential | `Cred - <service>` | `Cred - Mage AI` |
| fact | `Fact - <key>` | `Fact - Work VM hostname` |
| resource | `<Name>` | `Lenovo ThinkPad Dock` |
| person | `<Full name>` | `Amy Chen` |
| meeting | `YYYY-MM-DD <topic>` | `2026-09-26 AO analyzer sync` |
| writing | Descriptive name | `Story and Reason bank` |
| knowledge | Topic name, key term in English | `Polars LazyFrame`, `條件句 As if` |
| source | `YYYY-MM-DD <kind> <subject>` | `2026-09-26 email Concur policy` |
| moc | `MOC - <topic>` | `MOC - Kedro` |
| daily | `YYYY-MM-DD` | `2026-09-26` |
| attachment | `<note title> - <n>.<ext>` | `Polars LazyFrame - 1.png` |

Rules:
- **Unique titles (I-4).** On a collision, first check whether it's a duplicate (merge per §8.2). If the notes are genuinely different, add a qualifier in parentheses: `Kedro hooks (Q&A)`.
- **No numeric ordering prefixes** (`0.`, `1.`, `2_`) and **no `!` prefixes**. Reading order belongs in MOCs.
- Title characters follow §5.1. Question-tasks therefore end with the full-width `？` instead of `?`.
- **Mixed language:** title in the language you'd search first; all other names go in `aliases`.
- **Knowledge titles:** `<tool or subject> <specific term>`, e.g. `Polars with_columns`, `Kedro hooks`, `Confusion matrix`. The tool name goes first so related notes sort together. Troubleshooting notes name the symptom: `Polars LazyFrame dt error`. No `How to`, `Note on`, dates or version numbers, unless the version is the subject.

### 5.1 File and folder names on every system

The vault syncs between Windows, macOS and Linux, so every name must be valid on all three at once:

- Characters never allowed in a file or folder name: `< > : " / \ | ? *`, and control characters.
- Characters also never allowed in a note title, because they break Obsidian links: `# ^ [ ]`.
- Reserved names, in any case and with or without an extension: `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`.
- No name ends with a dot or a space, or starts with a space.
- Names are compared case-insensitively after Unicode NFC normalization (the composed form), so `Note` and `note`, or `é` written two ways, are the same name.
- A name is at most **100** characters, and a path from the vault root at most **200**.

### 5.2 Renaming and moving

A note is renamed or moved **only** when:
1. It is being classified for the first time (raw capture → typed note).
2. Its `type` or topic changes, so its folder or naming pattern changes.
3. Its current name or location breaks a rule (§2, §2.3, §5), e.g. a misspelling or a forbidden character.
4. You ask for it.

Never for style alone. Every rename or move is one changeset that:
- computes the new name from §5, and checks it is unique (case-insensitive) and valid on Windows, macOS and Linux;
- **adds the old title to `aliases`**, so searches for it still find the note;
- rewrites every reference: wikilinks (including `|alias` and `#heading` forms), embeds, Markdown and path links, links in properties, and canvas nodes;
- verifies afterwards that no link broke. If one did, the whole changeset is rolled back.

The note's `id` never changes, so history, snapshots and changesets still point to it.

---

## 6. Folders vs. properties vs. tags vs. links

| Mechanism | Use it for | Don't use it for |
|---|---|---|
| **Folder** | Note type (plus one topic level in `60-Knowledge/`) | Topics, status, dates |
| **Property** | Anything filtered or sorted with a fixed vocabulary | Free-form themes |
| **Tag** | Cross-cutting themes, hierarchical with `/`: `#ml/xai`, `#tool/kedro`, `#course/cs1332` (max 3) | Anything already a property |
| **Link** `[[…]]` | Specific relationships | Categorizing |

**Tag registry:** allowed tags are listed in `99-System/Tags.md`. A new tag is added to the registry first, as part of the same changeset. Unregistered tags are a lint error. This prevents `#kedro`, `#Kedro` and `#tool/kedro` from all coexisting.

---

## 7. Links, MOCs, and external URLs

A **MOC** (Map of Content) is an index note that lists and orders every note on a topic, with a sentence of context per link.

- Every note satisfies I-5, at least one outbound link.
- Every `60-Knowledge/` topic folder has `MOC - <Topic>`. Sub-topics with 5+ notes get their own MOC, linked from the parent.
- Project and area hubs embed Bases views of their tasks, meetings and logs, and link to relevant knowledge notes.
- **External URLs:** keep a URL inline in the note that uses it. Create a `resource` note only when it's referenced from 2 or more notes, or when you'd look it up by name.

---

## 8. Note shape: body, split, merge, collections, delete

### 8.1 Body structure

- The filename is the title. **Don't repeat it as an H1**; the body starts at `##`.
- Each type has a body skeleton in `98-Templates/`. Minimum required sections:

| Type | Required sections |
|---|---|
| sop | `## Steps` (numbered), `## Gotchas`, `## Related` |
| troubleshooting | `## Symptom`, `## Cause`, `## Fix` |
| project / area hub | `## Goal` (project) or `## Standard` (area), `## Status`, `## Decisions`, views |
| meeting | `## Notes`, `## Decisions`, `## Action items` (links to tasks) |
| knowledge (concept) | free form, with a `## Summary` of 1–3 lines at the top |

- **Screenshots must be searchable.** Every image that carries information gets a short text description under it: what it shows, key terms, and the visible text.

### 8.2 Split and merge

**Split** when a note has two or more H2 sections that would each be searched separately, or when it's longer than about 1,500 lines. Course hand-outs are the exception: keep them whole.

**Merge** only when a pair of notes passes **all three gates** and matches **one trigger**. Otherwise the notes stay separate and get linked, digested (§19) or reclassified.

**Gates (all must hold):**
1. **Same subject.** Both notes answer the same question, or one is a sub-part of the other's subject. Sharing a tool, tag or topic folder is not enough.
2. **Same scope.** Both `work` or both `personal`. A `work` note never merges into a `personal` one: reclassify it instead (e.g. an internal-only command becomes a `fact`). Platform variants are the exception: the result takes the stricter scope.
3. **The target's type accepts the content** (§3). A fact, credential, person or task is never merged into another type; it is extracted and linked (§3.1).

| Trigger | Test | Result |
|---|---|---|
| Stub | Body under about 200 bytes (frontmatter excluded), and a related note passes the gates | A section in the related note. Facts and credentials are exempt. With no related note, the stub stays and goes to digestion (§19) or becomes a `learn` task (§3.1); a note is never created just to hold it |
| Platform variants | The same procedure or topic, differing only by OS | One note with a `platform:` list and a section per OS |
| Near-duplicate | Most of the smaller note's content already exists in the larger one | Keep the more complete note's title |
| Covered by a collection | Every item in the note is already a row of a collection (§8.3), and what's left is a sequence or a tip | The remainder becomes a section of the collection |

**Don't merge** when:
- each note would be searched on its own: a distinct subject with complete examples (typically over 1 KB), even if related. Link them instead;
- the two answer different kinds of question on the same topic (a comparison vs. an explanation of why);
- the result would meet the split rule above;
- either note is in `15-Incubator/` (§18.3) or `95-Archive/`, or is marked `assistant: skip`.

**How a merge is done** (one changeset):
- **Target:** the note the trigger names. Between two equal notes, the one with more incoming links. Its title stays unless it breaks §5.
- **Content:** moved verbatim into a section named after the old note's subject, with headings demoted to fit. Only conversational filler (e.g. an AI's closing question) may be dropped, and only when the review card lists it.
- **Names and links:** old titles and their aliases join the target's `aliases`. Every reference is rewritten (§5.2); in logs and reports the old name stays as display text: `[[New title|Old title]]`.
- **Properties:** `tags` are combined (max 3); `scope` and `sensitive` take the stricter value; `digest` takes the less processed state and keeps only the `digest_reason` values still true after the merge (a merged stub is no longer a stub); `created` takes the earlier date, `updated` is today; an SOP's `last_verified` takes the older date.
- **Record:** the target gets a `## History` line, and the old note is deleted (§8.4). The content-preservation check (§16.4) compares the old notes with the result.

**Finding candidates:** the Deep pass (§16.3) lists merge candidates with the trigger each one matches; nothing is merged without approval.

### 8.3 Collections

A list of like items (vocabulary, commands, installed packages, quotes, SQL snippets) is **one** `knowledge` note with `kind: collection`, not one note per item. An item **graduates** to its own note once it needs its own properties, status or links.

### 8.4 Delete

Delete only:
- Zero-byte notes and empty folders.
- Byte-identical duplicate attachments (hash-verified), after repointing their links.
- Notes whose entire content was merged into another note (§8.2).
- Inbox captures judged to be noise (no information worth keeping), **with your approval**.
- Assistant chat sessions (`99-System/Assistant/Sessions/`) older than 90 days, in one approved batch. Changesets that came from them keep the session's title and date as text.

---

## 9. Changing information over time

### 9.1 Updates and conflicts

- When new information **updates** a note, the note is edited in place, `updated` changes, and a dated line is added under `## History`: `- 2026-09-26: switched from micromamba to uv (reason…)`.
- When new information **contradicts** a note and it's unclear which is right, **don't overwrite**. Add a `> [!warning] Conflict` callout (a highlighted Obsidian box) with both versions and set `needs_review: true`.
- **Decisions** are recorded where they apply: in the project/area hub's `## Decisions`, or in the note's `## History`. Each entry has a date and a reason. A decision made in a meeting is recorded in both the meeting and the hub.

### 9.2 Dates for migrated notes

`created` = the earliest reliable evidence: the file's creation time, else the oldest timestamp embedded in the note (e.g. `Pasted image 20260605…`), else the file's modification time. `updated` = the file's modification time. After migration, the assistant sets `updated` on every applied change.

---

## 10. Special files

| File | Rule |
|---|---|
| **Canvas** (`.canvas`) | Canvases can't hold properties. Each canvas belongs to a container, a MOC, or a knowledge topic, lives next to it, and is **embedded or linked from a note** that carries the properties. A canvas with no owning note gets one created (a hub or a knowledge note) with the same name; its workflow state (digest, graduation) lives on that note (§19.5). A new canvas in `00-Inbox/` is picked up like any other capture. |
| **Excalidraw** (`.excalidraw.md`) | Treated like a canvas. It can hold properties; set `type` to match its owner's type and put it next to the owner. |
| **Attachments** (images, PDFs, docs) | Anything embedded in a note lives in `Attachments/`, flat. Rename to `<note title> - <n>.<ext>` when processed. |
| **Project-internal files** (files referenced by code, e.g. example diagrams in a repo) | Stay inside the project's code tree (§11). They are not attachments. |
| **Orphan attachment** (embedded by no note) | Flagged by lint; deleted only after your confirmation. |
| **Daily notes** | `01-Daily/YYYY-MM-DD.md`, type `daily`. They're a capture log: anything durable written there is **extracted** into typed notes during processing, and the daily note keeps a link to them. Daily notes are never archived or deleted. |

---

## 11. Projects with code

- A project container may hold code (`src/`, `tests/`, `README.md`, config files). Code folders are exempt from I-2 and I-6.
- **Code-tree files:** documents that the code or a coding agent reads by filename (e.g. `README.md`, an agent charter, design docs referenced from them) keep their names and get **no frontmatter**, because renaming them would break those references. The project hub links to them. They are exempt from I-1 to I-5.
- The hub note is the entry point. Design docs are `project-doc` notes next to it.
- The assistant **indexes and edits only `.md` notes with frontmatter and `.canvas` files** in containers. It never touches code, `README.md` or code-tree files unless you explicitly ask.
- Archiving a project moves the **whole container**, code included.

---

## 12. Sources and capture

- **Create a `source` note** for non-text captures (image, audio, email, file) and for long text captures (a transcript, or pasted text over about 30 lines), except pasted AI answers. The original is embedded or attached.
- **Short typed captures** don't get a source note: the extracted notes cite the daily note (`source: "[[2026-09-26]]"`).
- **Pasted AI answers never get a `source` note**, however long: what's kept is the digested understanding, not the chat. The extracted notes always get `origin: ai-chat`, and every correction the assistant made to the answer is recorded in their `## History`.
- **Emails** (`.eml`, or Outlook `.msg`) are always converted to a Markdown `source` note (`YYYY-MM-DD email <subject>`): sender, recipients, date and subject as properties, the body as Markdown, and attachments saved to `Attachments/` and embedded. The original file is attached too. Tasks, facts and SOP steps in the email are then extracted like any other capture. Credentials in an email follow §3.1.
- **Meetings** are captured as text only (your notes, or a transcript your meeting app produced). There is no audio capture.

---

## 13. Archiving

**Archiving** = moving a note into `95-Archive/` (mirroring its original top-level folder) and setting:
```yaml
status: archived
archived: 2026-09-26
archive_reason: "project finished" | "tool no longer used" | "superseded by [[…]]" | "process retired" | "area ended"
```
Links keep working. Archived notes are excluded from default views. To restore a note, move it back and reset its `status`.

| Type | Archive when |
|---|---|
| idea | `dropped`, or `promoted` for 30+ days (the whole container moves). `parked` ideas stay where they are |
| project | `done` or `dropped` for 30+ days (the whole container moves) |
| area | You've permanently stopped maintaining it (not merely `dormant`) |
| task | `done` or `dropped` for 90+ days |
| sop | The process no longer applies (tool retired, process changed). Staleness alone is not a reason |
| knowledge | `deprecated` **and** the tool or technique is no longer used. Concepts are never archived just for age |
| writing / project-doc | Its container is archived, or it's superseded |
| credential / fact / resource / person | `retired` |
| log / meeting / source / daily / moc | Only together with their container. Otherwise never |

**Don't archive** notes that are merely old but still true. **When unsure**, mark the note `deprecated` and let the monthly review decide.

---

## 14. Enforcement and review

- **Mechanical checks:** the lint validates every invariant (I-1…I-6), required properties, enum values, unregistered tags, duplicate titles, orphans, stubs, orphan attachments, stale SOPs and aging `waiting` tasks.
- The code reads its rules directly from the tables in this handbook (see *Single source of truth* at the top). There is no separate schema file.

| When | What | Who |
|---|---|---|
| Whenever | Capture into `01-Daily/` or `00-Inbox/` | You |
| Weekly (suggested) | Process the inbox to zero; review `waiting` tasks and `needs_review` notes | You start it; assistant proposes, you approve |
| Monthly (suggested) | Lint report (`99-System/Lint YYYY-MM.md`), then the archive sweep (§13), then the Incubator check (§18.4) | You start it; assistant proposes, you approve |
| Quarterly | Re-verify `stale` SOPs; review `deprecated` notes and `dormant` areas | You, with the assistant's list |

---

## 15. Rules for the assistant

1. **Proposals only.** Every create, edit, move, merge, rename or delete is a proposed changeset, applied only after approval.
2. **Obey this handbook exactly.** When uncertain or uncovered, use the fallback (§0.3) and propose a handbook amendment. Never improvise a placement.
3. **Deduplicate before creating:** search titles, aliases, `key` and `service`; prefer patching an existing note.
4. **Keep provenance:** `source:` and `origin:` on every extracted note.
5. **Both languages** in `aliases` on every note created or migrated.
6. **Never quote `sensitive: true` values** in chat.
7. **Stay out of `95-Archive/`** except to restore, and out of project code (§11).
8. **Rename and move per §5.2,** rewriting every reference in the same changeset.
9. **Every applied changeset is its own record** in `99-System/Assistant/Changesets/`: date, operations, reason and diff. The changelog is the Bases view `90-Views/Changelog.base` over those records, never a hand-kept list.

### Amending the handbook

- An amendment is a pull request to `docs/handbook.md` in the repository, never an edit in the vault. The assistant may draft one; nothing takes effect until it is merged and the assistant is updated.
- It bumps `version` (minor for new rules, major for rules that change existing placements) and is logged in *Version history* below.
- A major change comes with a migration changeset for the notes it affects, so the vault never contradicts the handbook.

---

## 16. Maintenance job

**Purpose:** you write raw, anywhere; the assistant brings every note into compliance with this handbook. You never need to organize by hand.

### 16.1 What counts as a change

On every run, the job compares the vault against its record of the last approved state and detects:
- **New files**, in any folder, not just `00-Inbox/`.
- **Edited files**, where the content hash differs from the last processed version.
- **Moved or renamed files**, where the same content appears at a new path.
- **Deleted files**, which leave dangling links behind.

A **content hash** is a short fingerprint of the file's content; any edit changes it. The job's own applied changes are recorded immediately, so they never re-trigger it.

### 16.2 Settle time

A note is processed only after **30 minutes without edits**. This means the job never works on a note you're still writing, or one Obsidian Sync is still syncing.

### 16.3 What the job may propose

| Situation | Proposal |
|---|---|
| New note with no frontmatter (raw text) | Classify it (§3) and add properties (§4). Restructure the body into its type's skeleton (§8.1). Extract embedded items into their own notes (§3.1). Rename and move it (§5, §2). Link it to its MOC or container (§7). |
| Organized note where you added raw text | **Integrate only the added part:** move it into the right section, extract other-type items from it, add a `## History` line if it updates something (§9.1), and update `updated`. |
| Organized note you edited in place | Keep your wording. Re-validate the invariants and fix only what now breaks, e.g. a new unregistered tag. |
| Note you moved to another folder | Your move is a signal: propose changing `type` to match the new folder. If the content clearly contradicts that type, flag `needs_review` instead. |
| Deleted note | Propose removing or repointing links that now point nowhere. |
| Lint violations anywhere | Mechanical fixes: missing `updated`, tag casing, a missing MOC link, and misspelled titles or folder names (e.g. `Englilsh` → `English`). |
| Note with `digest: approved` | Write the digestion draft and set `digest: review` (§19). |
| Weekly deep pass | Duplicate candidates (§8.2), missing links between related notes, contradictions between notes (§9.1), image descriptions (§8.1). |

### 16.4 What the job must never do

1. **Lose or change information.** Restructuring may move, split, or add text, but every piece of information in the original must still exist afterwards. The job checks this automatically before proposing, and any proposal that fails the check is discarded.
2. **Rewrite your wording** in organized notes. Only raw text it is integrating may be reformatted.
3. **Touch notes marked `assistant: skip`**, anything in `95-Archive/`, or project code (§11). **Restructure anything in `15-Incubator/`**: there it may only add properties and links (§18.3).
4. **Apply a stale proposal.** If a note changes after a proposal was made for it, the proposal is discarded and regenerated on the next run.
5. **Apply anything without approval** (§15.1).

### 16.5 Review

- **Mechanical fixes** from one run are grouped into a single batch you can accept at once.
- **Content changes** (classifying, restructuring, integrating, extracting, merging) get one review card per note, showing a before/after diff.
- Proposals you reject are remembered: the job does not propose the same change to the same content again.

### 16.6 Schedule: you start every run

**The job never processes notes on its own.** Nothing runs on a timer or on file changes. Each pass starts only when you click it in the assistant's app:

| Button | Scope |
|---|---|
| **Sweep changes** | Notes new or changed since the last approved state (§16.1), after settle time (§16.2) |
| **Lint** | Every note; rule checks only, no AI calls |
| **Deep pass** | Duplicates, missing links, contradictions, image descriptions (§16.3, last row) |
| **Archive check** | Archive candidates (§13), stale tasks (§17.6), the Incubator check (§18.4) |
| **Approve to digest / graduate** | One note, immediately (§19) |

**The one automatic job** is session retention: once a day it looks for assistant chat sessions older than 90 days and queues their deletion as a single batch for your approval (§8.4). It touches no other note.

Where other sections say "weekly" or "monthly", that's the suggested cadence for starting the matching button, not a schedule.

**Both PCs run the assistant.** It keeps no state of its own: everything lives in the vault under `99-System/Assistant/` and in note properties, so both installs behave identically. A lease note decides which PC runs each periodic sweep, and base-hash checks make an accidental double run harmless.

---

## 17. Tasks and learning items

You'll capture to-dos and things-to-learn constantly, in raw form, anywhere. This section defines how they're organized.

### 17.1 Three kinds of task

| `kind` | What it is | Done when | Example |
|---|---|---|---|
| `action` | Something to *do* | The action is complete | `Submit OMSCS transcript` |
| `question` | A specific question to *answer* | It's answered, and the answer is written into a knowledge note | `Why does import fail without __init__？` |
| `learn` | A skill, topic or resource to *study* | You've studied it **and** written what you learned into knowledge note(s) | `Learn Kedro hooks` |

**Closing the loop:** a `question` or `learn` task can only be marked `done` with a `produced:` property linking to the knowledge note(s) it created or updated. The point of learning something is that it ends up in `60-Knowledge/`. If one is marked done without `produced`, the job proposes a knowledge note stub from whatever you wrote, or flags it.

### 17.2 How raw captures are recognized

The maintenance job (§16) treats these as task captures **in any note** (daily note, inbox, or in the middle of a knowledge note):

| You write | Becomes |
|---|---|
| `- [ ] …` (a checkbox), `TODO …`, `待辦 …`, `要做 …` | `action` |
| `? …`, `Q: …`, `為什麼…`, `why …`, or a line ending in `?`/`？` that you mark as a question | `question` |
| `to learn …`, `要學 …`, `learn …`, `study …`, `read …` (paper, book, course), a bare URL with "learn/read later" | `learn` |
| `done …`, `完成 …`, or checking a box next to an existing task link | Marks the existing task `done` |

**What happens to the original line:** your wording stays, and a link to the new task note is appended (`要學 Kedro hooks → [[Learn Kedro hooks]]`), so the context you wrote it in is kept. The task note is the single source of truth for status. If the line was a checkbox, the checkbox is removed, so the status isn't tracked in two places.

**Checkboxes that stay checkboxes:** sub-steps inside a task, project or SOP note stay as inline `- [ ]` items. They're only promoted to their own task note when they get a due date, a `waiting_on`, or are referenced from elsewhere.

### 17.3 Defaults and inference

- `priority`: p2 if you didn't state one ("urgent" or "!" → p1; "someday" or "maybe" → p3). It's never flagged just for a missing priority.
- `status`: `todo`, or `someday` if phrased as maybe, someday, 有空再.
- `due`: relative dates ("Friday", "下週五", "end of month") are converted using the **capture date** (the daily note's date or the file's creation time), not the processing date.
- `topic`, `project`, `area`: inferred from the note the capture was found in and its content. Anything uncertain is left empty rather than guessed.
- **Duplicates:** a capture matching an open task (same intent) updates that task instead of creating a new one.

### 17.4 Grouping learning

- Every `learn` and `question` task has a `topic` matching a `60-Knowledge/` topic, or a tag.
- **Each MOC embeds its open learn and question tasks** under a `## To learn` section. When you open `MOC - Kedro`, you see what you know about Kedro and what you still plan to learn.
- **3 or more learn tasks with a shared goal** (e.g. "become fluent in Kubernetes", a course) → the job proposes a **learning project** in `20-Projects/` with those tasks linked. The project's `## Goal` states the outcome.
- **Courses you take** (e.g. an OMSCS course) are projects; the lectures and readings are learn tasks; course notes are `knowledge` with `kind: course-note`.

### 17.5 Views (in `90-Views/`)

| View | Shows |
|---|---|
| **Today** | Overdue, due today, and `doing` tasks |
| **Next** | `todo` tasks by priority, then due date |
| **Waiting** | `waiting` tasks and who you're waiting on, oldest first |
| **Learning queue** | Open `learn` and `question` tasks, grouped by topic |
| **Recently learned** | Learn and question tasks done in the last 30 days, with their `produced` notes |
| **Someday** | `someday` tasks, reviewed weekly |

The daily note template embeds **Today**.

### 17.6 Review

- **Weekly:** each `someday` task gets promoted to `todo`, kept, or `dropped`. `waiting` tasks older than 14 days get a nudge. Learn tasks untouched for 90 days are proposed for `someday` or `dropped`.
- **Monthly:** done or dropped tasks older than 90 days are archived (§13).

---

## 18. Incubator: ideas still forming

For things you're still thinking through or constructing without a solid roadmap. They aren't raw captures (the Inbox), they don't have a goal and done condition yet (a project), and they aren't settled understanding (knowledge).

### 18.1 What goes here

- A design you're sketching without a plan (e.g. *Self-healing AI agent*).
- A topic where you don't have the whole picture yet (e.g. *EBM ML learning*).
- A system or workflow idea you keep circling back to.

**Not** here: something you only need to *do* (a task), something you can already describe with a goal and an end (a project), or something unprocessed (the Inbox).

### 18.2 Shape

- One note (type `idea`) per idea. When it has several files (canvases, drawings, drafts), it gets a folder: `15-Incubator/<Name>/<Name>.md` plus the files. Those extra notes are `project-doc` with `idea: "[[<Name>]]"`.
- Required: `question`, one sentence on what you're trying to figure out. It keeps the idea findable and makes the monthly check easy.
- Optional: `next_step`, the one thing you'd do next if you picked it up.

### 18.3 What the assistant may do here

- Add or fix properties and links, and propose related notes.
- **Never** restructure, split, merge or reformat the content. Messy is allowed. The body skeletons (§8.1) and stub rules (§8.2) don't apply.

### 18.4 Lifecycle

| Status | Meaning |
|---|---|
| `exploring` | Early, open-ended |
| `shaping` | A direction is emerging |
| `promoted` | It became something else; `promoted_to` links to it |
| `parked` | Not now, but worth keeping. It stays in the Incubator but leaves the default view |
| `dropped` | Abandoned; archived |

- **Graduation.** It becomes a **project** once you can state a goal and a done condition, **knowledge** once it's settled understanding, or an **area** once it's an ongoing responsibility. The new note is created, the idea gets `status: promoted` and `promoted_to`, and it's archived 30 days later.
- **Monthly check.** For each live idea: still alive? An idea untouched for 90 days is proposed as `parked` or `dropped`. Nothing is parked or dropped without your approval.
- **View:** `90-Views/Incubator.base` lists live ideas with their question, oldest first.

---

## 19. Digestion: turning captures into solid knowledge

Many notes hold material you haven't digested yet: stubs, screenshot-only notes, raw captures from videos or courses, and pasted AI answers you haven't verified. They sit in a **digestion queue** and go through two approvals.

### 19.1 Properties

| Property | Values |
|---|---|
| `digest` | `pending → approved → review → graduated` (or back to `pending` if rejected) |
| `digest_reason` | one or more of `raw-capture`, `stub`, `screenshot-only`, `ai-unverified` |
| `digest_draft` | link to the draft note, when the draft is a new note (e.g. from a learn task) |
| `digest_feedback` | your comments when you send a draft back |

The maintenance job sets `digest: pending` whenever a note matches a reason. You can also set it yourself on any note.

### 19.2 The flow

| Step | You | The assistant |
|---|---|---|
| 1. Queue | See it in **Digest → Needs digestion** | Flags the note `pending` with its reasons |
| 2. **Approve to digest** | Click the item's **Approve to digest** button (one per item) | Starts **immediately**: sets `digest: approved`, reads the note text, **its screenshots** and linked sources, writes a draft (§19.3), then sets `digest: review`. You see progress on the item while it runs |
| 3. Review | Read the draft in **Digest → Ready to graduate**; edit freely | — |
| 4a. **Approve to graduate** | Click the item's **Approve to graduate** button | Makes it solid knowledge: `status: evergreen`, `origin: own`, linked from its MOC. For a learn task, the task is set `done` with `produced` linking the new note |
| 4b. Send back | Click **Send back** and type your feedback (saved as `digest_feedback`) | Returns to `pending`; the next **Approve to digest** redrafts using your feedback |
| **Shortcut: Graduate as-is** | Click **Graduate as-is** on any item, whether or not it's in the queue | Skips digestion (§19.5) |

Approving step 2 authorizes the assistant to write the draft. Nothing becomes solid knowledge without step 4a.

**Button behavior**
- Buttons act on **one item** and run **right away**. The maintenance job's settle time (§16.2) doesn't apply to an explicit click.
- If you edit the note while its digestion is running, the draft is discarded (the note changed under it) and the item returns to `pending`, with a message saying why.
- If digestion fails (network, model or content-check error), the item returns to `pending` with `digest_error` explaining what went wrong.
- Buttons live in the assistant's own web app, which runs on both PCs. A click runs on the PC where you clicked, which records itself in `digest_runner` so the other PC doesn't run it too.
- The properties stay the source of truth, so the buttons and hand-edited properties are interchangeable.

### 19.3 What a draft looks like

- **Knowledge notes** (stub, screenshot-only, AI-unverified) are rewritten in place into the §8.1 skeleton. The original text is kept at the bottom in a folded `> [!quote]- Original capture` box, so nothing is lost and you can compare.
- **Learn tasks** (raw capture) produce a **new knowledge note** in the right `60-Knowledge/<Topic>/` folder, linked from the task as `digest_draft`. The task keeps the raw capture.
- **Screenshots** are read and described in text; each claim taken from an image cites it ("screenshot 2").
- **Generalize:** if the material teaches a general rule through an example, the draft also proposes the general knowledge note (§3.1, instance vs. principle).
- **Anything not supported by your note, its screenshots or its linked sources** is marked in a `> [!question] Unverified` box. The assistant doesn't fill gaps with confident-sounding guesses.
- The content-preservation check (§16.4) still applies to every draft.

### 19.4 Views

`90-Views/Digest.base` has four views: **Needs digestion** (grouped by topic), **Digesting**, **Ready to graduate** and **Graduated**.

### 19.5 Graduating directly (no digestion)

Some notes are already finished when you make them, e.g. a canvas you've completed or a note you wrote carefully. For those, **Graduate as-is** skips steps 2 and 3.

- **Available on any** knowledge note, canvas or drawing, from anywhere: the Digest queue, the note's page in the assistant, or a note in `00-Inbox/`.
- **Your content is not changed.** The assistant writes no draft and no rewrite.
- **What it does:**
  - Sets `status: evergreen`, `origin: own`, `digest: graduated` and `graduated_via: direct`.
  - Removes any `digest_reason`.
  - Links the note from its MOC.
- **If the note isn't placed yet** (in the inbox, or missing its type or topic), the confirmation shows the proposed type, name and folder. One click confirms both the placement and the graduation. You can change the proposal before confirming.
- **Canvases can't hold properties**, so their graduation state lives on a companion note (§10):
  - If the canvas already has an owning note, that note is graduated.
  - If not, the assistant creates a knowledge note with the canvas's name. It holds the properties, embeds the canvas, and gets a short `## Summary` built only from the canvas's own text cards, so the canvas becomes searchable. That summary is the only text the assistant writes, and it's shown in the confirmation.
- **Excalidraw drawings** hold their own properties, so they're graduated directly.
- **Checks still apply:** the invariants (§0.1) and the link check. A graduation that would break a rule shows what's missing instead of proceeding.

### 19.6 Proactive digestion of direct captures

When you hand a capture to the assistant directly (pasted into chat, or sent with "digest this"), the assistant digests it **right away** instead of queueing it:

- In one changeset it extracts every note the capture yields (§3.1, including instance vs. principle), writes each in its type's final skeleton (§8.1), and patches existing notes rather than duplicating them (§15.3).
- New knowledge notes from it get `digest: review` (ready to graduate), not `pending`. They keep `origin: ai-chat` if the material came from an AI.
- Only the extraction is proactive. The changeset still needs your approval (§15.1), and nothing becomes solid knowledge without **Approve to graduate** (§19.2).

---

## Appendix A — Migration map (pre-2026-09 structure)

| Old location | New location | Type |
|---|---|---|
| `I/1. Concepts/*` | `60-Knowledge/{ML, Data Science, Statistics, Software, Systems}/` | knowledge |
| `I/1. Concepts/System/CLI and Terminal/0. Question buckets.md` | `60-Knowledge/Software/Python testing tools`, with each question or to-do extracted to `10-Tasks/` | knowledge + task |
| Empty notes whose title states an intent (`Airflow`, `Transitional words`) | `10-Tasks/`, status `someday` | task (kind: learn) |
| `…/Software and Coding/Keys.md` (actually a link to a data-structure article) | `40-Reference/Resources/Data file structure (freeCodeCamp)` | resource |
| `I/2. Hands-on/*`, install/setup | `30-SOPs/`, Linux/Windows variants merged | sop |
| `I/2. Hands-on/*`, snippets and command lists | `60-Knowledge/Software/` or `Systems/` | knowledge (snippet / collection) |
| `…/Unused tool/*` | `95-Archive/…` | archive_reason: tool no longer used |
| `…/0. Location record.md` | One note per row in `40-Reference/Facts/` | fact |
| `…/SW Project management/__init__.py/!Description Template.md` | `60-Knowledge/Software/` | knowledge (snippet) |
| `I/3. War room/Self-healing AI agent`, `EBM ML learning` | `15-Incubator/<Name>/` | idea + project-doc |
| `I/3. War room/Setup your terminal` (quick notes from a learning video) | `10-Tasks/Learn terminal setup from agentic workflow video` | task (kind: learn) |
| `I/1. Concepts/!Knowledge Lakehouse` (the old holding place for unclassified knowledge) | `15-Incubator/Knowledge lakehouse/` (only the working-flow sketch remains) | idea |
| `V/Office facility purchase/*` (plan cancelled) | `95-Archive/` | project, resources, fact — archived |
| `II/Projects/*` | `20-Projects/<Name>/`; code stays (§11) | project + project-doc |
| `II/Application/` | `20-Projects/Grad applications/` | project |
| `II/Englilsh/` | `25-Areas/English/` hub | area |
| `II/Englilsh/PinTOFEL`, `KO班`, `備考` | `95-Archive/20-Projects/TOEFL/` (a finished project) | project + course-note |
| `II/Englilsh/Practive/Reading/*` | Archived with TOEFL | log |
| `II/Englilsh/Grammer`, `單字片語`, `Improvise` | `60-Knowledge/English/` | knowledge (concept / collection) |
| `II/Englilsh/Explore myself/*` (story bank, about me) | `80-Writing/` | writing (story) |
| `II/Learning/*` | `60-Knowledge/CS/` | knowledge (course-note) |
| `III. Semiconductor/*` | `60-Knowledge/Semiconductor/` | knowledge; `scope: work` only for internal-system notes |
| `V/For Obsidian/` | `99-System/` | system |
| `V/Office facility purchase/!Note.md` (a dated purchase log, not a procedure) | `20-Projects/Office PC purchase/` | project + project-doc |
| `V/Office facility purchase/*` items | `40-Reference/Resources/` (quotes and products); `Our laptop` → `Fact - Team laptop model` | resource / fact |
| `V/For Obsidian/Plugins.md` | `30-SOPs/SOP - Install Obsidian plugins (Portable)` | sop |
| Notes with passwords/tokens | Steps stay per their type; secrets extracted to `Cred - <service>` | credential, `sensitive: true` |
| `Images/`, `X. Images/` | `Attachments/` (duplicates removed) | — |
| `!…` and `0. intro` notes | `MOC - <topic>` | moc |

## Appendix B — Glossary

- **Bases**: Obsidian's core plugin that shows notes as filterable, sortable tables built from their properties.
- **Frontmatter / Properties**: YAML metadata at the top of a note (§4).
- **Container**: a project or area folder that holds its hub plus its own docs, logs and code (§2.1).
- **MOC (Map of Content)**: an index note that curates and orders links on one topic (§7).
- **Invariant**: a condition that must be true for every note at all times (§0.1).
- **Lint**: an automated check that lists every note breaking a rule, like a code linter.
- **Orphan**: a note with no links, or an attachment no note embeds.
- **Changeset**: a batch of proposed operations that you approve or reject before anything is written.
- **Provenance**: where information came from (`source:`, `origin:`).
- **SOP (Standard Operating Procedure)**: a step-by-step procedure for a recurring task.
- **Evergreen / seed**: a refined, reliable note vs. a rough, unverified one.
- **Enum**: a property whose value must come from a fixed list.

## Version history

- **2.13 (2026-09-28):** The changelog is a Bases view over the applied changeset records (`90-Views/Changelog.base`) instead of a file the assistant appends to, so each change is recorded once (§15.9, §2, §3). The existing `99-System/Changelog.md` stays as the record of changes before 2.13; nothing is appended to it.
- **2.12 (2026-09-28):** Pasted AI answers never get a `source` note, whatever their length; their notes keep `origin: ai-chat` and record corrections in `## History` (§12). `ai-chat` removed from the source `kind` values (§4.2), and §3.1 says what the notes of a source-less capture link to.
- **2.11 (2026-09-28):** Merge criteria (§8.2): three gates (same subject, same scope, the target's type accepts the content), four triggers (stub, platform variants, near-duplicate, covered by a collection), when not to merge, and how a merge is carried out. Any fully merged note may be deleted, not only stubs (§8.4).
- **2.10 (2026-09-28):** A new topic folder is proposed with its first note instead of after 5 notes; the note waits in `00-Inbox/` until the amendment is merged (§2.2).

- **2.9 (2026-09-27):** Single source of truth: this file in the repository is the only copy of the rules; the vault keeps a link note instead of a copy, and the code reads its rules from this file's tables (top of the handbook, §14, §15). The folders exempt from the invariants are now stated in §0.1, the structural types `daily`, `moc` and `system` got folder rows in §3, and the task lifecycle in §4.3 includes `archived` (as §13 already allowed); all three were previously known only to the code.

- **2.8 (2026-09-27):** Added the instance vs. principle tie-breaker: a capture that teaches a general rule through one case produces both notes (§3.1). Captures handed directly to the assistant are digested proactively in one changeset (§19.6), and digestion drafts generalize (§19.3).
- **2.7 (2026-09-27):**
  - Added topic-folder definitions and tie-breakers for `60-Knowledge/` (§2.3). Moved 12 notes accordingly:
    - pandas and Polars notes, and Data profiling → Data Science;
    - Confusion matrix → ML;
    - Python environment managers → Software.
  - Added the knowledge title pattern and the rename/move rules (§5.1).
  - The maintenance job runs only when you start it; the only automatic job is session retention (§16.6).
  - Emails (`.eml`, `.msg`) become Markdown source notes, and meetings are captured as text only (§12).
  - Added the assistant-managed properties `id` and `assistant_hash` (§4.1), and exempted `99-System/Assistant/` state files from the invariants (§0.1).

- **2.6 (2026-09-27):** Assistant chat sessions are kept 90 days, then deleted in an approved batch (§8.4).
- **2.5 (2026-09-27):** Added **Graduate as-is** (§19.5): graduate a finished note, canvas or drawing directly without digestion, with placement confirmed in the same step and a companion note for canvases.
- **2.4 (2026-09-27):** The assistant is stateless and runs on both PCs (state lives in `99-System/Assistant/` and note properties). Buttons live in its local web app, not an Obsidian plugin.
- **2.3 (2026-09-27):** Digestion and graduation are triggered by per-item buttons and start immediately. Settle time does not apply to explicit clicks. Added handling for edits during digestion, failures, and clicks on a machine without the service (§19.2).
- **2.2 (2026-09-27):** Added digestion (§19): the `digest` property and queue, two approvals (approve to digest, approve to graduate), draft rules including reading screenshots and marking unverified content, and the Digest view.
- **2.1 (2026-09-27):** Added the tie-breaker for unfinished learning captures: they become `learn` tasks carrying the raw capture, not knowledge notes (§3.1). Terminal setup reclassified accordingly.
- **2.0 (2026-09-27):** Added `15-Incubator/` and the `idea` type for thinking still being formed (§18), with a decision-order step 3a, containers for ideas, lifecycle, archive rule and monthly check. The maintenance job may not restructure Incubator content. Migration map updated: Self-healing AI agent, EBM ML learning and Knowledge lakehouse become ideas; Terminal setup becomes a course note; Office PC purchase archived as cancelled.
- **1.4 (2026-09-27):** `topic` is a link to the MOC and allowed on every type. `90-Views/`, `98-Templates/` and code-tree files are exempt from the link invariant. Added the code-tree file rule (§11). Migration map updated to match the actual migration.
- **1.3 (2026-09-27):** Added §17, tasks and learning items: `learn` kind, closing the loop with `produced`, raw-capture recognition, defaults, grouping learning in MOCs and learning projects, and task views.
- **1.2 (2026-09-26):** Added §16, the maintenance job (change detection, settle time, allowed and forbidden changes, review grouping, schedule), and the `assistant: skip` property.
- **1.1 (2026-09-26):**
  - Added: the contract (invariants, precedence, fallback); `area`, `project-doc`, `log`, `writing`, `daily` types; `25-Areas/`, `80-Writing/`; container rule; mixed-note extraction.
  - Added: unique titles; scope rule; required vs. optional properties; tag registry; collections; body skeletons; updates, conflicts and decisions; migrated-note dates; canvas, Excalidraw, daily-note and file rules; source-note threshold; task `kind: question` and `someday`; recurrence; enforcement via lint and schema; the amendment process.
- **1.0 (2026-09-26):** First version.
