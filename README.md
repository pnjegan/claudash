# Claudash

Personal Claude usage dashboard. Tracks token consumption, cost, cache ROI,
5-hour window burn, per-project attribution, sub-agent cost, waste patterns,
and claude.ai browser usage — for Max, Pro, and API plans.

Zero pip dependencies. Single SQLite file. Single HTML page.

![license](https://img.shields.io/badge/license-MIT-black)
![python](https://img.shields.io/badge/python-3.8%2B-black)
![deps](https://img.shields.io/badge/dependencies-zero-black)

## What you get

- **Subscription ROI math** — see your API-equivalent cost vs. what you pay Anthropic
- **Per-project attribution** — cost, sessions, cache hit rate, model efficiency, week-over-week change
- **5-hour window intelligence** — burn rate, predicted exhaust, safe-to-start check, best autonomous-run hour
- **Sub-agent cost tracking** — see how much your agentic orchestration costs
- **Waste-pattern detection** — floundering loops, repeated reads, cost outliers, context rot
- **Daily budget alerts** — configurable per-account cost ceiling with warning and exceeded insights
- **claude.ai browser tracking** — unified view across Claude Code + web chat (combined window burn)
- **MCP server** — expose Claudash data to Claude Code itself via Model Context Protocol
- **Insights engine** — 14 rules that fire actionable notifications (cache spikes, compaction gaps, window risk, ROI milestones, etc.)

## Quick start (5 minutes)

```bash
git clone https://github.com/YOUR_USER/claudash
cd claudash
python3 cli.py dashboard
# Opens at http://127.0.0.1:8080 (localhost only by design)
```

If you're running on a VPS, forward the port over SSH:

```bash
ssh -L 8080:localhost:8080 user@your-vps
open http://localhost:8080
```

Full setup walkthrough in [SETUP.md](SETUP.md).

## Two sync methods for claude.ai browser data

Claudash supports two ways to push your claude.ai session usage to the server.
Pick one based on how you use Claude.

- **`tools/oauth_sync.py`** — **recommended for Claude Code users**. Reuses the
  OAuth access token that `claude` already stores in `~/.claude/.credentials.json`.
  No cookies, no keychain, works on Linux / macOS / Windows. Run via cron.

- **`tools/mac-sync.py`** — for **claude.ai browser-only** users (no Claude Code
  install). Extracts the `sessionKey` cookie from Chrome / Vivaldi via the macOS
  keychain. macOS only.

Both scripts POST to the same `/api/claude-ai/sync` endpoint gated by the
`sync_token` from `python3 cli.py keys`.

## Commands

| Command | Description |
|---|---|
| `python3 cli.py dashboard` | Start the server on :8080 (127.0.0.1) |
| `python3 cli.py scan` | Incremental scan of all tracked JSONL files + waste detection |
| `python3 cli.py scan --reprocess` | Re-tag every existing session using the current `PROJECT_MAP` |
| `python3 cli.py show-other` | List source paths of sessions tagged `Other` |
| `python3 cli.py stats` | Per-account stats table (CLI) |
| `python3 cli.py insights` | Print active insights |
| `python3 cli.py window` | Show 5-hour window status per account |
| `python3 cli.py export` | Export last 30 days of sessions to `usage_export.csv` |
| `python3 cli.py waste` | Run waste-pattern detection and print a summary |
| `python3 cli.py mcp` | Print the MCP settings.json snippet + smoke-test the server |
| `python3 cli.py keys` | Print `dashboard_key` and `sync_token` (sensitive) |
| `python3 cli.py claude-ai` | Show claude.ai browser tracking status |

## How Claudash differs from similar tools

Claudash is not a clone of any existing tool. It focuses on the parts other
trackers skip: persistence, per-project attribution, and the intelligence
layer that turns raw numbers into action.

| Feature | Claudash | ccusage | claude-usage | claude-monitor |
|---|---|---|---|---|
| Web dashboard | ✓ | ✗ | ✓ | ✗ |
| Per-project attribution | ✓ | partial | ✗ | ✗ |
| claude.ai browser tracking | ✓ | ✗ | ✗ | ✗ |
| Subscription ROI math | ✓ | ✗ | ✗ | ✗ |
| Account manager UI | ✓ | ✗ | ✗ | ✗ |
| Sub-agent cost tracking | ✓ | ✗ | ✗ | ✗ |
| MCP server | ✓ | ✓ | ✗ | ✗ |
| Waste pattern detection | ✓ | ✗ | ✗ | ✗ |
| Multi-machine collector | ✓ | ✗ | ✗ | ✗ |
| Zero pip dependencies | ✓ | ✗ | ✓ | ✗ |

We recommend using `ccusage` alongside Claudash — `ccusage` for quick terminal
reports, Claudash for deep project intelligence, persistence, and actionable
insights.

## Insight rules

14 rules fire after every scan:

| Type | Severity | When it triggers |
|---|---|---|
| `model_waste` | amber | Project uses Opus but avg output <800 tokens — Sonnet is sufficient |
| `cache_spike` | red | Cache creation >3× the 7-day average |
| `compaction_gap` | amber | Sessions hit 70% of window limit without `/compact` |
| `cost_target` | green | Project hit its cost-per-session target |
| `window_risk` | red | Current burn rate will exhaust the 5-hour window in <60 min |
| `roi_milestone` | green | Subscription ROI crossed 2×, 5×, or 10× this month |
| `heavy_day` | blue | Consistent heavy usage on same day of week |
| `best_window` | blue | Identifies quietest 5-hour block for autonomous runs |
| `window_combined_risk` | red | Claude Code + claude.ai browser combined >80% of window |
| `session_expiry` | red | claude.ai session cookie expired |
| `pro_messages_low` | amber | Pro plan at >70% of message budget |
| `subagent_cost_spike` | amber | Sub-agents consume >30% of project cost |
| `floundering_detected` | red | Session stuck in retry loops (same tool >=4 times) |
| `budget_warning` / `budget_exceeded` | amber / red | Daily budget threshold crossed |

## API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/data?account=X` | — | Full analysis (metrics, projects, windows, insights, sub-agents, waste, budget) |
| GET | `/api/projects?account=X` | — | Per-project breakdown |
| GET | `/api/insights?account=X&dismissed=0` | — | Active insights |
| GET | `/api/window?account=X` | — | 5-hour window status + history |
| GET | `/api/trends?account=X&days=7` | — | Daily snapshots for charts |
| GET | `/api/health` | — | DB size, total records, last scan |
| GET | `/api/accounts` | — | Accounts with `data_paths`, projects, budget |
| GET | `/api/claude-ai/accounts` | — | claude.ai browser tracking config (session keys scrubbed) |
| POST | `/api/scan` | X-Dashboard-Key | Trigger a rescan |
| POST | `/api/insights/{id}/dismiss` | X-Dashboard-Key | Dismiss an insight |
| POST / PUT / DELETE | `/api/accounts*` | X-Dashboard-Key | Account CRUD |
| POST | `/api/claude-ai/sync` | X-Sync-Token | Push browser / OAuth usage from a collector |

GET endpoints are unauthenticated because the server only binds `127.0.0.1`.
Every mutating endpoint requires `X-Dashboard-Key` (from `python3 cli.py keys`).

## Tech stack

- Python 3.8+ stdlib only — zero pip dependencies
- SQLite with WAL mode (`data/usage.db`)
- Vanilla JS dashboard with DM Serif Display + DM Mono + DM Sans (Google Fonts `@import`)
- No build step, no bundler, no Node, no Docker

## Documentation

- [SETUP.md](SETUP.md) — first-time setup guide
- [REPORT.md](REPORT.md) — architecture overview
- [FOUNDING_DOC.md](FOUNDING_DOC.md) — vision, concepts from first principles
- [SECURITY_TRUTH_MAP.md](SECURITY_TRUTH_MAP.md) — fresh-eyes security audit
- [END_USER_REVIEW.md](END_USER_REVIEW.md) — cold-start review + scorecard
- [CHANGELOG.md](CHANGELOG.md) — session history

## License

MIT. See [LICENSE](LICENSE).
