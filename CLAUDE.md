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
hard-coded in `src/`.

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
- A pull request that changes screens updates `docs/design.html`; one that adds a CLI command or a
  config key updates `docs/architecture.md` §5.5 or §4.1.1.
- Before pushing: `uv run ruff format src tests && uv run ruff check src tests && uv run mypy && uv run pytest`.
