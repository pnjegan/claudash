# Claudash — self-audit

*Status: engineer's self-review. Every claim is sourced to a file:line, a SQL query, or a git commit.*

*DB window: 2026-03-19 → 2026-04-17 (30 days). Single account: `personal_max` (Max plan, $100/mo).*

---

## 1. One number

In 30 days of Claude Code use, I ran **$7,981.58 of API-equivalent work** through a **$100/mo** Max subscription. That is **79.8× the subscription cost**.

```sql
-- data/usage.db
SELECT ROUND(SUM(cost_usd), 2) FROM sessions;
-- 7981.58
```

The "API-equivalent" framing matters. On a Max plan, Anthropic does not bill per token — so "savings" is the wrong word. What Claudash computes is: if every token I used had been billed at the current Anthropic API rate card, I would have paid $7,981.58. I paid $100. Whether that is a win depends on whether the work I did was worth ≥$100; it is not a cash transfer.

This is the number I actually trust from this audit. The rest is context.

---

## 2. What Claudash is

Claudash is a personal Claude usage dashboard. It parses the JSONL session logs Claude Code writes to `~/.claude/projects/`, stores them in a single SQLite file, and surfaces per-project cost, 5-hour window burn, cache ROI, waste-pattern detection, and — in v2 — an "agentic fix loop" that uses Claude to generate CLAUDE.md rules for its own waste patterns. Zero pip dependencies, one HTML page, one .db file.

Source: `README.md:1-7`, paraphrased.

---

## 3. Scale of data

Everything the rest of this doc cites comes out of one SQLite file: `data/usage.db`, **14 MB on disk**.

| Metric | Value | Query |
|---|---|---|
| Distinct sessions scanned | 72 | `SELECT COUNT(DISTINCT session_id) FROM sessions;` |
| Total rows (per-turn records) | 21,830 | `SELECT COUNT(*) FROM sessions;` |
| Total tokens (input + output + cache_read + cache_create) | ~3.75 billion | `SELECT SUM(input_tokens)+SUM(output_tokens)+SUM(cache_read_tokens)+SUM(cache_creation_tokens) FROM sessions;` |
| JSONL files indexed | 233 | `SELECT COUNT(*) FROM scan_state;` |
| JSONL bytes processed | 206 MB | `SELECT SUM(last_offset) FROM scan_state;` |
| Lines parsed | 88,181 | `SELECT SUM(lines_processed) FROM scan_state;` |

### Model split

```sql
SELECT model, COUNT(*) AS rows, COUNT(DISTINCT session_id) AS sessions,
       ROUND(SUM(cost_usd), 2) AS cost
FROM sessions GROUP BY model ORDER BY cost DESC;
```

| Model | Rows | Sessions | Cost (API-equiv) | % of total |
|---|---|---|---|---|
| claude-opus | 18,759 | 72 | $7,923.74 | **99.27%** |
| claude-sonnet | 1,743 | 21 | $54.36 | 0.68% |
| claude-haiku | 1,328 | 17 | $3.47 | 0.04% |

Opus accounted for **99.3%** of my API-equivalent spend. That number matters more than it might look. Keep reading to §6.

---

## 4. Feature inventory — capability groups

Claudash has accumulated **63 distinct features** across 16 SQLite tables, 18 Python modules, 2 HTML templates, and an npm wrapper. I won't list all 63 inline; they're in Appendix A. The headline capabilities break into ten groups.

