# Claudash — Session 22 State

## Current version: 3.2.0

## What's live (as of 2026-04-18)
- v3.0.0: compliance_events table, 4 insight rules
  (repeated_reads_project, multi_compact_churn,
  cost_outlier_session, fix_never_measured)
- v3.0.1: row_factory bug fix in generate_insights()
- v3.1.0: sub-agent work classification
  - 8 tool columns in sessions table
  - classify_subagent_work() + subagent_intelligence()
  - /api/data includes subagent_intelligence
  - Dashboard: work classification badges + Haiku savings
  - Insight rule 19: subagent_model_waste (latent at 30%)
  - Tests: SA-001 through SA-005 (all pass)
  - PID lock: duplicate process gap closed
- v3.2.0: truth-first sub-agent intelligence
  - Classifier hallucination fix — turns_per_tool guard
    Tidify mechanical: $547.81 → $19.09 (87% was hallucinated)
  - sessions.prompt_quality column + scorer + backfill
  - Insight rule 21: unbounded_subagent_prompt (7 real cases)
  - detect_subagent_file_redundancy() function (rule deferred)
  - haiku_savings_caveat field alongside estimate
  - UUID validation in _parse_subagent_info() + JSONL format docstring
  - Tests: SA-006 + SA-007 added (27/30 pass, 0 FAIL)

## Real data (snapshot 2026-04-18, post-v3.2 restart)
- 74 distinct main sessions / 22,697 turn-rows
- 37 distinct sub-agent (session_id, source_path) pairs — 35 distinct
  session_ids due to JSONL format collapse
- Sub-agent prompt quality distribution:
  scoped: 17, balanced: 2, unbounded: 18, unknown: 0
- Tidify: 29 sub-agents, verdict=review_mechanical
  mechanical: 1 session / $19.09 (honest — was $547 hallucinated)
  reasoning: 5 / $931.83
  mixed: 23 / $1668.52
  haiku_savings_estimate: $18.14 (with verify-before-acting caveat)
- Claudash: 5 sub-agents, verdict=review_mechanical
  mechanical: 1 / $1.52  (genuinely tool-dense, tpt=1.44)
- Brainworks: 1 sub-agent, verdict=justified
- Active insights: 58 (7 new unbounded_subagent_prompt + all prior)

## Insight rules currently firing (all with verifiable backing data)
- model_waste (11), floundering_detected (10), cost_outlier_session (7),
  unbounded_subagent_prompt (7, v3.2 new), subagent_cost_spike (4),
  multi_compact_churn (3), repeated_reads_project (3), window_risk (3),
  fix_regressing (2), window_combined_risk (2), roi_milestone (1),
  best_window (1), fix_never_measured (1)
- Rule 19 subagent_model_waste: 0 fires (latent — after hallucination
  fix, Tidify share dropped to <1%, further from 30% threshold)
- Rule 20 subagent_file_redundancy: not shipped — 0 verified cases
  (detection function pre-built; rule earns its existence when data shows)

## Known gaps (deferred to v3.3 or later)
- Sub-agent session_id should be agent-<hash> from filename (not the
  parent UUID embedded in JSONL content). Currently 147 sub-agent JSONL
  files collapse to ~35 DB rows. detect_subagent_file_redundancy() is
  wired and will light up when this fix lands.
- PID lock atexit doesn't fire on SIGTERM — pidfile gets stale content
  after kill. Harmless (kernel releases flock; next starter overwrites)
  but cosmetic. Fix: signal.signal(SIGTERM, clean_exit) in cli.py.
- arch_compliance 6th efficiency dimension — TODO at analyzer.py:1172.
  Needs multi-week compliance_events volume.
- compliance --score CLI command (deferred).
- skill_usage + generated_hooks tables exist but empty.
- Cron watchdog pre-bind race — PID lock is second defensive layer.

## Next session priorities
1. Consider fixing sub-agent session_id to agent-<hash> — unlocks
   per-sub-agent tracking and lights up rule 20 automatically.
2. SIGTERM handler for clean pidfile on kill (tiny fix).
3. Watch rule 21 accuracy — does the 'unbounded' classification
   correlate with real cost post-remediation? Tidify 913fbebe-3c3
   is the most expensive instance — is the audit output worth $464?
4. Measure fix#12 (WikiLoop, repeated_reads, applied ~48h ago,
   still 0 measurements) — run: python3 cli.py measure 12

## Startup command
python3 cli.py dashboard --no-browser --skip-init

## PID file
/tmp/claudash.pid — flock-guarded. atexit clean on interpreter exit;
stale content remains on SIGTERM (harmless — overwritten by next start).
