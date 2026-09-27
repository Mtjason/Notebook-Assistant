# Working in this repository

Notebook-Assistant keeps Jason's Obsidian vault organized under the Vault Handbook. Read
`docs/architecture.md` before changing structure and `docs/handbook.md` before changing rules.

## Non-negotiables

- **Every vault change is a changeset** applied only after approval, with base-hash checks,
  link verification and rollback (`app/apply.py`). Nothing writes to notes directly.
- **The handbook is the source of truth.** `domain/schema.py` mirrors it; when a rule changes,
  update the handbook (vault `99-System/Handbook.md`, copy in `docs/handbook.md`), the schema and
  the tests in the same branch.
- **Digest and split captures correctly.** Every path that turns raw material into notes goes
  through the shared extraction planner (`app/extract.py`, see `docs/maintenance-job.md`,
  Extraction): atoms → handbook types, instance vs. principle (Handbook §3.1), patch before
  create, coverage validated in code. A change that makes splitting worse on the fixture
  captures is a regression.
- **`domain/` is pure** — no I/O. Files go through `ports/vault.py`.
- **Portable file handling:** always `encoding="utf-8"` (ruff PLW1514 enforces it), keep line
  endings, apply Windows + macOS + Linux name rules on every host, compare names with `name_key`.
- **Never commit real vault notes.** Tests use `tests/fixtures/vault/` (synthetic). Golden tests
  read the real vault via `NA_REAL_VAULT`, locally only.
- **Minimal diffs:** edit frontmatter through `Frontmatter.set/delete`, which rewrite only the
  touched entry; an untouched note must re-render byte-identically.

## Workflow

- One feature branch at a time: `feat/<name>` off `main`, merged by pull request when CI is
  green on Linux, Windows and macOS. Order: docs/architecture.md §5.4.1.
- Before pushing: `uv run ruff format src tests && uv run ruff check src tests && uv run mypy && uv run pytest`.