| Group | Features | Key file:line | Before this existed | After |
|---|---|---|---|---|
| JSONL scanning | 8 | `scanner.py:99-148` (parser), `:813-841` (periodic) | Claude Code writes logs; nobody reads them | 5-min incremental scan, offset-tracked, cross-platform path discovery |
| Token / cost math | 2 | `scanner.py:57-65` (`compute_cost`) + `config.py:81-84` (pricing) | ccusage shows a daily total | Per-turn cost attached to every row |
| Waste detection | 3 | `waste_patterns.py:120-328` (floundering, repeated_reads, bad_compact) | You find waste by reading bills | `waste_events` table with token_cost, severity, detail_json |
| Analytics | 13 | `analyzer.py:41-1192` (13 metric functions) | Aggregate by hand in a notebook | One-call rollups: window, per-project, rightsizing, context-rot, efficiency score |
| Insights engine | 1 (16 types) | `insights.py:51-393` | Stare at dashboard to notice things | 16 distinct insight types fire on rule hits |
| Fix tracker (v1) | 4 | `fix_tracker.py:109-522` (baseline / delta / verdict / share-card) | "Did that CLAUDE.md rule work?" — guess | Plan-aware verdict after ≥N sessions |
| Fix generator (v2) | 5 | `fix_generator.py:1-807` (3 providers, 6 prompt templates, 8-step CLAUDE.md discovery) | Hand-type rules | LLM-generated proposals, applied with one click |
| MCP server | 2 (10 tools) | `mcp_server.py:62-457` | Dashboard data trapped in browser | Claude Code queries its own metrics via JSON-RPC over stdio |
| Browser tracking | 3 | `claude_ai_tracker.py:114-342`, `tools/mac-sync.py`, `tools/oauth_sync.py` | 5-hour window looks fine, web chat steals it | Combined Code + chat window view |
| CLI / UI / packaging | 14 | `cli.py` (15 commands), `templates/dashboard.html` (2,090 lines), `bin/claudash.js` (npm wrapper) | `python3 scripts/*.py` | `npx @jeganwrites/claudash` |

Full 63-feature table in Appendix A.

---

## 5. V1 vs V2 split

Version boundary: `v1.0.15` (`c15ed10`) → `v2.0.0` (`05df213`). Seven `feat(v2): F*` commits between them, plus the P1+P2 agentic-loop commit `bfff7e0`.

### V1 shipped (36 of the 63 features, in `@jeganwrites/claudash@1.0.15`)

| Subsystem | One-line summary |
|---|---|
| JSONL scanner + incremental state | 5-min scan with byte-offset resume over a `scan_state` table |
| Token/cost calculator | Per-model Opus/Sonnet/Haiku rate card hardcoded at `config.py:81-84` |
| Analytics core | 10 metric functions: account, window, project, compaction, rightsizing, daily snapshots, trend, subagent, budget, efficiency score |
| Waste detection v1 | Floundering + repeated_reads detectors over the JSONL tool_use stream |
| Insights engine | 16 distinct insight types across 14 numbered rules in `insights.py` |
| Fix tracker v1 | Record baseline → measure delta → assign plan-aware verdict → export share card |
| Browser (claude.ai) sync | Cookie-based (Mac) + OAuth (Linux/VPS) + manual session-key paste |
| MCP server (read-only) | 5 tools: summary, project, window, insights, action_center |
| CLI + init wizard | 15 verbs, auto-detects plan from `~/.claude/.credentials.json`, auto-discovers data paths |
| Web UI | Single-page dashboard with hero / windows / projects / trends / compaction / fix-tracker sections |
| Packaging | PM2 config, health endpoint, npm wrapper, auto-restart dashboard, sync daemon, shared `_version.py` |

### V2 items — what shipped, what didn't

| Item | Description | Status | Evidence |
|---|---|---|---|
| F1 | Session lifecycle events (compact / clear / plan_mode) | **done** | `c54bf63`; table `lifecycle_events` at `db.py:282-295` populated with 146 compacts, 146 subagent_spawns |
| F2 | Context rot bucketed metric | **done** | `8654ed1`; `analyzer.py:652-778` |
| F3 | Bad-compact detector | **done** | `8654ed1`; `waste_patterns.py:246-328`; produces 0 events in current DB because user over-compacts (see §6) |
| F4 | Agentic fix generator (Anthropic-only, 3 transports) | **done** | `eec74b8 → 1641300 → 17b14d6 → 88d2439`; 807-line `fix_generator.py` |
| F5 | Bidirectional MCP (5 write-side tools + warning queue) | **done** | `d6a33fe`; `mcp_server.py:262-457` |
| F6 | Streaming cost meter (SSE + hooks + live widget) | **done** | `fb46ba9`; `server.py:529-563` + `hooks/*.sh` + `dashboard.html:2042-2090` |
| F7 | Per-project `autoCompactThreshold` recommender | **done** | `8c3db4d`; `analyzer.py:851-976` |
| P1 | Auto-fix from insights | **done** | `bfff7e0`; `server.py:824-895` |
| P2 | Auto-measurement loop | **done** | `bfff7e0`; `scanner.py:736-811` — runs ≥1d old, ≥3 new sessions, 6h dedup |

