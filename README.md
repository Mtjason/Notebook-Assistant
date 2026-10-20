# Notebook-Assistant

An AI assistant that keeps an Obsidian vault organized under one handbook. It classifies raw
captures, digests screenshots and half-finished notes into real knowledge, and answers questions
from your notes. **Nothing in the vault changes until you approve it.**

- Rules: [`docs/handbook.md`](docs/handbook.md), the single source of the vault rules (the code reads it)
- Design: [`docs/architecture.md`](docs/architecture.md) · [`docs/maintenance-job.md`](docs/maintenance-job.md)
- Screens: [`docs/design.html`](docs/design.html), open it in a browser
- Status and branch order: [`docs/architecture.md` §5.4.1](docs/architecture.md#541-feature-branches-in-order)

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

The web app lives in `frontend/` (Node 22). Its build lands in the Python package, so `serve`
shows it, and the release wheel ships it:

```bash
cd frontend && npm ci            # once
npm run lint && npm run typecheck && npm test
npm run build                    # → src/notebook_assistant/web/
npm run dev                      # hot reload; /api goes to `notebook-assistant serve` (NA_PORT, default 8765)
```

```bash
uv run notebook-assistant doctor --vault <vault>   # can this PC run the assistant?
uv run notebook-assistant serve  --vault <vault>   # the web app on http://127.0.0.1:8765
```

Golden tests against your real vault are **local only and read-only**:

```bash
NA_REAL_VAULT="/mnt/c/Users/user/Documents/Jason's Vault" uv run pytest tests/test_real_vault.py
```

## Try the core against your vault

All commands below read the vault; `plan-move` and `digest` only write a *pending* changeset
record under `99-System/Assistant/Changesets/`, and nothing else changes until you run `apply`.
`digest` calls the Claude API: set `ANTHROPIC_API_KEY` (or run `ant auth login`) first.

```bash
V="/mnt/c/Users/user/Documents/Jason's Vault"
uv run notebook-assistant check --vault "$V"          # every note against the handbook
uv run notebook-assistant links --vault "$V"          # broken links
uv run notebook-assistant plan-move --vault "$V" \
  "60-Knowledge/ML/Confusion matrix.md" "60-Knowledge/ML/Confusion matrix metrics.md"
uv run notebook-assistant digest --vault "$V" \
  --text answer.md --origin ai-chat                   # a capture → notes, as a changeset
uv run notebook-assistant changesets --vault "$V"     # review the record in Obsidian first
uv run notebook-assistant apply --vault "$V" cs-…     # your approval
uv run notebook-assistant undo  --vault "$V" cs-…     # revert it
```

## Layout

See [`docs/architecture.md` §3.2](docs/architecture.md#32-package-layout).
