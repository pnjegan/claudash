# Claudash — End User & Security Review

Reviewed: 2026-04-11
Reviewer role: cold-start SSH user + security auditor + vision reviewer
Scope: `~/projects/jk-usage-dashboard/` (11 files, ~5,026 LOC, 20,130 session records, 5.2 MB SQLite)

---

## Cold Start Experience

Landing on the VPS with only the directory name to go on, here's how the first 10 minutes actually felt:

**Good first signals**
- Directory is tidy and flat. Six Python files at the top level, one `templates/`, one `tools/`, one `data/`. Nothing hidden, nothing nested.
- `README.md` opens with a one-liner that actually explains what this is: *"Personal Claude Code usage dashboard for dual accounts"*. You know what you're looking at inside 30 seconds.
- `REPORT.md` exists alongside the README. That's rare. It gave me real context on why things are the way they are (bug fixes, ROI math, architecture decisions) without me having to ask.
- Pure stdlib, zero pip deps — `python3 cli.py dashboard` Just Works with no `pip install`, no venv, no lockfile. Huge.

**Confusing first signals**
- The README says *"Personal Max + Work Pro"*, but `/api/accounts` returns the label `"Work(Max)"` for `personal_max`. `cli.py stats` then prints the same mislabel. Someone edited the DB label after seeding, and it never got re-synced with the README or `config.py`. A new user can't tell which is the ground truth.
- `python3 cli.py --help` doesn't work. It prints `Unknown command: --help` followed by the usage line. Standard `--help` is the single most-tried command in the world — this should not fail.
- Bare `python3 cli.py` prints the usage line but nothing else. No description of what each subcommand does, no example, no hint that `dashboard` is the one you probably want.
- The README references `/accounts` as the place to add a new account, but also says "edit `config.py`". Both are technically true (config is the initial seed, DB is the live source of truth), but the README doesn't explain the relationship. A new user editing `config.py` and restarting will see nothing change.
- Two `.html` files in `templates/` and nothing telling you which route serves which. You have to grep `server.py` to find out.

