# Claudash

Personal Claude usage dashboard. Tracks token consumption, cost, cache ROI,
5-hour window burn, per-project attribution, sub-agent cost, waste patterns,
and claude.ai browser usage — for Max, Pro, and API plans.

Zero pip dependencies. Single SQLite file. Single HTML page.

![license](https://img.shields.io/badge/license-MIT-black)
![python](https://img.shields.io/badge/python-3.8%2B-black)
![deps](https://img.shields.io/badge/dependencies-zero-black)

![Claudash Dashboard](docs/screenshot.png)

## What you get

- **Efficiency Score** — single 0-100 score across 5 dimensions: cache, model right-sizing, window discipline, floundering rate, compaction. Honest, actionable, comparable over time.
- **Subscription ROI math** — see your API-equivalent cost vs. what you pay Anthropic
- **Per-project attribution** — cost, sessions, cache hit rate, model efficiency, week-over-week change
- **5-hour window intelligence** — burn rate, predicted exhaust, safe-to-start check, best autonomous-run hour
- **Sub-agent cost tracking** — see how much your agentic orchestration costs
- **Waste-pattern detection** — floundering loops, repeated reads, cost outliers, context rot
- **Daily budget alerts** — configurable per-account cost ceiling with warning and exceeded insights
- **claude.ai browser tracking** — unified view across Claude Code + web chat (combined window burn)
- **MCP server** — expose Claudash data to Claude Code itself via Model Context Protocol
- **Insights engine** — 14 rules that fire actionable notifications (cache spikes, compaction gaps, window risk, ROI milestones, etc.)

## Platform Support

| Platform | Core Dashboard | Browser Tracking | Notes |
|---|---|---|---|
| macOS + Claude Code | Full | via mac-sync.py or oauth_sync.py | Best experience |
| Linux + Claude Code | Full | via oauth_sync.py | Recommended for VPS |
| Windows + Claude Code | Core | Not supported | Path auto-detection added |
| EC2/VPS | Full | Headless | Use SSH tunnel to view |
| claude.ai browser only | Partial | Window tracking only | No project intelligence |

## Running Claudash across multiple machines

If you use Claude Code on multiple machines (Mac + VPS, work + personal),
run ONE Claudash instance and point it at all your data.

Recommended: run Claudash on your primary machine or VPS.
To include Claude Code sessions from other machines, sync their JSONL files:

```cron
# On secondary machine (Mac/Windows), add to crontab:
*/5 * * * * rsync -az ~/.claude/projects/ user@your-server:~/.claude/projects-secondary/
```

Then add the synced path as a second account in the Accounts tab.

Do **NOT** run separate Claudash instances per machine — you will get split
dashboards with no unified view.

## Getting Started

### Requirements
- Python 3.8+
- Claude Code installed and at least one session run
- macOS or Linux (Windows: core features work, browser tracking not supported)

### Via npm (recommended)

```bash
npm install -g @jeganwrites/claudash
claudash
```

Requires Node.js 16+ and Python 3.8+.
Auto-installs, opens browser, detects your Claude Code data.

### Or git clone

```bash
git clone https://github.com/pnjegan/claudash
cd claudash
python3 cli.py dashboard
# Browser opens at http://localhost:8080
```

### Quick start (VPS/EC2)

```bash
# On your server:
git clone https://github.com/pnjegan/claudash
cd claudash
nohup python3 cli.py dashboard > claudash.log 2>&1 &

# On your local machine:
ssh -L 8080:localhost:8080 your-server
# Open: http://localhost:8080
```

### First run

Claudash auto-detects `~/.claude/projects/` on startup.
If it finds JSONL files, data appears immediately.
If not, check that Claude Code has been used at least once.

### Browser window tracking (optional)

```bash
# Claude Code users (any OS) — recommended:
python3 tools/oauth_sync.py

# macOS browser-only users:
python3 tools/mac-sync.py

# Automate via cron:
# */5 * * * * python3 /path/to/oauth_sync.py
```

### Auto-sync daemon (runs every 5 minutes)

```bash
python3 cli.py sync-daemon
# Or run in background:
nohup python3 cli.py sync-daemon > /tmp/claudash-sync.log 2>&1 &
```

Full setup walkthrough in [SETUP.md](SETUP.md).

## Keeping it running

### Simple (background process)

```bash
nohup python3 cli.py dashboard > claudash.log 2>&1 &
```

### Recommended (PM2 — auto-restarts on crash)

```bash
bash tools/setup-pm2.sh
```

### Check if running

```bash
curl http://localhost:8080/health
# or with PM2:
pm2 status
```

### View logs

```bash
tail -f /tmp/claudash.log
# or with PM2:
pm2 logs claudash
```

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

## Account configuration

`config.py` sets the initial account configuration on first run.
After first run, accounts are managed in the dashboard UI (Accounts page).
Changes to `config.py` after first run have no effect — use the Accounts
page to modify accounts.

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
| `python3 cli.py sync-daemon` | Auto-sync browser data every 5 min (foreground) |

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

## Fix Tracker

Claudash tracks whether the fixes you make to your workflow actually work.

1. **Baseline** — Claudash detects a waste pattern (e.g. floundering in Tidify costs $3,502/month)
2. **Apply** — You make a change (add max-retry rule to CLAUDE.md, set autoCompactThreshold)
3. **Measure** — Run `python3 cli.py measure <fix-id>` after 7 days
4. **Verdict** — Claudash shows before/after: sessions, cost, floundering rate, cache hit

```bash
# Add a fix
python3 cli.py fix add "Added max-retry:3 to CLAUDE.md for Tidify"

# Measure it after a week
python3 cli.py measure <fix-id>
```

No other Claude Code tracker closes this loop. Most tools tell you what happened. Fix Tracker tells you whether your fix worked.

## Fix Generator

Claudash uses Claude to fix Claude Code waste. It generates a targeted
CLAUDE.md rule for any waste pattern it detects — all three supported
providers run Anthropic models only.

```bash
python3 cli.py keys --set-provider          # one-time provider setup
python3 cli.py fix generate <waste_event_id>  # print a proposed rule, save as 'proposed'
```

Supported providers (Anthropic models only):

- **Anthropic API (direct)** — `claude-sonnet-4-5`. Default. Stdlib-only.
- **AWS Bedrock (Anthropic)** — `anthropic.claude-sonnet-4-20250514-v1:0`.
  For teams with existing AWS spend / HIPAA requirements. Needs
  `boto3` (optional `pip install boto3`).
- **OpenRouter (Anthropic)** — `anthropic/claude-sonnet-4-5` via
  OpenRouter. For users who want to use free credits first. Stdlib-only.

### Cost transparency

Fix generation requires an LLM call (~1,100 tokens per fix on Sonnet).
Estimated costs:

- **Anthropic direct**: ~$0.006 per fix
- **AWS Bedrock (Anthropic)**: ~$0.007 per fix — varies by region,
  check your [Bedrock console](https://console.aws.amazon.com/bedrock)
- **OpenRouter (Anthropic)**: ~$0.008 per fix

You control when fixes are generated — nothing calls the API
automatically. Every generation is triggered by you explicitly via
`claudash fix generate <id>`. Claudash itself (scanner, dashboard,
waste detection) has zero LLM costs and zero external API calls.

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
- [docs/HOOKS_SETUP.md](docs/HOOKS_SETUP.md) — Claude Code hooks integration
- [CHANGELOG.md](CHANGELOG.md) — version history
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute

## Security

Your data never leaves your machine.

- Dashboard reads JSONL files Claude Code writes to `~/.claude/projects/`
- All data stored in local SQLite (`data/usage.db`)
- Dashboard served on localhost only — not accessible from internet
- mac-sync.py reads browser cookies locally and pushes only your
  window usage percentage to your dashboard server
- No telemetry, no analytics, no external API calls
- No data sent to Anthropic, GitHub, or any third party

The dashboard key is stored in `data/usage.db` (SQLite).
The DB file has 0600 permissions (owner read/write only).
If you have filesystem access to the VPS, you have access
to the key — this is by design for a single-user tool.

## License

MIT. See [LICENSE](LICENSE).
