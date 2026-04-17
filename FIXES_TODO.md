# Deferred / Out-of-Scope for Today's Fix Session (2026-04-17)

Living punch list for follow-up. Items here were discovered during the 4-fix sprint but explicitly deferred to keep scope tight.

## Audit corrections

- **CLAUDASH_AUDIT.md gap #7 wording is inaccurate.** The "4 write-side MCP tools" phrase lives only in the immutable git commit message of `d6a33fe` (F5 feature commit), not in `CLAUDASH_V2_PRD.md` as the audit claimed. Action: when the audit doc is eventually committed (pending user decision), edit gap #7 to attribute the drift to the commit message, not the PRD.

## v2.1 queue (carried from audit)

- Add named tests for `/api/insights/{id}/generate-fix`, `/api/fixes/{id}/apply`, `_auto_measure_fixes`, `find_claude_md` fuzzy matching (audit gaps #9-#12).
- `MODEL_PRICING` refresh procedure — either env-var override, file loader, or tagged-release check (audit gap #25).
- Consider exposing `FLOUNDER_WINDOW` via env var for self-service tuning (arose during Fix 1).

## v3 queue

- Per-fix attribution in `fix_tracker.compute_delta` — gap #31. Structural change: track fix-specific waste-pattern subsets, not project-level aggregates.
- Corrective auto-regeneration when verdict='worsened' — PRD §11 Phase 3; `fix_regressing` insight emits at `scanner.py:792-810` with no consumer.
- Dedicated v2 metrics dashboard tab.
