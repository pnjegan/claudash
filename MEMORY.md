# Claudash — Session 21 State

## Current version: 3.1.0

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

## Real data (snapshot 2026-04-18)
- 74 distinct sessions / 22,697 turn-rows
- 35 sub-agent sessions (100% tool-classified)
- Tidify: 29 sub-agents, verdict=review_mechanical, 
  mech=$547.81 (20.9%), Haiku savings=$520.42
- Claudash: 5 sub-agents, verdict=review_mechanical
- Active insights: 43

## Known gaps (deferred to v3.2)
- arch_compliance 6th efficiency dimension 
  (TODO at analyzer.py:1172 — needs more compliance_events volume)
- compliance --score CLI command (deferred)
- skill_usage + generated_hooks tables exist but empty
  (need JSONL tool-call data from future sessions)
- cron watchdog pgrep probe fires before port bind — 
  PID lock is second defensive layer but watchdog logic 
  itself could be tightened

## Next session priorities
1. Let compliance_events accumulate 2+ weeks of real data
   then revisit arch_compliance dimension
2. Measure fix#12 (WikiLoop, repeated_reads, applied 35h ago, 
   0 measurements) — run: python3 cli.py measure 12
3. Watch if Tidify mechanical_cost crosses 30% threshold —
   if it does, rule 19 fires automatically

## Startup command
python3 cli.py dashboard --no-browser --skip-init

## PID file
/tmp/claudash.pid — clean on shutdown via atexit
