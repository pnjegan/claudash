# Claudash

Personal Claude Code usage dashboard for dual accounts — Max (heavy usage) + Pro (work). Tracks token consumption, costs, cache efficiency, 5-hour window burns, compaction intelligence, and generates actionable insights.

## Quick Start

```bash
cd ~/projects/jk-usage-dashboard
python3 cli.py dashboard
```

SSH tunnel from your machine:
```bash
ssh -L 8080:localhost:8080 root@your-vps
# Visit http://localhost:8080
```

## How Account Tagging Works

Claude Code stores JSONL logs under `~/.claude/projects/`. Each account has configured data paths, and projects are identified by matching folder path keywords.

| account_id | Label | Plan | Window | Data Paths |
|------------|-------|------|--------|------------|
| `personal_max` | Work (Max) | Max ($100/mo) | 1M tokens / 5hr | `~/.claude/projects/`, `~/.claude-personal/projects/` |
| `work_pro` | Personal (Pro) | Pro ($20/mo) | 200K tokens / 5hr | `~/.claude-work/projects/` (browser-only after Session 1 rework) |

All Claude Code JSONL sessions on this box currently belong to the `personal_max` (Work Max) account — the `work_pro` account is retained for `claude.ai` browser tracking only.

| Project | Keywords | Account |
|---------|----------|---------|
| WikiLoop | wikiloop, wiki-loop, wiki_loop | Work (Max) |
| CashKoda | cashkoda, cash-koda | Work (Max) |
| SpiralSpeak | spiralspeak, spiral-speak | Work (Max) |
| CCAF | ccaf, exam, certification | Work (Max) |
| Tidify | tidify | Work (Max) |
| CareLink | carelink, care-link, medicotix | Work (Max) |

Unmatched folders default to "Other" under `personal_max` (Work (Max)).

## Commands

| Command | Description |
|---------|-------------|
| `python3 cli.py dashboard` | Scan + serve dashboard on :8080 |
| `python3 cli.py scan` | Scan all paths, print summary |
| `python3 cli.py stats` | Terminal table: project, tokens, cost, cache%, ROI |
| `python3 cli.py insights` | Print active insights to terminal |
| `python3 cli.py window` | Show current 5hr window status for all accounts |
| `python3 cli.py export` | Export last 30 days to usage_export.csv |

## Adding a New Project

Edit `config.py` → `PROJECT_MAP`:

```python
"MyProject": {"keywords": ["myproject", "my-project"], "account": "personal_max"},
```

Then rescan: `python3 cli.py scan` or POST to `/api/scan`.

## Adding a New Machine

Future: `pusher.py` will push JSONL from remote machines to a central instance. For now, each machine runs its own dashboard or syncs via rsync:

```bash
rsync -avz remote:~/.claude/projects/ ~/.claude-remote/projects/
```

Then add the path to the account's `data_paths` in `config.py`.

## Extending to API Billing

Future: `anthropic_api_scanner.py` will pull usage from the Anthropic API billing endpoint for direct API accounts. Currently only tracks Claude Code JSONL logs.

## Insight Types

| Type | Severity | Description |
|------|----------|-------------|
| `model_waste` | Amber | Project using Opus with avg output <800 tokens — Sonnet would be cheaper |
| `cache_spike` | Red | Cache creation >3x 7-day average — possible CLAUDE.md reload bug |
| `compaction_gap` | Amber | Sessions hit 80% context without /compact — context rot risk |
| `cost_target` | Green | Project hit its cost-per-session target |
| `window_risk` | Red | Current burn rate predicts hitting limit in <60 min |
| `roi_milestone` | Green | Subscription ROI crossed 2x, 5x, or 10x threshold |
| `heavy_day` | Blue | Consistent heavy usage on same day of week |
| `best_window` | Blue | Identifies quietest 5-hour block for autonomous runs |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/data?account=X` | Full analysis (all/personal_max/work_pro) |
| GET | `/api/projects?account=X` | Per-project breakdown |
| GET | `/api/insights?account=X&dismissed=0` | Active insights |
| POST | `/api/insights/{id}/dismiss` | Dismiss an insight |
| GET | `/api/window?account=X` | Window status + history |
| GET | `/api/trends?account=X&days=7` | Daily snapshots for charts |
| POST | `/api/scan` | Trigger rescan |
| GET | `/api/health` | DB size, records, last scan |

## Tech Stack

- Python stdlib only (zero pip dependencies)
- SQLite with WAL mode (`data/usage.db`)
- Single-file HTML/CSS/JS dashboard (no CDN, no build step)
- Auto-rescan every 5 minutes, auto-refresh dashboard every 60 seconds