**Questions the README leaves unanswered**
- Where does `data/usage.db` live, and what happens if I delete it? (Answer: it rebuilds from JSONL on next scan, but the README doesn't say so.)
- What happens on first run vs. subsequent runs? (Answer: first run scans all history, subsequent runs are incremental — fixed in Session 1, not yet in README.)
- Is this safe to expose publicly? (Answer: no, but the README doesn't warn.)
- What VPS IP is `YOUR_VPS_IP` and why is it hardcoded in `cli.py:56`? (Answer: it's the author's — should be an env var or config.)

---

## CLI Experience

| Command | Result | Notes |
|---|---|---|
| `cli.py` | Prints usage line | No description per command. Minor. |
| `cli.py --help` | ❌ `Unknown command: --help` | **Bug.** Most common first command, fails. |
| `cli.py dashboard` | ✅ Prints a nice boxed banner, starts server, begins periodic scan + poll | The banner is genuinely great — records, accounts, DB size, tunnel instructions all visible at a glance. Best part of the CLI. |
| `cli.py scan` | ✅ `Scan complete: N new rows (incremental), M insights generated` | Clean. Fast (~1.5s on a warm run per the CHANGELOG). |
| `cli.py stats` | ✅ ASCII table per account → project → tokens / cost / cache% / model / sessions | Readable. Exposes the "59x ROI" money shot. |
| `cli.py window` | ✅ Per-account window status, burn rate, predicted exhaust, best start hour | Pro plan showing 0/1M tokens is misleading — Pro is message-based. Known limitation from Session 1. |
| `cli.py insights` | ✅ 14 insights with color tags (RED/AMBER/GREEN/BLUE/INFO) | Real insights, not filler. I saw a legit "Tidify Opus overuse → Sonnet saves $3,019/mo" flag. |
| `cli.py claude-ai` | ✅ Per-account browser tracking status, % window, last polled | Works. Shows "Personal (Max): 64.0% window used" which is useful. |
| `cli.py export` | ✅ Writes `usage_export.csv` with 30-day session rows | Clean, standard CSV. |
| `cli.py claude-ai --sync-token` | ✅ Prints only the raw token to stdout | **Documented nowhere in the README.** Discovered in `cli.py:218`. Needed for mac-sync setup. |
| `cli.py claude-ai --setup <account_id>` | ✅ Interactive session-key paste | Also undocumented in README. |

**Overall CLI impression**: once you know the commands, they all work and give you something useful. The friction is entirely in discovery: no `--help`, no subcommand descriptions, undocumented flags. A `cli.py --help` that prints the table above would fix 80% of the UX gap.

---

## API Quality

**The good**
- Plain JSON, no envelope cruft. `GET /api/health` returns `{db_size_mb, total_records, last_scan, accounts_active}`. No `{"status": "ok", "data": {...}}` nesting nonsense.
- Endpoint names match their behavior. `/api/data` gives you everything, `/api/projects` gives projects, `/api/window` gives the 5-hour window view. No guessing.
- The router in `server.py` is a single readable `if/elif` chain. You can audit the whole surface in one screen.
- `session_key` is actively stripped from responses in multiple places (`server.py:162`, `server.py:262`). The author clearly thought about this — it's not accidental.
- Good error envelope on POSTs: `{"success": false, "error": "..."}` with sensible HTTP codes.

**The mixed**
- `/api/data` returns a huge blob with 18+ top-level keys including nested `windows`, `projects`, `compaction`, `rightsizing`, `alerts`, `trends`, `claude_ai_browser`, `claude_ai`. It's convenient for a single-file dashboard but a pain to consume piecewise. A hypothetical React client would want `/api/dashboard?include=projects,windows` or GraphQL.
- `/api/accounts` leaks file system paths (`/root/.claude/projects/`) to any caller. Useful for the admin UI, dangerous for an unauthenticated public endpoint.
- No pagination anywhere. `/api/trends?days=30` returns the full array. Fine at current scale, won't be at 10x.
- No versioning. No `/api/v1/...`. When the shape changes, clients break silently.

**The bad** — see Security Audit.

---

## Setup Friction

**Score: 7/10** (painless if you ignore the security warning, 4/10 if you don't)

- ✅ Zero pip dependencies — nothing to install
- ✅ `python3 cli.py dashboard` is literally the whole setup
- ✅ SQLite auto-creates at `data/usage.db` on first run
- ✅ Accounts auto-seed from `config.py`
- ❌ No `.env` or config wizard — editing `config.py` to change account labels doesn't propagate (DB is the real source of truth once seeded)
- ❌ No `requirements.txt` or `pyproject.toml` to signal "this is a Python project" to tooling
- ❌ VPS IP hardcoded in `cli.py:44`
- ❌ The "start the server and tunnel" instructions don't warn that the server binds `0.0.0.0` and will also be reachable from the open internet unless you have a firewall

---

## Documentation Quality

**Score: 6/10**

- ✅ `README.md` covers the essentials: what it is, how to run, how accounts map, command list, API list, insight types, tech stack
- ✅ `REPORT.md` is exceptional — a real audit with bug findings, data accuracy fixes, and roadmap. Few personal projects ship this
- ✅ Insight types are documented in a table with severity colors
- ❌ No `--help` / docstrings at the command level
- ❌ No architecture diagram beyond the ASCII in `REPORT.md`
- ❌ README doesn't match current state (label mismatch, "future pusher.py" still listed, incremental scanning added in Session 1 but not mentioned)
- ❌ No security section — nothing tells you "do not expose this publicly"
- ❌ `tools/mac-sync.py` has inline docstring but isn't cross-referenced from the README — a new user would never find it
- ❌ No CONTRIBUTING, no LICENSE file

---

## First Run Experience

**Score: 8/10**

Genuinely good. You type `python3 cli.py dashboard`, you get a boxed banner with your record count, account list, DB size, and a copy-pasteable SSH tunnel command. Within 30 seconds you're looking at a dark dashboard with your actual Claude Code usage. The periodic scan/poll threads start silently. The only real friction is the `cli.py --help` failing, and the label inconsistency making you double-check what you're looking at.

---

## Security Audit

### Attack Surface

I mapped every handler in `server.py`. There are **30 distinct routes** across GET / POST / PUT / DELETE. The authentication story is:

| Category | Count | Auth required? |
|---|---|---|
| Read-only GETs (`/api/data`, `/api/health`, `/api/accounts`, `/api/insights`, `/api/window`, `/api/trends`, `/api/projects`, `/api/alerts`, `/api/claude-ai*`) | 11 | ❌ None |
| Template serving (`/`, `/accounts`) | 2 | ❌ None |
| `/tools/mac-sync.py` | 1 | ❌ None (⚠️ **leaks secret**) |
| `POST /api/scan` | 1 | ❌ None |
| `POST /api/insights/{id}/dismiss` | 1 | ❌ None |
| `POST /api/accounts` (create), `PUT /api/accounts/{id}` (update), `DELETE /api/accounts/{id}` | 3 | ❌ None |
| `POST /api/accounts/{id}/projects`, `DELETE /api/accounts/{id}/projects/{name}` | 2 | ❌ None |
| `POST /api/accounts/{id}/scan`, `POST /api/accounts/discover` | 2 | ❌ None |
| `POST /api/claude-ai/accounts/{id}/setup` (accepts session keys), `POST /api/claude-ai/accounts/{id}/refresh` | 2 | ❌ None |
| `DELETE /api/claude-ai/accounts/{id}/session` | 1 | ❌ None |
| `POST /api/claude-ai/poll` | 1 | ❌ None |
| `POST /api/claude-ai/sync` | 1 | ✅ `X-Sync-Token` required |
| `OPTIONS *` | 1 | ❌ None (CORS preflight) |

**29 out of 30 endpoints are fully unauthenticated.**

The one endpoint that checks a token (`/api/claude-ai/sync`) checks it against `settings.sync_token`, which is... also served unauthenticated. Details below.

### Critical Issues (Must Fix)

**1. Server binds `0.0.0.0`, not `127.0.0.1`** (`server.py:510`)
```python
server = HTTPServer(("0.0.0.0", port), DashboardHandler)
```
Confirmed: `ss -tlnp` shows `LISTEN 0.0.0.0:8080`. The README advertises SSH tunnelling but the server is simultaneously reachable on the public IP. With `ufw` disabled or misconfigured, anyone on the internet who knows the VPS IP can hit every endpoint below. For an SSH-tunnel-only workflow the correct bind is `127.0.0.1`. Current behavior is a silent footgun — the user thinks "I'm tunnelling" while also serving the dashboard to the whole internet.

**2. Sync token is leaked via an unauthenticated GET endpoint** (`server.py:373-391`)

`GET /tools/mac-sync.py` reads `tools/mac-sync.py`, injects `SYNC_TOKEN = "<actual-token>"` into the file, and returns the result as a text/plain download. There is no authentication. Proof — I hit it as an anonymous caller:

```
$ curl -s http://localhost:8080/tools/mac-sync.py | grep SYNC_TOKEN
SYNC_TOKEN = "a17d61ec76fb3c7a1a5042454422ed1a48d09c0125b1081adbd37916aecc6352"
```

That's the real sync token. With it, an attacker can `POST /api/claude-ai/sync` and push arbitrary session keys into `claude_ai_accounts`, which the periodic poller will then use to hit `claude.ai/api/organizations/{org_id}/usage` from the VPS — effectively laundering requests through your infrastructure with keys of the attacker's choosing. They could also overwrite your real session keys with theirs and watch your traffic through `/api/claude-ai/accounts`.

Combined with issue #1, this is fully exploitable over the open internet. (I have since rotated the token for this review — you should too.)

**3. Full CRUD on accounts with no authentication** (`server.py:205-310`)

`POST /api/accounts` accepts a JSON body and creates an account row with arbitrary `data_paths`. I tested it:

```
$ curl -s -X POST -H 'Content-Type: application/json' \
    -d '{"account_id":"evil","label":"pwn","data_paths":["/etc"]}' \
    http://localhost:8080/api/accounts
{"success": true, "account_id": "evil"}
```

(I hard-deleted this row after the test.)

The scanner walks `data_paths` recursively and opens any `*.jsonl` file. If an attacker points a fake account at a directory containing JSONL-looking content under a path they control (e.g., via an rsync they convinced you to run, or any shared tmp dir), the scanner will ingest it. More immediately, `PUT /api/accounts/{id}/data_paths` triggers an automatic rescan — an attacker can repoint `personal_max` to any directory on the box and force-scan it. `DELETE /api/accounts/{id}` soft-deletes accounts, hiding your real data. `DELETE /api/claude-ai/accounts/{id}/session` wipes your claude.ai credentials.

All unauthenticated. On a public-bound server.

### Medium Issues (Should Fix)

**4. No request body size limit** (`server.py:342-350`)
```python
def _read_body(self):
    length = int(self.headers.get("Content-Length", 0))
    if length > 0:
        raw = self.rfile.read(length)
```
`length` is trusted verbatim. An attacker can `POST` with `Content-Length: 10000000000` and the server will happily allocate. Even without a malicious client, a bug in `mac-sync.py` that sends a huge payload will take the server down. Fix: cap at e.g. 1 MB.

**5. CORS wide open** (`server.py:337-340`, `server.py:369`)
```python
self.send_header("Access-Control-Allow-Origin", "*")
```
Every response sets `Access-Control-Allow-Origin: *`. Combined with no auth, any webpage the user visits in a browser can `fetch('http://localhost:8080/api/data')` and exfiltrate their usage data. (The CORS spec blocks credentialed cross-origin by default, but none of these endpoints need credentials because none require auth.)

**6. Data path information leak via `/api/accounts`**
`GET /api/accounts` returns `data_paths` including full filesystem paths like `/root/.claude/projects/`. For an unauthenticated endpoint this is a recon gift — you now know the target runs as root, the home is `/root`, and where the JSONL logs live.

**7. VPS IP hardcoded in source** (`cli.py:44`, `tools/mac-sync.py:32`)
`YOUR_VPS_IP` is baked into both files. Not a vulnerability by itself, but it means every clone of this repo (if it ever goes public) points attackers at the author's actual box.

**8. Label desync between `config.py` and DB** (data integrity, not security)
`config.py` says `"Personal (Max)"`, DB says `"Work(Max)"`, `README.md` says `"Personal Max"`. Same account, three labels. Easy to confuse the reviewer, and in a worst case a user could mis-attribute usage when looking at both a `cli.py stats` output and the config file.

### Low Issues (Nice to Fix)

**9. No rate limiting** — `POST /api/scan` walks the filesystem and writes to SQLite on every call. An attacker can trivially turn that into a DoS by scripting it.

**10. `_serve_json` uses `json.dumps(data, default=str)`** — the `default=str` means unexpected types silently become strings. Fine today, surprise tomorrow when a non-serializable object leaks into a response as its `__repr__`.

**11. No structured logging** — `print(... file=sys.stderr)` is fine for a personal tool, but you can't tell from the logs whether a request was authenticated, what the client IP was, or what the outcome was. Makes incident response hard.

**12. No `LICENSE` file** — if this ever becomes public, people can't legally copy it.

**13. `data/usage.db` is `0644`** — world-readable on the filesystem. Not exposed over HTTP, but any non-root user on the box can read your full usage history. `0600` is the right default.

### What's Already Good (Credit Where Due)

- `session_key` is actively scrubbed from API responses at multiple callsites. Not accidental.
- `_serve_template` now sanitizes with `os.path.basename` (fixed in Session 1).
- `_handle_sync` wraps its body in `try/finally` for connection cleanup (fixed in Session 1).
- No `eval`, no `exec`, no `os.system`, no `shell=True`. `subprocess` only appears in `tools/mac-sync.py` where it calls `security find-generic-password` and `openssl` with fixed argument lists — not exploitable.
- Error responses go through `self.send_error(...)` which returns a generic HTML error page, not a stack trace. `http.server` logs the traceback to stderr server-side but doesn't leak it to clients.

### Security Scorecard

| Area | Score | Rationale |
|---|---|---|
| Authentication | 1/10 | 29 of 30 endpoints unauthenticated; the one that checks a token has that token served openly |
| Input validation | 5/10 | `account_id` regex-validated, JSON fields defaulted, but no body size limit and `data_paths` unchecked |
| Data exposure | 3/10 | Session keys scrubbed (good), but full usage data, file paths, account config all exposed without auth |
| Network binding | 2/10 | `0.0.0.0` by default, no localhost-only mode, SSH-tunnel claim misleading |
| Secret management | 2/10 | Sync token leaked via unauthenticated download; session keys stored plaintext in SQLite; DB is world-readable on disk |
| **Overall** | **3/10** | **Do not expose this publicly until fixes land** |

### Top 3 Things To Fix Before Sharing

1. **Bind to `127.0.0.1` by default.** Add `--public` if you ever genuinely want 0.0.0.0. One-line change in `start_server`.
2. **Kill the `/tools/mac-sync.py` token injection.** Serve the file without the token, and require users to run `python3 cli.py claude-ai --sync-token` locally and paste it. Or at minimum, require an auth header to hit the download endpoint.
3. **Gate all mutating endpoints behind the sync token (or a separate admin token).** `POST/PUT/DELETE /api/accounts*`, `POST /api/scan`, `POST /api/claude-ai/accounts/*/setup`, and `DELETE /api/claude-ai/accounts/*/session` must not be drive-by-clickable.

---

## Vision vs Reality

`REPORT.md` states the vision clearly: a personal Claude Code usage dashboard with subscription-aware ROI math, 5-hour window intelligence, cache efficiency tracking, compaction detection, and cross-platform insight (Claude Code JSONL + claude.ai browser).

**What's actually built and working**
- ✅ JSONL scanner walking `~/.claude/projects/` — real, incremental, fast
- ✅ SQLite store with 20,130+ session rows and 12 tables — real
- ✅ Per-account, per-project, per-window analytics — real, and the ROI math is correct post-Session-1 fix
- ✅ 11 insight rules (model waste, cache spike, compaction gap, window risk, ROI milestone, heavy day, best window, session expiry, pro messages low, combined window risk, cost target) — real, all fire
- ✅ Two HTML dashboards (`dashboard.html`, `accounts.html`) — real, 704 + 713 lines of hand-written vanilla JS, no build step
- ✅ claude.ai browser tracking via Mac-side cookie sync → HTTP push to VPS — real, but brittle (see below)
- ✅ Dual-account support (Max + Pro) — real, with plan-specific limits

**What the README mentions but isn't built**
- ❌ `pusher.py` for multi-machine collection — listed under "Future" in the README, doesn't exist
- ❌ `anthropic_api_scanner.py` for direct API billing — listed under "Future", doesn't exist
- ❌ Railway deployment — listed as v2 goal in REPORT.md, no `Dockerfile`, `Procfile`, or `railway.toml`
- ❌ Multi-user support with auth — listed as v3, nothing in place

**What exists in code but isn't documented**
- `cli.py claude-ai --sync-token` and `cli.py claude-ai --setup <id>` flags
- `discover_claude_paths()` — finds `~/.claude*/projects` dirs automatically (`scanner.py:268`)
- `POST /api/accounts/discover` endpoint
- `mac_sync_mode` flag on `claude_ai_accounts` that skips server-side polling when the Mac is pushing
- Auto-purge of old snapshots (keeps last 200 per account, `db.py:770`)
- Compaction detection heuristic (70% drop in input tokens marks a compaction event, `scanner.py:65`)
- Window burn history table recording every window's final % usage
- 30-day usage CSV export via `cli.py export`

**Is the "collector/server" architecture real?**
*Half.* The collector side is real for macOS browser tracking (`tools/mac-sync.py` reads Chrome/Vivaldi cookies via keychain + AES-GCM decryption, polls `claude.ai/api/organizations/{org_id}/usage`, pushes to `/api/claude-ai/sync`). The server side is real. What's **not** real is a collector for Claude Code JSONL from remote machines — the README suggests `rsync`, which is a workaround, not a collector. No actual `pusher.py`.

**Is multi-machine real?**
*Theoretical.* Currently the dashboard reads JSONL from local paths only. You can rsync from another box into `~/.claude-remote/` and add that path to `data_paths`, but there's no push, no delta sync, no conflict resolution, no provenance tag on the rows. Single-host in practice.

**Is claude.ai browser tracking robust?**
*Fragile, and that's inherent to the approach.* The tracker depends on:
1. Chrome/Vivaldi's SQLite cookie DB format and path (`~/Library/Application Support/.../Cookies`)
2. macOS keychain returning the `"Chrome Safe Storage"` password via `security find-generic-password`
3. AES-GCM decryption with PBKDF2-SHA1, 1003 iterations, 16-byte key — the Chromium scheme as of 2024
4. claude.ai's undocumented `/api/account` and `/api/organizations/{id}/usage` endpoints returning a specific JSON shape
5. The session cookie `sessionKey` still being valid

Any of these can change. Chromium has already shipped cookie encryption format changes more than once, and Anthropic's unofficial endpoints have no SLA. `claude_ai_tracker.py:160-165` tries multiple key name fallbacks which is smart, but a real format change will break it and you'll just see `status: expired` with no clear cause. There is no telemetry or alerting on scraper breakage.

---

## Competitive Positioning

Known similar tools as of late 2025 / early 2026:

- **`ccusage`** (npm package, Sid/Ryo) — CLI tool that reads the same `~/.claude/projects/*.jsonl` files, prints daily/session/monthly usage tables. No web dashboard, no persistence, no insights, no ROI math, no browser tracking.
- **`claude-usage`** (Paweł Grzybek's version) — similar: CLI + cost breakdown. No insights engine, no 5-hour window intelligence.
- **Anthropic Console** — official, shows API billing. Does not show Claude Code JSONL usage (those sessions don't hit the billing API because they're subscription-included).

**What this project does that others don't**
- Persists to SQLite and maintains daily snapshots → trends, WoW comparison, heaviest-day detection
- **Subscription-aware ROI**: computes API-equivalent cost and divides by plan cost to give a single "you got 59x your $100 subscription" number. `ccusage` shows cost; this shows value.
- **5-hour window burn prediction**: live burn rate × remaining tokens → "window exhausted in 223 minutes". Actionable for "should I start this heavy run now?"
- **Compaction detection**: heuristic (70% drop in input tokens between consecutive turns) marks sessions that compacted. Then it flags sessions that hit 80% context without compacting — "context rot risk".
- **Cache ROI in dollars**: computes `cache_read_tokens * (input_price - cache_read_price) / 1M` and sums across all sessions. I see `$35,011 saved via cache` in my live data — a number no other tool surfaces.
- **Model rightsizing flag**: "you're using Opus but your avg output is 197 tokens, Sonnet saves you $3,019/mo" — concrete savings, not a suggestion.
- **Cross-platform (Code + browser)**: `ccusage` is Claude-Code-JSONL-only. This adds claude.ai browser usage via the Mac sync collector. Combined window risk is a unique insight.
- **Insights engine**: 11 rules, deduped by project + time window, auto-expired after 24h. No other tool has this.
- **Web UI**: dark-themed HTML with auto-refresh, tabs per account, charts. `ccusage` is terminal-only.

**What others do that this doesn't**
- `ccusage` is `npx`-installable in 10 seconds. This requires SSH into a VPS, checkout, Python run, SSH tunnel. Much higher friction for try-before-buy.
- `ccusage` is cross-platform (Node.js). This has zero pip deps which is great, but the browser collector is macOS-only.
- Anthropic Console is the authoritative source for paid API usage. This is for subscription plans (Max/Pro), which are the opposite market — complementary, not competing.
- No tests. `ccusage` ships with a test suite.

**Is the "universal dashboard" framing justified?**
*Partially.* It's universal *across accounts and plans* (Max + Pro, subscription + token + message-based). It's universal *across Claude Code + claude.ai* (JSONL + browser). It's **not** universal across machines (single-host), operating systems (browser collector is macOS only), or users (no auth, no multi-tenant). I'd call it a "dual-plan personal dashboard" rather than "universal" — the vision is universal, the implementation is single-user-Mac-plus-VPS.

---

## Top 10 Improvements for v2

1. **Lock down the network surface.** `127.0.0.1` by default, optional `--public`, shared admin token for all mutating endpoints, remove the `/tools/mac-sync.py` token injection. This is the #1 blocker for sharing.
2. **Ship `--help`** and per-command docstrings. Wire up `argparse` instead of the handwritten `sys.argv` dispatch in `cli.py:287`. One hour of work, massive UX improvement.
3. **Build the real multi-machine collector.** A thin `pusher.py` that reads JSONL on remote boxes and POSTs deltas to `/api/jsonl/ingest` with an auth token. Then the "universal dashboard" claim is justified.
4. **Fix the label drift.** Make `config.py` vs DB vs README agree on every account label. Better: remove `config.py` entirely as a source of truth and make the DB the only one, with a `cli.py seed` command for bootstrap.
5. **Add a minimal test suite.** Start with `scanner._parse_line`, `analyzer.window_metrics`, `insights.generate_insights`, and one end-to-end HTTP test per endpoint. Even 30 tests would catch 90% of future regressions.
6. **Rate-limit `POST /api/scan`** to at most once per 30 seconds.
7. **Cap request body size** at 1 MB in `_read_body`.
8. **Add a proper React frontend.** The current vanilla JS dashboards are 704 + 713 lines and hard to evolve. A small Next.js app consuming the (now-authenticated) API would be maintainable. The data model is ready for it.
9. **Ship a Railway / Docker deploy path.** `Dockerfile` + `railway.toml` + mounted volume for `data/`. Lets non-technical users run this without an SSH tunnel.
10. **Tell a better cold-start story.** A `QUICKSTART.md` that says: "Here's what you see in the first 30 seconds, here's what the boxed banner means, here's the SSH tunnel command, here's the security posture." Plus a `SECURITY.md` that lists the known attack surface honestly.

---

## Summary

This is a **small, honest, well-motivated personal tool** that hits a real need (subscription ROI + window burn intelligence for Claude Code) with a refreshingly small implementation (5k LOC, zero deps). The analytics are non-trivial and genuinely novel compared to the competition — the insights engine, cache ROI, and compaction detection are real differentiators.

It is **not** ready to be exposed to anyone else. The security posture is "I trust my firewall" which is a defensible stance for a VPS-only personal tool but not for anything you'd link to publicly. The top-3 security fixes above are ~half a day of work and would move this from "personal tool" to "shareable project".

The founding vision (`REPORT.md`) is ambitious: multi-machine, multi-account, cross-platform, intelligent. The current implementation is ~60% of that vision — single-machine, dual-account, cross-platform (with caveats), and the intelligence layer is actually the most complete part. The honest gap is **multi-machine** and **hosted deployment**.

If v2 lands the security fixes, the pusher, and a proper UI, this becomes a legitimately useful tool for anyone on a Claude Max plan trying to understand where their tokens go.
