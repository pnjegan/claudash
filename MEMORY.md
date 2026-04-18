# Claudash — Session 22 handoff state

## Current version: 3.3.0

Full handoff: `.dev-cdc/SESSION_22_HANDOFF.md` (in repo from this commit).

## What's live
- v3.0.0: compliance_events, 4 insight rules, cli.py realstory, /api/realstory
- v3.0.1: row_factory guard in generate_insights()
- v3.1.0: sub-agent work classification, PID lock
- v3.2.0: turns_per_tool guard (classifier hallucination fix),
  prompt_quality column, rule 21 unbounded_subagent_prompt,
  detect_subagent_file_redundancy() function
- v3.3.0: cli.py backup + restore, M04/M05/M06 fixes

## Critical finding: fix#11 and fix#14 "worsened" verdicts are FALSE

Investigation at end of session showed three measure-function bugs:

1. **Identical repeated measurements** — fix#11 has 3 byte-identical
   delta blocks across 3 timestamps (14:06, 20:07, 02:07). fix#14 same
   pattern. Measure is replaying cached delta, not re-reading DB.
2. **Floundering 0→3 over-weights verdict** — a zero-to-nonzero
   floundering transition with pct_change=0.0 (undefined division) flips
   verdict=worsened even when waste_events.total dropped and cost fell >70%.
3. **Shared baselines for fix#5-8** — all captured_at=1775927935,
   waste_total=90, cost=$932.28, sessions=8. Gap #31 (documented).

Actual metrics for fix#11 (CLAUDE.md trim+split):
  waste_events 62→60, repeated_reads 48→43, cost $1261→$338, turns 238→150.
Fix#14 (AI cost_outlier rule):
  waste_events 70→60, repeated_reads 56→43, cost $1302→$277, turns 258→132.

Both fixes are actually IMPROVING the project. The `fix_regressing`
insights in DB are false signals — consider dismissing on next session.

## Next session — decide first

(A) Fix measure() function: last-writer-wins or re-run on each call,
    fix verdict weighting (primary metric direction > absolute-count
    changes on secondary rare patterns), fix pct_change math for 0→N.
OR
(B) Manual verdict flip for fix#11 and #14, defer measure refactor.

Pick before touching anything else — it affects every future measurement.

## Open items
- fix#12 (WikiLoop): re-measure after 7+ post-fix sessions
- H01 sub-agent session_id collapse (147 JSONL → 35 DB)
- L01 insights.severity → column (currently in detail_json)
- L02 ~30 genuinely dead functions (post-test-filter)
- 36 apt packages upgradable (VPS maintenance)
- Session 19/20 carry-forwards: _NO_DASH_KEY fragility (server.py:650),
  MODEL_PRICING refresh, missing /api/claude-ai/sync negative-path test

## Live state
- Running: pid 3191593, v3.3 code, port 8080
- PID lock: /tmp/claudash.pid (SIGTERM-cleaned in v3.3, SIGKILL still leaks)
- DB: data/usage.db 13.5 MB, WAL, busy_timeout 30s
- Backups: /root/backups/claudash/ (rclone-synced to Drive)
- Override: CLAUDASH_BACKUP_DIR env var or --output DIR

## Row snapshot
- sessions: 23,023 turn-rows / 74 distinct session_ids
- fix_measurements: 55 (6 are identical-delta noise from fix#11 and #14)
- fixes: 9 (4 improving, 2 "worsened" but verdict is wrong, 1 recently-measured, 2 no-meas)
- insights (active): 53 (includes 2 false fix_regressing)
- compliance_events: 127
- waste_events: 93

## Startup
```
nohup python3 cli.py dashboard --no-browser --skip-init > logs/server.log 2>&1 &
```

## File anchors
- scanner.py:178  _parse_subagent_info (UUID validation + docstring)
- analyzer.py:654 classify_subagent_work (turns_per_tool guard)
- analyzer.py:695 subagent_intelligence (verdict + savings + caveat)
- analyzer.py:1172 TODO for arch_compliance 6th efficiency dim
- insights.py rules 15-19 (v3.0 + v3.1) + rule 21 (v3.2)
- cli.py:82 PID lock with SIGTERM handler (v3.3)
- cli.py:~1310 backup/restore commands (v3.3)
- db.py:97 sessions migration loop (29 cols)
- db.py:~843 detect_subagent_file_redundancy (no rule yet)
