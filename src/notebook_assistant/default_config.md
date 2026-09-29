---
type: system
kind: config
models:                       # one entry per task; any model ID the API accepts
  classify: claude-haiku-4-5-20251001     # triage, placement, lint explanations
  transform: claude-sonnet-5              # sweep restructuring, capture extraction
  digest: claude-opus-5-5                 # screenshots + drafting (Handbook §19)
  chat: claude-sonnet-5
  fallback: claude-sonnet-5               # used if a configured model is unavailable
limits:
  monthly_spend_usd: 30       # AI jobs pause when reached; the UI shows month-to-date cost
  max_tokens_per_job: 60000
checks:
  preservation_similarity: 0.9  # content-preservation check: how closely a sentence must survive
coordination:
  stale_run_minutes: 15       # a digest or sweep run older than this counts as abandoned
extraction:
  related_notes: 8            # existing notes shown in full to the planner, for patch-not-create
---

The default `Config.md`: every tunable the assistant reads, with its default value
(docs/architecture.md §4.1.1). A vault's own `99-System/Assistant/Config.md` overrides any of
these keys; a key it leaves out keeps the value here.