### Deferred to v3 (PRD §11, "Phase 3 — Closed loop")

| Item | Status | PRD line |
|---|---|---|
| Corrective auto-regeneration when verdict='regressed' | Not built — `fix_regressing` insight fires (`scanner.py:792-810`) but nothing consumes it | `CLAUDASH_V2_PRD.md:330` |
| Dedicated v2 metrics dashboard tab | Not built — `templates/dashboard.html` has no new tab past `fix-tracker-section` | `CLAUDASH_V2_PRD.md:331` |

### Explicitly out of scope (PRD §4)

| Item | PRD line |
|---|---|
| Autonomous self-healing writes to CLAUDE.md | `CLAUDASH_V2_PRD.md:111-113` |
| Multi-turn / conversational fix generation | `CLAUDASH_V2_PRD.md:115-116` |
| LLM-graded (not arithmetic) verdict | `CLAUDASH_V2_PRD.md:117-119` |

---

## 6. What my own tool taught me about my own usage

This is the section I wanted to write when I built Claudash.

### I use Opus for everything

99.3% of my API-equivalent spend was on Opus. The `model_rightsizing` check at `analyzer.py:368-398` flags every Opus session whose average output is under 800 tokens as a Sonnet candidate. Current latest estimates, summed across the four projects with active `model_waste` insights:

```sql
SELECT ROUND(SUM(latest), 2) FROM (
  SELECT MAX(json_extract(detail_json, '$.savings')) AS latest
  FROM insights WHERE insight_type='model_waste' GROUP BY project
);
-- 4887.71
```

**~$4,888/mo** of the $7,981 is theoretically avoidable by downshifting short-output Opus sessions to Sonnet. That's an upper bound — Claudash doesn't validate that Sonnet would have succeeded at every such task. But it is the single biggest lever I have.

### My efficiency grade is a D

`compute_efficiency_score` (`analyzer.py:1063-1192`) returns **65/100, grade D**. Breakdown:

| Dimension | Score | Weight |
|---|---|---|
| Cache efficiency | 100 | 0.25 |
| Model right-sizing | 29 | 0.25 |
| Window discipline | **13** | 0.20 |
| Floundering rate | 100 | 0.20 |
| Compaction discipline | 100 | 0.10 |

Window discipline is 13/100. Formula at `analyzer.py:1105-1118` penalizes utilization above 80%. Given the total 30-day spend, "above 80%" is the mechanical reading — I am consistently pushing the 5-hour window close to the ceiling rather than pacing across it.

Floundering at 100/100 is **not good news** — it's an artefact of the detector returning zero events. See §7.

### One session cost $1,109

```sql
SELECT session_id, project, ROUND(SUM(cost_usd),2), SUM(input_tokens+output_tokens),
       datetime(MIN(timestamp),'unixepoch')
FROM sessions GROUP BY session_id ORDER BY SUM(cost_usd) DESC LIMIT 1;
-- fb516355-1886-4bd8-b05b-c8ecd8757e7a | Brainworks | 1109.57 | 267740 | 2026-04-08 05:27:29
```

One session, **$1,109.57, 267,740 tokens, Brainworks project, 2026-04-08**. The `subagent_metrics` rollup (`analyzer.py:576-640`) shows that the entire Brainworks project is a single subagent lineage — one parent session spawned one child, and the child is the $1,109 session. Without the subagent metric, I would have seen "Brainworks cost $1,109" in the project table and missed that it's a single run, not a month of work.

