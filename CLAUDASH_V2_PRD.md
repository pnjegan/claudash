# Claudash v2.0 — Agentic Fix Loop (PRD)

**Status**: Draft
**Target release**: v2.0.0
**Owner**: Jegan
**Related docs**: `INTERNALS.md` (§5 waste patterns, §10 fix tracker)

---

## 1. Vision

Close the loop between waste detection and waste elimination.

Today: Claudash detects waste. Humans read the findings, guess at a
CLAUDE.md rule, type it out, and hope it helps.

v2.0: Claudash detects waste, generates a targeted fix via the Anthropic
API, a human approves in one click, Claudash writes the fix to
`CLAUDE.md`, snapshots a baseline, and measures the result after 7 days.
If the fix didn't work, Claudash generates a correction.

Claude fixing Claude's own inefficiency. Fully closed loop.

## 2. Motivation

- 136 `repeated_reads` events in Tidify alone, ~$4,023 in recovered-cost
  opportunity sitting there indefinitely — nothing acts on the data.
- 5 fixes are currently "measuring"; every one of them was hand-typed.
  Generation is the rate-limit in the loop.
- Each pattern has a templatable fix shape. CLAUDE.md rules,
  `autoCompactThreshold`, retry limits — the patterns are small,
  repetitive, and well understood.
- No competitor tool closes this loop: `ccusage`, `claude-usage`,
  `claude-monitor` all stop at detection.

## 3. The loop (4 stages)

```
                ┌────────────┐
                │  DETECT    │  waste_patterns.py → waste_events
                └──────┬─────┘
                       ▼
                ┌────────────┐
                │  GENERATE  │  NEW — fix_generator.py → Anthropic API
                └──────┬─────┘
                       ▼
                ┌────────────┐
                │  APPROVE   │  human click → fix_applier.py → CLAUDE.md
                │  + APPLY   │  record_fix() baselines
                └──────┬─────┘
                       ▼
                ┌────────────┐
                │  MEASURE   │  measure_fix() after 7d → verdict
                └──────┬─────┘
                       │   verdict == "regressed"
                       └──► loop back to GENERATE with correction context
```

### 3.1 Stage 1 — DETECT (already built)
`waste_patterns.detect_all()` writes to `waste_events` on every scan.
Unchanged for v2.

### 3.2 Stage 2 — GENERATE (new)
Input:
- pattern type (one of 4)
- project name + account
- waste payload (file list, retry count, cost, etc. — pulled from
  `waste_events.detail_json`)
- current `CLAUDE.md` (if present — see §6 discovery)
- previous fixes for this project (from `fixes` table)

Output — `FixRecommendation`:
- `rule_text` — exact markdown to append to CLAUDE.md
- `reasoning` — 2-3 sentences explaining why this addresses THIS pattern
- `expected_impact_pct` — model's estimate of waste reduction (0-100)
- `risk_level` — `low` | `medium` | `high`
- `settings_change` — optional JSON patch for `~/.claude/settings.json`
  (DEEP_NO_COMPACT returns an `autoCompactThreshold` here)

Model: `claude-sonnet-4-5` (explicitly not Opus — cost matters and this
task is well-bounded).
Caching: system prompt + pattern templates sent as a
`cache_control: ephemeral` block, so the 90% of the prompt that never
changes hits cache on every call after the first.

### 3.3 Stage 3 — APPROVE + APPLY (new, hybrid)
Dashboard path:
1. User opens a waste event row → "Generate Fix" button.
2. Modal shows `rule_text`, `reasoning`, `risk_level`, diff preview of
   CLAUDE.md before/after.
3. "Apply" → server writes `CLAUDE.md` (after `.claudash-backup` copy),
   calls `record_fix()` to snapshot baseline, sets `status='applied'`
   and `applied_to_path=<path>`.
4. "Skip" → `status='rejected'`, row dismissed.

CLI path:
- `claudash fix generate <waste_event_id>` → prints proposal, creates
  `fixes` row with `status='proposed'`.
- `claudash fix apply <fix_id>` → writes CLAUDE.md, flips to `applied`.

### 3.4 Stage 4 — MEASURE (extends existing `measure_fix()`)
- Periodic job (or `claudash measure`) runs `measure_fix()` for every
  applied fix older than 7 days with no recent measurement.
- Existing `compute_delta` + `determine_verdict` do the arithmetic.
- **New**: on `verdict='regressed'`, enqueue a corrective generation —
  feed the previous rule_text + the delta back to the generator with
  `corrective=true` in context.

## 4. Out of scope (v2.0)

- Not autonomous. Every write to CLAUDE.md requires explicit human
  approval. No background "self-healing" mode in v2.
