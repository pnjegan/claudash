# Claudash — Audit Report

Generated: 2026-04-11

## What This Project Is

A personal Claude Code usage dashboard that tracks token consumption, costs, cache efficiency, 5-hour window burns, and generates actionable insights. Runs on a DigitalOcean VPS, serves a dark-themed web dashboard on port 8080 via SSH tunnel. Pure Python stdlib — zero pip dependencies.

## Why We Built It

Inspired by the need to understand Claude Code usage patterns across multiple projects and accounts. With Max plan ($100/mo) providing 1M tokens per 5-hour window, knowing how much window is consumed by Claude Code vs. claude.ai browser usage is critical for productivity planning. The dashboard answers: "Can I start a heavy coding session right now, or will I hit the limit?"

## What Value It Brings

- Real-time visibility into 5-hour window consumption
- API-equivalent cost tracking ($5,772/mo value on a $100 plan = 57.7x ROI)
- Model right-sizing alerts (Opus used where Sonnet would suffice)
- Cache efficiency monitoring (100% cache hit rate means CLAUDE.md is working)
- Cross-platform tracking: Claude Code JSONL + claude.ai browser (via Mac cookie sync)
- Actionable insights: cache spikes, compaction gaps, window risk, best usage windows

## How It Works

```
Mac (browser)                    VPS (Claude Code)
     |                                |
     | mac-sync.py                    | ~/.claude/projects/*.jsonl
     | reads cookies                  |
     | polls claude.ai               |
     | pushes usage+key              |
     |-----> POST /api/claude-ai/sync |
     |                                | scanner.py walks JSONL
     |                                | analyzer.py computes metrics
     |                                | insights.py generates alerts
     |                                |
     |          Dashboard :8080       |
     |<------ SSH tunnel ------------>|
```

## How We Built It (8 Phases)

| Phase | What | Purpose |
|-------|------|---------|
| 1 | config.py | Account definitions, project mapping, pricing |
| 2 | db.py | SQLite schema with 12 tables, migrations, CRUD |
| 3 | scanner.py | Walk JSONL files, parse tokens, detect compaction |
| 4 | analyzer.py | Per-account metrics, window burn, trends, ROI |
| 5 | insights.py | 11 insight rules, dedup, staleness cleanup |
| 6 | server.py | HTTP API (20+ endpoints), template serving |
| 7 | dashboard.html + accounts.html | Dark-themed SPA, dynamic tabs, dual window bars |
| 8 | cli.py | 7 CLI commands (dashboard, scan, stats, insights, window, export, claude-ai) |

Plus: mac-sync.py (Mac cookie extractor), claude_ai_tracker.py (browser polling)

## Bug Hunter Findings

### Critical Bugs Found and Fixed

**1. Data misattribution (16,381 sessions)**
- All JSONL data comes from one Mac user (unitedappsmaker, Max plan)
- Tidify/CareLink were configured in PROJECT_MAP as `work_pro`
- 16,381 sessions were tagged to the wrong account, making all metrics wrong
- Fix: Updated config.py, ran SQL to reassign all sessions to `personal_max`
- Impact: ROI went from 12x to 57.7x (the correct number)

### Logic Bugs Found and Fixed

**2. Haiku cache_read pricing wrong**
- Was: $0.03/MTok. Should be: $0.025/MTok
- Overestimated cache savings by 20% for Haiku sessions
- Fix: config.py line 44

**3. Migration UPDATEs ran every startup**
- `UPDATE sessions SET account = 'personal_max' WHERE account = 'personal'` ran on every `init_db()` call
- Harmless (zero-row no-op after first run) but wasteful write transaction
- Fix: Gated behind `account_migration_done` settings flag

### Security Fixes

**4. Path traversal defense in _serve_template**
- `_serve_template(filename)` joined user-controlled input with TEMPLATE_DIR without sanitization
- Not currently exploitable (all call sites use hardcoded strings) but risky for future changes
- Fix: Added `os.path.basename(filename)` sanitization

**5. Connection leak in _handle_sync**
- `conn = get_conn()` opened but multiple early-return paths could skip `conn.close()`
- Under rapid error traffic, could exhaust file descriptors
- Fix: Wrapped entire body in `try/finally: conn.close()`

### Performance Improvements

**6. Missing index on sessions.model**
- Queries filtering by model had no index
- Fix: `CREATE INDEX IF NOT EXISTS idx_sessions_model ON sessions(model)`

## Code Improvements Made

- Cleaned up startup banner in cli.py with formatted box showing records/accounts/DB size
- work_pro account correctly set to window_token_limit=0 (Pro plan uses messages, not tokens)
- work_pro label updated to "Personal (Pro)" and data_paths cleared (browser-only)
- All 6 projects reassigned to personal_max in account_projects table

## Data Accuracy Fixes

| What | Before | After |
|------|--------|-------|
| personal_max sessions | 3,414 | 19,844 |
| work_pro sessions | 16,355 | 0 |
| personal_max ROI | 12x | 57.7x |
| work_pro ROI | 189x | 0x (browser only) |
| Haiku cache_read pricing | $0.03/MTok | $0.025/MTok |

## Current Limitations

- Scanner re-reads all JSONL files on each scan (deduped by UNIQUE constraint, but I/O heavy)
- No incremental scan tracking (file offset or hash-based)
- Window calculations use epoch-modulo, not Anthropic's actual window boundaries
- Combined Code + Browser window % is an estimate — Anthropic doesn't expose unified usage
- Pro plan window shows 0% because it's message-based, not token-based

## Future Roadmap

### v2 — Windows Collector
- Collect JSONL from cofounder's Windows machine via rsync or pusher.py

### v2 — Railway Deployment
- Deploy dashboard as a persistent Railway service instead of manual VPS

### v2 — Anthropic Admin API
- Use company billing API for accurate per-org cost tracking

### v3 — Team Sharing
- Multi-user support with auth, per-user dashboards

## How to Add a New Account
1. Go to /accounts in the dashboard
2. Click "+ Add Account"
3. Fill in name, plan type, data paths
4. Click Save

## How to Add a New Machine
1. rsync `~/.claude/projects/` from remote machine to a local path
2. Add that path to the account's data_paths in /accounts
3. Or run mac-sync.py on the remote machine for browser tracking

## SSH Tunnel Instructions
```bash
ssh -L 8080:localhost:8080 root@YOUR_VPS_IP
# Then visit http://localhost:8080
```