### Tidify is 59% of my total

```sql
SELECT project, ROUND(SUM(cost_usd),2), 
       ROUND(100.0*SUM(cost_usd)/(SELECT SUM(cost_usd) FROM sessions),1) AS pct
FROM sessions GROUP BY project ORDER BY pct DESC;
```

| Project | Cost | % of total |
|---|---|---|
| Tidify | $4,711.87 | 59.0% |
| Claudash | $1,613.87 | 20.2% |
| Brainworks | $1,109.57 | 13.9% |
| WikiLoop | $358.68 | 4.5% |
| CareerOps | $176.68 | 2.2% |
| Knowl | $10.90 | 0.1% |

Tidify is a large data-cleaning app with 52 distinct sessions averaging 300 rows apiece. That it dominates cost is not surprising. What matters is that before Claudash, I would have had no idea the ratio was 59/41 vs 90/10 or 10/90.

---

## 7. What my own tool taught me about itself

This is the section I didn't want to write.

### Flag 1 — the floundering detector is too strict for real workloads

**Symptom**: `SELECT COUNT(*) FROM waste_events WHERE pattern_type='floundering'` returns 0. In 30 days, 72 sessions, 21,830 rows, zero flagged floundering events.

**Diagnosis**: I pulled the top session by row count (Tidify, `8e51450a-…`, 806 rows, 567 parsed `tool_use` blocks) and ran the detector against it directly.

```
Top 5 (tool, input_hash) pairs by frequency: 
  ('Bash', '233564f8'): 7
  ('Bash', '7743ceff'): 3
  ('Bash', '00ccf3af'): 3
  ('Edit', '9a02a544'): 3
  ('Bash', '0f2d42c4'): 3

Longest consecutive run of identical (tool, input_hash): 1
Floundering runs detected (≥4 consecutive): 0
```

Seven identical Bash calls in one session — classically "Claude is stuck" — but not four of them in a row. Real Claude Code sessions interleave Reads, Greps, and Edits between retries, so the "≥4 consecutive" requirement at `waste_patterns.py:36,120-145` almost never triggers.

**The parser is fine.** 567 tool_use blocks extracted cleanly. The `FLOUNDER_THRESHOLD = 4` with consecutive matching is the bug. A stricter-than-the-old-one but more honest detector would count total repeats of a `(tool, input_hash)` key in-session, the way `_detect_repeated_reads` at `waste_patterns.py:147-181` already works for files.

**Consequence for the blog**: I cannot publish a "floundering events detected" count from this database. The `Floundering rate = 100/100` line in my efficiency score is therefore a false positive — it is saying "zero events detected" when the truth is "detector undercounts."

**Fix**: one file, one function, one session's work. Landing in v2.1.

### Flag 2 — closed-loop attribution is project-scoped, not fix-scoped

**Symptom**: the top 5 applied fixes by measured improvement all report **exactly −21.1% waste change**. The uniformity looked suspicious.

**Diagnosis**: I pulled the `baseline_json.captured_at` for the five fixes.

```sql
SELECT id, datetime(created_at,'unixepoch'), project, waste_pattern FROM fixes
WHERE id IN (5,6,7,8,10) ORDER BY id;
```

| id | created_at | project | waste_pattern |
|---|---|---|---|
| 5 | 2026-04-11 17:18:55 | Tidify | floundering |
| 6 | 2026-04-11 17:18:55 | Tidify | repeated_reads |
| 7 | 2026-04-11 17:18:55 | Tidify | deep_no_compact |
| 8 | 2026-04-11 17:18:55 | Tidify | cost_outlier |
| 10 | 2026-04-13 10:40:05 | Tidify | floundering |

Four of the five were created **in the same second**, all targeting Tidify. The fifth was created two days later, still targeting Tidify.

Measurements:

```sql
SELECT fix_id, measured_at,
       json_extract(delta_json,'$.waste_events.before') AS before,
       json_extract(delta_json,'$.waste_events.after') AS after,
       json_extract(delta_json,'$.waste_events.pct_change') AS pct
FROM fix_measurements WHERE fix_id IN (5,6,7,8,10)
ORDER BY fix_id, measured_at DESC;
```

Every fix's most recent measurement shows `before=90, after=71, pct=-21.1`. Every fix's earlier measurement shows `before=90, after=62, pct=-31.1`. Every measurement at every timestamp is identical across the five fixes.

**Root cause** (`fix_tracker.py:287-311`): `compute_delta` computes the "current" window via `capture_baseline(conn, project, since_override=fix["created_at"])`. Because four fixes share `created_at` and all target Tidify, they receive the same current-window aggregate. The `−21.1%` is ONE real project-level waste reduction (Tidify: 90 → 71 events over three days), being reported FOUR times as if it were four independent improvements.

This is **not a code bug**. The code does what `compute_delta` is designed to do. The gap is **product-level**: the closed-loop verdict cannot attribute improvement to individual fixes when multiple fixes target the same project at the same time. That would require either:

- Staggering fixes (only one active per project) — operational discipline, not code
- Tracking per-fix behavioral deltas (e.g., did the `autoCompactThreshold` fix actually reduce late compactions? did the `max-retry` rule reduce floundering events specifically?) — a structural change to `compute_delta`

**Consequence for the blog**: the honest number from v2's closed loop is **one −21.1% project-level reduction, not five**. The 24 `improving` verdict count from `fix_measurements` is a measurement artefact inflating a single signal.

This becomes Phase 4 gap **#31** in the formal record below.

### Phase 4 gap #31 (added by this audit)

| # | Problem | File:line | Severity | Category |
|---|---|---|---|---|
| 31 | Closed-loop verdict cannot attribute improvement to individual fixes when multiple fixes target the same project simultaneously. `compute_delta()` uses project-level baselines and project-level current windows, so N concurrent fixes report N identical verdicts from one signal. | `fix_tracker.py:287-404` (`compute_delta`); `fix_tracker.py:109-253` (`capture_baseline`) | high | measurement_design |

> **Post-audit update** — Flag 1 (the floundering detector) was fixed in commit `2e4d6d5` on 2026-04-17. The rewritten detector counts ≥4 identical `(tool, input_hash)` calls within a 50-call sliding window; re-running against the same DB surfaced **8 floundering events across 8 distinct sessions, $2,323.73 of previously-invisible waste**. The efficiency score dropped from **65/D** to **45/F** as the `flounder` dimension flipped from 100/100 (false-positive "no events") to 0/100 (real signal: 8 of 72 sessions = 11.1 % flounder rate, clamped to 0 by the formula at `analyzer.py:1121-1126`). The F grade is the honest reading. Flag 2 / gap #31 (per-fix attribution) remains deferred to v3.

---

## 8. Honest gaps — the five that matter