- Not a code editor. The generator only writes CLAUDE.md rules and
  optional `settings.json` patches — never touches source files.
- Not multi-turn. One shot per generation. If the fix is bad, generate
  a new one; don't converse.
- Not LLM-graded. Verdict stays arithmetic (`compute_delta`), not
  model-judged. Phase 3 may add an optional "explain the verdict"
  narration, still not a gate.

## 5. Data model changes

### `fixes` table — 5 new columns
```sql
ALTER TABLE fixes ADD COLUMN generated_by TEXT DEFAULT 'human';
  -- 'human' | 'claudash'
ALTER TABLE fixes ADD COLUMN generation_prompt TEXT;
  -- full prompt sent to Anthropic (for auditability + replay)
ALTER TABLE fixes ADD COLUMN generation_response TEXT;
  -- raw JSON response from Anthropic (for replay + analysis)
ALTER TABLE fixes ADD COLUMN applied_to_path TEXT;
  -- absolute path of the CLAUDE.md that was modified
ALTER TABLE fixes ADD COLUMN waste_event_id INTEGER REFERENCES waste_events(id);
  -- links the fix back to the waste event that triggered it
```

Status vocabulary extends: `proposed` (generated, not applied),
`applied` (existing), `rejected` (user skipped), `reverted` (existing),
`regressed` (measure says it made things worse).

### `settings` table
```sql
-- New rows, same existing schema
'anthropic_api_key'  : encrypted or plaintext (see §7 security)
'fix_autogen_enabled': '1' | '0'
'fix_autogen_model'  : default 'claude-sonnet-4-5'
```

### No changes to
`waste_events`, `fix_measurements`, `sessions`, `accounts`.

## 6. CLAUDE.md discovery

Project → CLAUDE.md resolution order:
1. If `accounts.data_paths[i]` for the account contains the project's
   source_path prefix, walk up from the session's `source_path` to find
   `CLAUDE.md`.
2. Fallback: `~/projects/<project-slug>/CLAUDE.md` and
   `~/<project-slug>/CLAUDE.md`.
3. Fallback: user-provided path stored per-project in a new
   `projects.claude_md_path` column (deferred to v2.1 if needed).

If none found: generator still runs (missing-CLAUDE.md is a common
starting state). `rule_text` becomes the seed for a NEW CLAUDE.md,
human applies by creating the file.

## 7. Security & secrets

- Anthropic API key stored in `settings` table, chmod 0600 via the
  existing DB-file protection (`db.py:_lock_db_file`).
- Key never returned by any API endpoint. New endpoint
  `POST /api/settings/api-key` accepts write-only; `GET` returns only
  `{configured: bool}`.
- Prompt and response stored alongside each fix for auditability, but
  prompts never include secrets — just pattern data + CLAUDE.md
  contents (which the user already owns).
- Offline behavior: if no key is set OR Anthropic is unreachable, CLI
  prints "generator offline — apply fix manually" and falls back to
  the existing `cmd_fix_add()` flow. Not a regression.

## 8. Prompt templates

All four templates share this system prompt (cached):

```
You are a Claude Code optimization expert. Your job is to write a single
targeted CLAUDE.md rule that will reduce a specific observed waste
pattern. You will receive telemetry from Claudash (a dashboard that
scans Claude Code's JSONL transcripts) and the project's current
CLAUDE.md. Respond ONLY with valid JSON matching the schema provided.
Do not explain outside the JSON. Rules must be concrete and actionable;
avoid platitudes like "be efficient" or "use cache".
```

### 8.1 REPEATED_READS
```
Pattern: REPEATED_READS
Project: {project}
Account: {account}
Event count: {count} sessions in last 30 days
Most re-read files (basename only — full paths intentionally stripped):
{file_list}
Estimated recoverable cost: ${token_cost}

Current CLAUDE.md:
<<<{claude_md}>>>

Previous fixes tried on this project (chronological):
{fix_history}

Write one CLAUDE.md rule that prevents these specific re-reads.
Return JSON:
{
  "rule_text": "<markdown to append to CLAUDE.md>",
  "reasoning": "<2-3 sentences>",
  "expected_impact_pct": <0-100>,
  "risk_level": "low"|"medium"|"high"
}
```

### 8.2 FLOUNDERING
```
Pattern: FLOUNDERING
Project: {project}
Sessions affected: {session_count}
Dominant stuck tool: {tool_name}
Retry run length (consecutive identical calls): {retry_count}
Estimated cost at risk: ${token_cost}

Current CLAUDE.md:
<<<{claude_md}>>>

Previous fixes tried:
{fix_history}

Write a CLAUDE.md rule with an explicit retry ceiling and fallback.
Return JSON: {rule_text, reasoning, expected_impact_pct, risk_level}
```

