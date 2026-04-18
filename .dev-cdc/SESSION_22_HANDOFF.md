# Session 22 Handoff — 2026-04-18

Comprehensive handoff covering the full span from v3.0.0 audit/reconciliation through v3.3.0 publish, the v3.2 bug hunt, fix#12 measurement, and the fix#11/#14 "worsened" investigation that closed the session.

---

## What shipped this session

Five versions published to `@jeganwrites/claudash`:

| Version | Commit | Summary |
|---|---|---|
| 3.0.0 | `55b70a3` | Architecture Compliance Intelligence (schema-reconciled). compliance_events table, 4 insight rules, cli.py realstory, /api/realstory, 15 new columns across v3 tables. |
| 3.0.1 | `d951685` | row_factory guard in `insights.generate_insights()` — discovered during v3.0 audit. |
| 3.1.0 | `4411a04` | Sub-agent work classification: 8 tool columns, classify_subagent_work, subagent_intelligence, rule 19, PID lock, tests SA-001..005. |
| 3.2.0 | `1627ff9` | Truth-first sub-agent intelligence: turns_per_tool guard fixes classifier hallucination (Tidify mechanical $547.81 → $19.09), prompt_quality column, rule 21 unbounded_subagent_prompt, detect_subagent_file_redundancy() function. |
| 3.3.0 | `2876b0f` | cli.py backup + restore, bug fixes M04/M05/M06, bug hunt audit. |

All commits pushed to `origin/main` with tags `v3.0.0`, `v3.1.0`, `v3.2.0`, `v3.3.0` (3.0.0 tag was never pushed, per earlier decision).

---

## Working principles that emerged and should carry forward

1. **Schema reconciliation before code.** The v3.0 pre-flight audit showed the v3 prompt used column names (`total_cost_usd`, `turns`, `tokens_wasted`, `rule_id`, `context_pct`) that didn't exist. Every subsequent feature spec was checked against real DB columns before writing SQL. Shipped zero queries that would fail at runtime.

2. **Truth-first insight rules.** Every new rule must show a DB row or JSONL line that proves it fires. Across v3.0 + v3.2 we dropped 4 proposed rules that had zero real firings (`subagent_chain_cost`, `prompt_cache_absent`, `output_input_ratio_low`, `subagent_file_redundancy`). Rule 19 ships silent but reachable; rule 20 (file redundancy) doesn't ship, just the detection function.

3. **Classifier hedging via caveat fields, not number changes.** `haiku_savings_estimate` kept its v3.1 key name for backward compat. The new `haiku_savings_caveat` string advises verification per session. `mechanical_cost` dropped 87% because the classifier itself improved (turns_per_tool guard), so the number is now honest.

4. **Per-turn vs per-session discipline.** `sessions` table is per-turn (23,023 rows for 74 distinct session_ids). Every new aggregation uses a `WITH s AS (SELECT ... GROUP BY session_id)` CTE. Never `COUNT(*)` treated as session count.

5. **`.dev-cdc/` is local-only** (gitignored at `.gitignore:50`) — except when explicitly force-added like this handoff. Bug hunt reports, snapshots, session wraps all stay local by policy.

---

## The fix#11/#14 investigation (last action of this session)

The v3.2 bug hunt flagged `fix_regressing` insights on fix#11 and fix#14. The v3.3 CHANGELOG punted them to manual review. The final session action was to diagnose — NO code change made. Three root causes surfaced:

### fix#11 "Trimmed CLAUDE.md 361→307 lines" — verdict=worsened, but actually improved
- `waste_events.total` 62 → 60 (-3.2%)
- `repeated_reads` 48 → 43 (-10.4%)
- `effective_window_pct` 96.3 → 80.2 (-16.7%, closer to 60-80% ideal)
- `avg_turns_per_session` 238.6 → 150.0 (-37.1%)
- `cost_usd` $1,261.41 → $338.18 (-73.2%)

### fix#14 "AI: cost_outlier fix" — verdict=worsened, but actually improved
- `waste_events.total` 70 → 60 (-14.3%)
- `repeated_reads` 56 → 43 (-23.2%)
- `cost_usd` $1,302.37 → $277.54 (-78.7%)

