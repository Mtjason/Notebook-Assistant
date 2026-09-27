# Notebook-Assistant

An AI assistant that keeps an Obsidian vault organized under one handbook. It classifies raw
captures, digests screenshots and half-finished notes into real knowledge, and answers questions
from your notes. **Nothing in the vault changes until you approve it.**

- Rules: [`docs/handbook.md`](docs/handbook.md) (the vault's copy in `99-System/Handbook.md` is the source of truth)
- Design: [`docs/architecture.md`](docs/architecture.md) · [`docs/maintenance-job.md`](docs/maintenance-job.md)
- Design review page: [`docs/design.html`](docs/design.html) — open it in a browser to evaluate the current design (UI schematic, split planner, data, backend, roadmap)

## Status

Built one feature branch at a time (docs/architecture.md §5.4.1):

| # | Branch | State |
|---|---|---|
| 1 | `feat/core-vault` | merged: notes, frontmatter, links, handbook rules, link-safe rename/move, changesets with apply/undo, vault-backed state |
| 2 | `feat/service-shell` | **next**: service, web app shell, platform profiles, `doctor`, release wheel |
| 3–10 | review · 4a extract · 4b digest · capture · sweep · views · search · chat · embeddings | later |

## Development (WSL or any Linux/macOS)

```bash
# once
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/Mtjason/Notebook-Assistant.git ~/projects/notebook-assistant
cd ~/projects/notebook-assistant

uv sync                          # creates .venv with all dev tools
uv run pytest                    # tests (fixture vault only)
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy                      # strict type checking
```

Golden tests against your real vault are **local only and read-only**:

```bash
NA_REAL_VAULT="/mnt/c/Users/user/Documents/Jason's Vault" uv run pytest tests/test_real_vault.py
```

## Try the core against your vault

All commands below read the vault; `plan-move` only writes a *pending* changeset record under
`99-System/Assistant/Changesets/`, and nothing else changes until you run `apply`.

```bash
V="/mnt/c/Users/user/Documents/Jason's Vault"
uv run notebook-assistant check --vault "$V"          # every note against the handbook
uv run notebook-assistant links --vault "$V"          # broken links
uv run notebook-assistant plan-move --vault "$V" \
  "60-Knowledge/ML/Confusion matrix.md" "60-Knowledge/ML/Confusion matrix metrics.md"
uv run notebook-assistant changesets --vault "$V"     # review the record in Obsidian first
uv run notebook-assistant apply --vault "$V" cs-…     # your approval
uv run notebook-assistant undo  --vault "$V" cs-…     # revert it
```

## Layout

```
src/notebook_assistant/
  domain/    pure logic, no I/O: names, frontmatter, note, links, schema (handbook as data),
             invariants, preserve (nothing-lost check), changeset, ids
  ports/     interfaces (VaultStore)
  adapters/  fs_vault (real disk: atomic UTF-8 writes, Windows lock retries), memory_vault
  app/       index (files + link graph), rename (plan a link-safe move), apply (+undo), canvas
  store/     vault-backed state: changesets, lease, runs, snapshots
  cli.py     developer commands above
tests/       unit · contract (both adapters) · property-based (random renames) · golden (local)
```