### 8.3 DEEP_NO_COMPACT
```
Pattern: DEEP_NO_COMPACT
Project: {project}
Sessions affected: {session_count}
Average window utilization: {avg_pct}%
Compaction events observed: {compaction_count}
Estimated waste: ${token_cost}

Current CLAUDE.md:
<<<{claude_md}>>>

Return JSON with BOTH:
- rule_text  (CLAUDE.md instruction to compact proactively)
- settings_change  {"autoCompactThreshold": <0-1>}
- reasoning, expected_impact_pct, risk_level
```

### 8.4 COST_OUTLIER
```
Pattern: COST_OUTLIER
Session: {session_id}
Project: {project}
Session cost: ${cost}  ({multiplier}x project 30-day average)
Token breakdown: input={input}, output={output}, cache_read={cr}, cache_write={cw}

Current CLAUDE.md:
<<<{claude_md}>>>

Return JSON: {diagnosis, rule_text, reasoning, expected_impact_pct, risk_level}
```

## 9. UI

### 9.1 Waste events table (existing)
- New column: **Fix** — values:
  - empty → "Generate Fix" button
  - `proposed` → "Review" button
  - `applied` → "Measuring (Nd)" badge
  - `regressed`/`reverted` → red badge

### 9.2 Fix review modal (new)
Sections:
1. Header: project · pattern · severity · est. impact · risk chip
2. `reasoning` block
3. `rule_text` block in monospace
4. Diff preview: "CLAUDE.md before" | "CLAUDE.md after" side-by-side
5. If DEEP_NO_COMPACT: optional `settings.json` diff
6. Footer: **Apply** · **Skip** · **Regenerate** (costs another API call)

### 9.3 Fix tracker (existing)
Extended to show `generated_by` badge and link back to the source
`waste_event`.

## 10. Success metrics

Tracked in `fixes` and `fix_measurements`:

| Metric | Target | How measured |
|---|---|---|
| Generation latency | < 10 s p95 | timestamp delta in `generation_response` |
| Acceptance rate | > 50 % | `applied` / (`applied` + `rejected`) |
| Effectiveness | > 40 % reduction on matched pattern | `fix_measurements.delta_json` after 7d |
| Cost per generation | < $0.10 | Anthropic usage × MODEL_PRICING |
| Corrective rate | < 20 % of applied | `regressed` count / `applied` count |

A Claudash v2 dashboard tab surfaces these live.

## 11. Phased delivery

### Phase 1 — CLI end-to-end (this session)
- `fix_generator.py` with all 4 pattern prompts + system prompt caching
- `db.py` migration: 5 new columns on `fixes` + settings rows
- `cli.py`:
  - `claudash fix generate <waste_event_id>`
  - `claudash keys --set-anthropic <key>`
- Manual test: run against the real Tidify `repeated_reads` event,
  print the JSON, commit the `fixes` row with `status='proposed'`.

**Phase 1 does NOT include**: applier, server endpoints, dashboard UI.

### Phase 2 — Apply flow (next session)
- `fix_applier.py`: `find_claude_md`, `backup_claude_md`, `apply_fix`,
  `verify_applied`.
- `cli.py`: `fix apply`, `fix preview`, `fix reject`.
- `server.py`: `POST /api/fixes/generate`, `POST /api/fixes/<id>/apply`,
  `GET /api/fixes/<id>/preview`.
- `templates/dashboard.html`: Generate Fix button + review modal.

### Phase 3 — Closed loop (final)
- Periodic `measure_fix` job (extends existing `start_periodic_scan`).
- Corrective generation when `verdict='regressed'`.
- v2 metrics dashboard tab.
- End-to-end demo: pick one live waste event, generate, apply,
  wait 7 days, measure, publish the verdict.

## 12. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Generated rule is vague platitude | Medium | System prompt forbids platitudes; "Regenerate" button; track acceptance rate |
| CLAUDE.md conflict (user edited same time) | Low | Backup before write; reject apply if mtime changed since preview |
| Anthropic key leak | Low | Settings-table store, chmod 0600, never in API response |
| Measure says "regressed" incorrectly due to external factors | Medium | Require minimum 7d + ≥10 sessions before verdict; show delta to user, don't auto-revert |
| Runaway corrective loop | Low | Cap corrective chain depth at 2 |

## 13. Open questions

- Should proposed fixes expire? (7d stale cutoff?)
- Should we A/B test fixes — apply to a subset of sessions? Probably not; too complex for v2.
- `autoCompactThreshold` writes to `~/.claude/settings.json` — that's a
  global file. Should we scope to project only (via CLAUDE.md text)?
  Currently: leave the global write opt-in behind a second confirmation.

---