### Three bugs in the verdict logic

1. **Shared-baseline bug (gap #31, documented)**: fixes #5, #6, #7, #8 all share `captured_at=1775927935` and `waste_total=90, cost=$932.28, sessions=8` — captured in a single batch using rolling 7-day aggregate. Any later measurement compares against a moving window.

2. **Measurement caching**: fix#11 has three measurements at 14:06, 20:07, 02:07. The delta blocks are **byte-identical**. The measure function is not re-reading post-fix DB state between runs — it's replaying the first delta. fix#14 has the same pattern (three identical deltas at 14:51, 20:51, 02:51).

3. **Floundering 0→3 over-weights verdict**: both fixes show `floundering.before=0, floundering.after=3, pct_change=0.0`. The zero-to-nonzero transition with `pct_change=0.0` (undefined division) flips the verdict to `worsened` even when every other waste metric dropped and cost fell >70%. The verdict function is under-weighting primary metric (`waste_events.total`) improvements.

### Why this matters for the next session

These are **measurement bugs**, not fix regressions. The insights citing "fix#11 worsened" and "fix#14 worsened" have been misleading the agentic loop. Two options for next session:

- **(A) Fix the measure function**: add last-writer-wins on repeated measurements (or re-compute every call), fix verdict to prioritize `waste_events.total` direction over absolute-count changes in rare patterns, fix floundering zero-to-N pct_change to `+inf` (not 0.0) so the math is at least honest.
- **(B) Mark fix#11, #14 as `improving` manually** (they clearly are), leave the measure function for a larger refactor.

The pre-existing `fix_regressing` insights in the DB (2 of them) are now known to be false signals. Consider dismissing.

---

## fix#12 (WikiLoop) — measured this session

- Before this session: `status=applied`, 0 measurements, 38h old. Rule `fix_never_measured` was firing.
- Action taken: ran `cli.py measure 12`.
- Result: `verdict=insufficient_data (1 days, 0 sessions)`. Raw trend: repeated_reads events 5 → 7 (+40%).
- Follow-up: re-measure in 7+ days. Don't conclude yet — 0 post-fix sessions is too thin to say anything.

---

## v3.2 bug hunt — results, deferred items

Report lives at `.dev-cdc/BUG_HUNT_V32_20260418.md` (local). 10 bugs found, 0 CRITICAL, 0 v3.3 blockers.

Fixed this session:
- M04 — backup path → `/root/backups/claudash/` (rclone-synced)
- M05 — SIGTERM handler (atexit now fires on kill)
- M06 — deleted `tools/setup-pm2.sh`, rewrote README

Deferred, needs attention next session:
- **M01** fix#11 verdict=worsened → now known measurement bug (see above)
- **M02** fix#14 verdict=worsened → same, known measurement bug
- **M03** fix#12 trending worse under insufficient_data → revisit after 7 days
- **H01** sub-agent session_id collapse (147 JSONL → 35 DB) — deferred design; `detect_subagent_file_redundancy()` is pre-wired
- **L01** `insights.severity` as column (lives in detail_json)
- **L02** ~30 genuinely dead functions after test-filter
- **L03** `dashboard_key` prints are intentional (keys command) — false positive, documented

Non-code items carried forward:
- 36 apt packages upgradable on VPS — security patches
- Pre-existing from Session 19/20: `_NO_DASH_KEY` bypass fragility (server.py:650), missing negative-path test for `/api/claude-ai/sync`, `MODEL_PRICING` refresh procedure (config.py:81-84)

---

## Next session priorities (ordered)

1. **Decide on fix#11/#14 measurement bugs** — option (A) fix the measure function, option (B) manual verdict flip. Choose before touching anything else; it affects the accuracy of every future measurement.
2. **JIT skill loading** — highest-value leak pattern not yet implemented. Would let skills load per-session rather than all-upfront from CLAUDE.md.
3. **`cli.py compliance --score`** CLI command (deferred from v3.0 — only `realstory` shipped as the anchor).
4. **VPS security patches** — `apt upgrade` maintenance window.
5. **fix#12 re-measure** — after 7+ post-fix sessions accumulate.
6. **Sub-agent session_id redesign (H01)** — if per-sub-agent tracking becomes high-value. `detect_subagent_file_redundancy()` will light up when this lands.
7. **Dead code cleanup (L02)** — per-function review of ~30 candidates; low priority.

---

## Current live state

- **npm published**: `@jeganwrites/claudash@3.3.0` — `npm view` confirms
- **Running process**: pid 3191593 on v3.3 code, port 127.0.0.1:8080 bound
- **PID lock**: `/tmp/claudash.pid` = 3191593, flock held
- **DB**: `data/usage.db` 13.5 MB, WAL mode, busy_timeout 30s
- **Backups live**: `/root/backups/claudash/claudash-20260418_04.{db,json}` (new v3.3 format) cohabiting with pre-existing cron files
- **rclone** actively syncing `/root/backups/claudash/` → `Drive:tidify-backups/claudash/`
- **Working tree**: clean after v3.3.0 commits pushed

Row counts snapshot:
```
sessions          23023
fix_measurements  55
fixes             9
compliance_events 127
insights          53
lifecycle_events  297
waste_events      93
window_burns      4652
```

Row counts that matter next session:
- `fix_measurements` has 55 rows, but fix#11 and fix#14 contribute 3 identical-delta rows each — effectively 3 rows of noise, not real signal.
- `insights WHERE insight_type='fix_regressing' AND dismissed=0` — 2 rows, both false signals per today's investigation.

---

## Startup commands

```bash
# start dashboard (with PID lock)
nohup python3 cli.py dashboard --no-browser --skip-init > logs/server.log 2>&1 &

# hot backup (goes to /root/backups/claudash/ by default now)
python3 cli.py backup

# restore
python3 cli.py restore --file /root/backups/claudash/claudash-20260418_04.db

# stop (SIGTERM, pidfile auto-cleaned in v3.3)
kill $(cat /tmp/claudash.pid)
```

Override backup path via `CLAUDASH_BACKUP_DIR=/custom/path python3 cli.py backup` or `--output DIR`.

---

## Files and line anchors worth remembering

- `scanner.py:178` — `_parse_subagent_info()` — UUID validation + JSONL format docstring (v3.2)
- `scanner.py:312` — `_iter_assistant_tool_uses()` — existing helper
- `scanner.py:~450` — `classify_session_tools()` + `update_session_tool_classification()` — v3.1 tool counting
- `scanner.py:~490` — `extract_subagent_prompt()` + `score_prompt_quality()` + `compute_prompt_quality_for_session()` — v3.2 scorer
- `analyzer.py:584` — `subagent_metrics()` (v3.0 legacy, project-aggregate)
- `analyzer.py:~654` — `classify_subagent_work()` with turns_per_tool guard (v3.2 hallucination fix)
- `analyzer.py:~695` — `subagent_intelligence()` — per-project verdict, Haiku savings, caveat field
- `analyzer.py:1172` — TODO for 6th `arch_compliance` efficiency dimension
- `insights.py` rules 15-21:
  - 15 repeated_reads_project, 16 multi_compact_churn, 17 cost_outlier_session, 18 fix_never_measured (v3.0)
  - 19 subagent_model_waste (v3.1, latent at 30%)
  - 21 unbounded_subagent_prompt (v3.2, fires on 7 real cases)
- `cli.py:82` — `_PIDFILE`, `_pid_lock_handle`, `_cleanup_pidfile`, `_acquire_pid_lock` with SIGTERM handler
- `cli.py:~1242` — `cmd_realstory()` (v3.0 anchor CLI)
- `cli.py:~1310` — `_default_backup_dir()`, `_backup_filename`, `_prune_backups`, `cmd_backup`, `cmd_restore` (v3.3)
- `db.py:97` — sessions table migration loop (29 columns)
- `db.py:~843` — `detect_subagent_file_redundancy()` function-only (v3.2, no rule)
