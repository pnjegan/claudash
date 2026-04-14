# Claudash Setup Guide

Personal Claude usage dashboard. Tracks token consumption, cost, cache ROI,
5-hour window burn, and per-project model efficiency across your Max/Pro/API
accounts. Zero pip dependencies, single SQLite file, single HTML page.

## Requirements

- Python 3.8+ (stdlib only — no `pip install` needed)
- Claude Code installed and used at least once (the JSONL logs under
  `~/.claude/projects/` are the data source)
- Optional: a VPS or always-on box to run it centrally
- Optional: a Mac with Chrome/Vivaldi if you want claude.ai browser tracking

## Quick start (5 minutes)

```bash
git clone https://github.com/pnjegan/claudash
cd claudash
python3 cli.py dashboard
# Opens at http://localhost:8080
```

On first run you'll see a boxed banner with your record count, account list,
and DB size. The dashboard auto-scans every 5 minutes in the background and
the browser auto-refreshes every 60 seconds.

## Running on a VPS via SSH tunnel

By default the server binds `127.0.0.1` only — it will refuse any connection
from the internet. To reach it from your laptop, forward the port over SSH:

```bash
# On your laptop:
ssh -L 8080:localhost:8080 user@your-vps-ip
# Now, in another tab on your laptop, open:
open http://localhost:8080
```

If you want the banner to show your VPS IP, set an env var before launching:

```bash
export CLAUDASH_VPS_IP=your-vps-ip
python3 cli.py dashboard
```

## Add your accounts

1. Open `http://localhost:8080/accounts`
2. Click "+ Add account"
3. Fill in:
   - **account_id**: short slug, lowercase (e.g. `work_max`)
   - **label**: display name (e.g. "Work (Max)")
   - **plan**: max / pro / api
   - **monthly cost**: your subscription price in USD (for ROI math)
   - **window limit**: 1,000,000 for Max, 200,000 for Pro, 0 for API
   - **data paths**: where Claude Code writes JSONL (default `~/.claude/projects/`)
4. Click Save — the dashboard reloads with your account as a new tab

You can also seed accounts by editing `config.py` before first run; after
that, the DB is the source of truth and editing `config.py` has no effect.

## Dashboard key (required for write actions)

Any admin action (Scan now, Add account, Dismiss insight, etc.) needs an
`X-Dashboard-Key` header. The key is auto-generated on first run. Retrieve it
with:

```bash
python3 cli.py keys
```

You'll see both `dashboard_key` and `sync_token`. Paste the **dashboard_key**
into the browser prompt the first time a write button fails — it's saved to
`localStorage` and never asked again.

The key grants full write access to your dashboard. Keep it private. Never
paste it into screenshots, chat transcripts, or commit it to source.

## Track claude.ai browser usage (optional, macOS only)

The Mac-side collector reads your Chrome/Vivaldi cookies, calls the
undocumented `claude.ai/api/organizations/{id}/usage` endpoint, and pushes the
result to Claudash. This lets Claudash show your *combined* window burn
(Claude Code + browser) rather than just the JSONL side.

```bash
# 1. On the server, get your sync_token
python3 cli.py keys

# 2. On the Mac, download the collector
curl http://localhost:8080/tools/mac-sync.py -o mac-sync.py
# (over SSH tunnel; the server no longer injects the token into the download)

# 3. Edit mac-sync.py, paste your sync_token into SYNC_TOKEN
# 4. Set VPS_IP in mac-sync.py to your server IP (or "localhost" if tunnelled)

# 5. Run it manually once to verify
python3 mac-sync.py

# 6. Schedule it every 15 minutes
crontab -e
*/15 * * * * /usr/bin/python3 /Users/you/mac-sync.py >/dev/null 2>&1
```

## What the numbers mean

- **ROI**: API-equivalent cost of your 30-day usage ÷ your monthly plan cost.
  10x means the Max plan saved you 10x its sticker price vs. pay-per-token.
- **Cache hit rate**: cache_read / (cache_read + cache_creation). Honest
  formula — a "miss" is a cache write, not a fresh input.
- **Window %**: tokens used in the current 5-hour rolling window as a share
  of your plan's limit.
- **Burn rate**: tokens per minute in the current window. Used to predict
  when you'll hit the wall.
- **Compaction events**: consecutive turns in a session where the total
  inbound context (input + cache_read) dropped by >30% — i.e. a `/compact`
  happened.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Unknown command: --help" | You're on an old version; update from git |
| Scan button silently does nothing | Browser hasn't been prompted for dashboard_key yet. Click it once and paste the key from `python3 cli.py keys` |
| Dashboard shows 0% window | No JSONL under your `data_paths`. Run Claude Code once in the account's data_path, then click Scan |
| `connection refused` from another machine | Expected — server binds `127.0.0.1` only. Use SSH tunnel |
| claude.ai browser tracking shows `expired` | Session cookie rotated. Re-run mac-sync.py after logging into claude.ai again |
| "request too large" on POST | Body exceeded 100 KB — you're sending something unusual. Check the request body |

## Uninstall

```bash
rm -rf ~/claudash
# Your JSONL logs under ~/.claude/projects/ are untouched.
```
