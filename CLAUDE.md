# Working in this repository

Notebook-Assistant keeps Jason's Obsidian vault organized under the Vault Handbook.

## Single source of truth

Every fact lives in exactly one place. Everything else links to it by path and section
(`docs/handbook.md` §3.1) and never restates it. There are no copies: none in the vault, none
in claude.ai project documents, none in summaries or tables.

| Kind of fact | Its one place |
|---|---|
| Vault rules (types, folders, properties, names, tags, digestion…) | `docs/handbook.md`. The code parses its tables (`domain/rules.py`, loaded by `handbook.py`); never hard-code a rule value |
| Architecture, data layout, platforms, release, feature branches, test checkpoints | `docs/architecture.md` |
| Maintenance job, extraction planner, two-PC coordination | `docs/maintenance-job.md` |
| Screens and their layout (visual only) | `docs/design.html` |
| What a module contains | its docstring |
| Why a decision was made | the section that defines it, and its pull request |

When you change a fact, change it in its one place and fix any reference that now points wrong.
If you find the same fact in two places, delete one and link to the other in the same pull
request. `tests/test_rules_single_source.py` fails on a copy of the handbook or on rule values
hard-coded in `src/`; `tests/test_docs_consistency.py` fails on a `§` reference to a section that
doesn't exist, a `docs/design.html` example the handbook doesn't allow, or an environment variable
without the `NA_` prefix. Write cross-document references with the document's name
(`Handbook §3.1`, `architecture.md §4.1.1`) so they resolve unambiguously.

## Doc consistency review

Whenever `docs/`, `CLAUDE.md` or `README.md` changed, the documents must still tell one story.
The Stop hook (`.claude/hooks/docs_review.py`) sends you here once per change; do it anyway if
the hook isn't running.

1. Run `uv run pytest tests/test_docs_consistency.py tests/test_rules_single_source.py`.
2. For every changed passage, list the facts it states or changes. Search for each one (key
   terms, property names, paths, section numbers) across `docs/`, `CLAUDE.md`, `README.md` and
   module docstrings, including the demo data in the script at the bottom of `docs/design.html`.
3. Each fact is stated once, in its home (table above), and only referenced elsewhere. Fix a
   contradiction in the home; replace a restatement with a reference.
4. The examples on `docs/design.html` obey the current handbook: titles (§5), folders (§2.3, §3),
   properties and values (§4).
5. A renamed or renumbered section: every reference to it is updated. A handbook change: `version`
   bumped and a *Version history* line added (Handbook §15).
6. In your reply, say what you checked and what you changed.

## Configuration, not constants

A value that someone might want to change lives in exactly one of three homes, never in code:

| Kind of value | Its home |
|---|---|
| A vault rule (anything the handbook decides) | `docs/handbook.md`, parsed at load; the same for every vault, which can't override it |
| A vault's tunable (models, limits, thresholds, toggles) | that vault's `99-System/Assistant/Config.md` (`docs/architecture.md` §4.1.1) |
| A per-machine setting (vault path, profile, features) | the per-machine `config.yaml` (`docs/architecture.md` §4.1.1, §5.3) |

- Code receives these values as typed, validated objects passed in (the way `Rules` is); it never
  reads a file or an environment variable deep inside logic. `domain/` gets them as arguments.
- A named module constant is fine only for an implementation detail nobody would tune (a regex, a
  file suffix). If you're unsure which it is, ask before adding one.
- A missing or malformed value fails loudly at load (like `HandbookFormatError`); no silent
  defaults that hide a typo.
- Environment variables use the `NA_` prefix.
- Adding a config key updates `docs/architecture.md` §4.1.1 in the same pull request.

## Clean code

- **One responsibility per function and module**; the module docstring says what it owns. If a
  docstring needs "and also", split the module.
- **Names come from the handbook's vocabulary** (note, type, topic, changeset, digest…), not
  synonyms. A function that enforces a rule names its section (`§4.2`) in its docstring.
- **No duplication in code either:** a second copy of logic is a bug waiting to diverge. Extract
  and reuse; don't copy-paste-adjust.
- **Types are the contract:** mypy strict, frozen dataclasses or Pydantic models at boundaries,
  no `Any` escaping a module, no stringly-typed dicts passed between layers.
- **Fail loudly, never silently:** no bare `except`, no swallowed errors, no fallback that guesses.
  Uncertain vault decisions go to the handbook fallback (§0.3), not to a heuristic.
- **Dependencies point inward:** `domain/` ← `app/` ← `api/`/`cli`/`jobs`; adapters implement
  `ports/`. Nothing outside `platform/` and `adapters/` checks the OS (`docs/architecture.md` §5).
- **No dead code, no speculative abstraction:** build what the current branch in
  `docs/architecture.md` §5.4.1 needs.
- **Comments say why, not what.** Match the density of the surrounding code.
- **Every behaviour change comes with a test** against `tests/fixtures/`.

## Non-negotiables

- **Every vault change is a changeset**, applied only after approval (`app/apply.py`).
  Nothing writes to notes directly.
- **A rule change is a pull request to `docs/handbook.md`**, never an edit in the vault
  (Handbook §15). Update the parser and tests in the same pull request if a table's shape changes.
- **Every path that turns raw material into notes goes through the extraction planner**
  (`docs/maintenance-job.md`, Extraction). Worse splitting on the fixture captures is a regression.
- **`domain/` is pure:** no I/O. Files go through `ports/vault.py`.
- **Portable file handling:** `docs/architecture.md` §5.2 (ruff PLW1514 enforces UTF-8).
- **Never commit real vault notes.** Tests use `tests/fixtures/`. Golden tests read the real vault
  via `NA_REAL_VAULT`, locally only.
- **Minimal diffs:** edit frontmatter through `Frontmatter.set/delete`; an untouched note must
  re-render byte-identically.

## Workflow

- One feature branch at a time, in the order of `docs/architecture.md` §5.4.1, merged by pull
  request when CI is green on Linux, Windows and macOS.
- **Jason reviews the design through `docs/design.html`.** Any change to what a screen shows or
  calls updates it in the same pull request, and anything it links to (handbook, architecture,
  maintenance job) must still agree with it. Examples on that page (paths, properties, titles)
  must obey the current handbook, because they get read as the spec.
- A pull request that adds a CLI command updates `docs/architecture.md` §5.5.
- When a design change touches several docs, check every file in `docs/` for references that
  now point wrong before calling it done.
- Before pushing: `uv run ruff format src tests && uv run ruff check src tests && uv run mypy && uv run pytest`.