Full Phase 4 table catalogued **31 gaps**: 5 high-severity (4 untested v2 paths + 1 measurement-design gap #31), 11 medium, 15 low. Five are worth naming in the blog.

| # | Problem | Severity | Why it matters |
|---|---|---|---|
| 9-12 | Untested v2 closed-loop paths — `/api/insights/{id}/generate-fix`, `/api/fixes/{id}/apply`, `_auto_measure_fixes`, `find_claude_md` fuzzy matching | high | These are the v2 headline. They are shipped, they work (DB evidence: 4 applied fixes), but not one of them has a named test in `claudash_test_runner.py`. Regression risk is real. |
| 6 | `mcp_server.py` module docstring lists 5 tools; the registry ships 10 | stale_doc | Documentation drift — new users read the docstring |
| 25 | `MODEL_PRICING` hardcoded in `config.py:81-84`. No procedure to refresh when Anthropic updates the rate card. | config_drift | Every ROI number quietly skews when prices move |
| 7 | git commit `d6a33fe` (F5 feature commit message) said "4 write-side MCP tools"; code at `mcp_server.py:262,290,345,400,427` ships 5 | stale_doc | Commit history is immutable; the "4" is wrong in the git record forever — documentation drift during F5 implementation |
| **31** | **Closed-loop attribution is project-scoped, not fix-scoped** | **high** | **See §7, flag 2. This is the v2 headline caveat.** |

---

## 9. What's next

### v2.1 (maintenance)

- Fix the floundering detector: count in-session repeats of `(tool, input_hash)` keys, not consecutive runs. One function in `waste_patterns.py`. Flag 1.
- Add named tests for `/api/insights/{id}/generate-fix`, `/api/fixes/{id}/apply`, `_auto_measure_fixes`, and `find_claude_md` fuzzy matching. Four high-severity gaps.
- Reconcile README/PRD/docstring counts: 16 insight types (not 14), 10 MCP tools (not 5 as the docstring claims), 5 F5 write-side tools (not 4 as the PRD said).
- Pricing refresh procedure for `config.py:81-84` — either an env var, a config file, or a tagged-release check.

### v3 (real closed loop)

- Per-fix attribution: track behavioural deltas specific to each fix (late-compact count, floundering events tagged to retries, etc.) instead of project-level aggregates. Flag 2 / gap #31.
- Corrective auto-regeneration: when `verdict='worsened'`, feed the prior fix + the regression signal back into `fix_generator` to propose a replacement rule. PRD §11 Phase 3, currently scaffolded at `scanner.py:792-810` (emits the insight) but not wired to a consumer.
- Dedicated v2 metrics dashboard tab (PRD §11). Currently the fix tracker lives in the v1 dashboard layout.

---

## Appendix A — full 63-feature list

The Phase 2 inventory of this audit, condensed to two columns for reference. Group order matches §4.

### Data ingestion (scanner.py)
1. JSONL session parser — `scanner.py:99-148`
2. Token/cost calculator — `scanner.py:57-65` + `config.py:81-84`
3. Incremental scan state — `scanner.py:154-176` + `db.py:118-128`
4. Compaction detection at parse time — `scanner.py:82-97`
5. Sub-agent parsing — `scanner.py:178-190`
6. Lifecycle events (compact/clear/plan_mode) [v2-F1] — `scanner.py:327-435`
7. Data-path auto-discovery — `scanner.py:503-593`
8. Periodic scan loop — `scanner.py:813-841`

### Analytics (analyzer.py)
9. Account metrics (30d cost, cache ROI, subscription ROI) — `analyzer.py:41-124`
10. 5-hour window metrics — `analyzer.py:126-200`
11. Per-project metrics — `analyzer.py:202-297`
12. Compaction metrics — `analyzer.py:299-366`
13. Model right-sizing — `analyzer.py:368-398`
14. Daily snapshots + 7d trend — `analyzer.py:400-477`
15. Window intelligence (safe-start) — `analyzer.py:478-510`
16. Alert generator — `analyzer.py:511-561`
17. Sub-agent metrics — `analyzer.py:576-640`
18. Context rot bucketed [v2-F2] — `analyzer.py:652-778`
19. Threshold recommender [v2-F7] — `analyzer.py:851-976`
20. Daily budget metrics — `analyzer.py:1027-1062`
21. Efficiency Score 0-100 — `analyzer.py:1063-1192`

### Waste detection (waste_patterns.py)
22. Floundering detection (input-hash based) — `waste_patterns.py:112-145`
23. Repeated-reads detection — `waste_patterns.py:147-181`
24. Bad-compact detection [v2-F3] — `waste_patterns.py:246-328`

### Insights (insights.py)
25. Insights engine — 16 distinct types across 14 rule sections — `insights.py:51-393`

### Fix tracker (fix_tracker.py)
26. Baseline capture — `fix_tracker.py:109-253`
27. Delta computation (plan-aware) — `fix_tracker.py:287-404`
28. Verdict engine — `fix_tracker.py:405-436`
29. Share-card generator — `fix_tracker.py:467-522`
30. Auto-measure after ≥1 day [v2-P2] — `scanner.py:736-811`

### Agentic fix generator [v2-F4] (fix_generator.py)
31. Pattern-specific prompt templates (6 patterns) — `fix_generator.py:416-489`
32. Anthropic-only multi-provider dispatch (direct / Bedrock / OpenRouter) — `fix_generator.py:504-640`
33. CLAUDE.md fuzzy discovery (8-step) — `fix_generator.py:241-359`
34. Graceful-error contract — `fix_generator.py:182-200`, `:685-777`
35. Fix application to CLAUDE.md with backup — `server.py:896+` + `fix_generator.py`

### Browser tracking
36. Claude.ai session-key poll — `claude_ai_tracker.py:114-197`
37. Mac cookie sync — `tools/mac-sync.py:55-384`
38. OAuth sync (Linux/VPS) — `tools/oauth_sync.py:58-286`

### MCP server (mcp_server.py)
39. MCP server — 10 tools (5 read, 5 write) — `mcp_server.py:62-457`
40. MCP warning queue [v2-F5] — `scanner.py:596-734` + `db.py:263-278`

### Hooks + streaming
41. Pre/PostToolUse hooks [v2-F6] — `hooks/*.sh` + `server.py:656-677`
42. Post-session scan trigger — `tools/hooks/post-session.sh`
43. SSE cost stream [v2-F6] — `server.py:529-563` + `dashboard.html:2042-2090`

### CLI + wrapper
44. CLI dispatcher (15 commands) — `cli.py:1275-1330`
45. Auto-restart dashboard — `cli.py:77-107`
46. Init wizard with credential auto-detect — `cli.py:221-358`
47. Provider setup wizard — `cli.py:1066-1161`
48. Scan reprocess — `cli.py:761-853`
49. npm wrapper — `bin/claudash.js:1-169`

### Database (db.py)
50. 16-table schema — `db.py:46-360`
51. Live-safe additive migrations — `db.py:34-37` (`_column_exists`)
52. DB-backed account config — `db.py:462-545`

### Web UI (templates/dashboard.html)
53. Auth-fetch shim — `dashboard.html:890-935`
54. Dashboard sections (hero / windows / projects / trends / compaction / fix-tracker) — `dashboard.html:813-2003`
55. Fix card UI — `dashboard.html:1782-2003`
56. Insight-to-fix CTA — `dashboard.html:1556-1600`
57. Health ping + reconnect toast — `dashboard.html:2004-2041`
58. Live cost widget [v2-F6] — `dashboard.html:2042-2090`

### Reliability / packaging
59. `/health` no-auth endpoint — `server.py:617-655`
60. PM2 config — `ecosystem.config.js` + `tools/setup-pm2.sh`
61. Sync daemon — `tools/sync-daemon.py` + `cli.py:1036-1042`
62. Shared `_version.py` — `_version.py:1-11`
63. Test runner (23 named tests) — `claudash_test_runner.py:95-679`

---

## Appendix B — architecture map

```
JSONL (~/.claude/projects/)
       ↓  scanner.py           incremental, byte-offset resume
  sessions table (21,830 rows)
       ↓  waste_patterns.py    + analyzer.py (13 metrics)
  waste_events + analytics     + lifecycle_events (v2-F1)
       ↓  insights.py          16 rule branches
  insights table               → dashboard + MCP server
       ↓  fix_tracker.py       baseline → delta → verdict
  fixes + fix_measurements
       ↓  fix_generator.py     LLM-proposed CLAUDE.md rules
  applied rules                → back to scanner's next pass
```

Everything is one SQLite file. Every event is append-only except `waste_events` (cleared on full rescan) and `insights` (stale-cleared at 24h). No services. No containers. 14 MB on disk after 30 days of heavy use.

---

*Authored 2026-04-17 as self-audit before public writeup. Data window 30 days. Flags 1 and 2 are the honest content — the rest is context.*
