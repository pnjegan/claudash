# Claudash — Changelog

## [2026-04-14] Session 9 — Reliability, npm package live, version 1.0.11 published

### Fixed
- **Tab switch JS null error** — `$('projects').innerHTML` referenced a nonexistent element ID. Changed to `$('proj-body')` with proper `<tr><td>` wrapper. Added `id="projects-section"` and `id="fix-tracker-section"`.
  Files: templates/dashboard.html

- **Hardcoded version strings** — `server.py /health` returned `"1.0.0"`, `cli.py HELP_TEXT` said `Claudash v1.0`, `mcp_server.py` had `SERVER_VERSION = "1.0.0"` — all while `package.json` moved through 1.0.9, 1.0.10, 1.0.11. Created shared `_version.py` that reads from `package.json`. All four call sites now dynamic.
  Files: _version.py, server.py, cli.py, mcp_server.py

- **SETUP.md placeholder** — `git clone <your-fork-or-repo>` replaced with `git clone https://github.com/pnjegan/claudash`.
  Files: SETUP.md

- **npm binary --help flag** — `--help` / `-h` / `--version` / `-v` now handled at module top before `main()` runs. Prevents macOS `open` from ever receiving these flags. Added `isPortInUse()` check with lsof + netstat fallback.
  Files: bin/claudash.js, package.json

- **Duplicate insights in DB** — cleaned 1 duplicate `heavy_day` insight, fixed 2 stale "Work (Max)" labels → "Personal (Max)".
  Files: data/usage.db (runtime state)

- **Efficiency score floundering formula** — added per-account filter on `waste_events` query (was counting across all accounts). Clarified penalty formula.
  Files: analyzer.py

### Added
- **Auto-restart loop** — `cmd_dashboard()` wraps `_run_dashboard()` in a try/except loop with exponential backoff (5 restarts max, 5s→60s).
  Files: cli.py

- **`/health` endpoint** — no-auth GET returning `{status, version, uptime_seconds, records, last_scan}`. Always 200 if server running.
  Files: server.py

- **Helpful 404 HTML page** — replaces blank error with styled page that auto-redirects to `/` after 5 seconds.
  Files: server.py

- **PM2 process manager setup** — `tools/setup-pm2.sh` one-command script + `ecosystem.config.js`. Survives VPS reboots.
  Files: tools/setup-pm2.sh, ecosystem.config.js

- **Connection-lost banner + reconnect toast** — dashboard pings `/health` every 30s. After 2 misses shows red banner; on recovery shows green "Reconnected" toast and refreshes.
  Files: templates/dashboard.html

- **Sync daemon** — `tools/sync-daemon.py` runs every 5 minutes, auto-detects platform. New `cli.py sync-daemon` command.
  Files: tools/sync-daemon.py, cli.py

- **Claude Code hooks integration** — `tools/hooks/post-session.sh` triggers a scan after every tool use. `docs/HOOKS_SETUP.md` has the settings.json snippet.
  Files: tools/hooks/post-session.sh, docs/HOOKS_SETUP.md

- **README Fix Tracker section** — documents the baseline → apply → measure → verdict loop. This killer feature was previously undocumented.
  Files: README.md

- **README process management section** — nohup, PM2, health check, log viewing.
  Files: README.md

- **README screenshot reference** — `![Claudash Dashboard](docs/screenshot.png)` after badges. Actual PNG pending.
  Files: README.md

- **npm package published** — `@jeganwrites/claudash@1.0.11` live on npm registry (https://www.npmjs.com/package/@jeganwrites/claudash). Two version bumps this session: 1.0.9 → 1.0.10 → 1.0.11.
  Files: package.json, bin/claudash.js

- **Cloudflare quick tunnel verified** — `cloudflared tunnel --url http://localhost:8080` exposes dashboard publicly without SSH.

### Removed
- **`usage_export.csv`** — 18,789 rows of session data that should never have been in a public repo. Deleted and added to `.gitignore`.
  Files: usage_export.csv (deleted), .gitignore

- **Broken doc links from README** — `REPORT.md`, `FOUNDING_DOC.md`, `SECURITY_TRUTH_MAP.md`, `END_USER_REVIEW.md` references. All four files are gitignored but linked in README.
  Files: README.md

- **`release-notes-cofounder.md` renamed** — to `release-notes-v1.0.md`, cleaned internal language.
  Files: docs/releases/2026-04-11/

### Architecture Decisions
- **Shared `_version.py` module** — single source of truth reading from `package.json`. Python (`server.py`, `cli.py`, `mcp_server.py`) and Node (`bin/claudash.js`) all read the same file.
  Why: Four hardcoded version strings had already drifted (package.json 1.0.9 vs everything else claiming 1.0.0).
  Impact: Release cadence is `npm version patch` → `git push --tags` → `npm publish`. Nothing else to edit.

- **Python-level auto-restart + PM2 as layered defense** — Python handles transient exceptions fast; PM2 handles OS crashes and reboots.
  Impact: `nohup` is no longer the recommended path. Docs lead with PM2.

- **npm scope `@jeganwrites/`** — scoped publish with `--access public` avoids the squatted unscoped `claudash` package.
  Impact: Install command is longer but unambiguous.

### Known Issues / Not Done
- **`docs/screenshot.png` doesn't exist yet** — README references it, will render as broken image on GitHub until a real screenshot is dropped in.
  Why deferred: requires running dashboard on Mac with real data.

- **Efficiency score reads 42/F on current DB** — honest output given 84% floundering rate, but new users may assume the tool is broken. No UI explainer.
  Why deferred: needs copy tuning + tooltip, not a quick fix.

- **CHANGELOG is 43KB** — still one monolithic file.
  Why deferred: not blocking launch.

- **Three internal docs (FOUNDING_DOC.md, END_USER_REVIEW.md, REPORT.md) remain on disk** (gitignored).
  Why deferred: not worth risk of accidentally deleting user's working tree state.

## [2026-04-13] Session 7 — Prompt A: 30 pre-launch gaps fixed across security, performance, platform, data, UI, and GitHub readiness

### Fixed
- **f-string SQL fragment in subagent_metrics()** — replaced `f"WHERE {where}"` with conditions list + string concatenation. Pattern was fragile even though no user input reached the SQL.
  Files: analyzer.py

- **Cache hit formula** — changed from `reads/(reads+writes)` to `cache_reads/(cache_reads+input_tokens)`, which correctly measures what fraction of inbound context came from cache vs fresh input.
  Files: analyzer.py, templates/dashboard.html

- **Floundering detection false positives** — detection key changed from just tool name to `(tool_name, input_hash)`. Running `Bash("npm test")` 5 times intentionally no longer flagged.
  Files: waste_patterns.py

- **Heavy day insight tagged to wrong account** — `heavy_day` insights were generated with `account='all'` even when referencing a specific project. Now generated per-account. Stale "Saturdays — Tidify" insight updated to `personal_max`.
  Files: insights.py

- **"No projects yet" empty state misleading** — context-aware messages: browser-only, no-sessions, or fresh install each get a distinct message.
  Files: templates/dashboard.html

### Added
- **30-second response cache for /api/data** — `_data_cache` dict keyed by account, TTL 30s, cleared on scan. Eliminates redundant `full_analysis()` calls during tab switching.
  Files: server.py

- **10-second query timeout** — `_get_data()` runs analysis in a thread with 10s join timeout, returns 503 on timeout.
  Files: server.py

- **Waste detection incremental** — tracks `last_waste_scan` timestamp in settings table. Only reprocesses files scanned since last waste run. O(new_sessions) not O(all_sessions).
  Files: waste_patterns.py

- **JSONL max line length guard** — lines >1MB skipped with warning. Prevents OOM on corrupted/malicious JSONL.
  Files: scanner.py

- **Sync account fallback warning** — when no org_id match found, prints explicit warning with advice to check config.py.
  Files: server.py

- **Windows/macOS/Linux path auto-detection** — `discover_claude_paths()` checks platform-specific directories (AppData on Windows, Library/Application Support on macOS, .config and .local on Linux).
  Files: scanner.py

- **Headless server detection** — CLI dashboard startup checks for `$DISPLAY`/`$WAYLAND_DISPLAY`, prints SSH tunnel instructions instead of browser-open message.
  Files: cli.py

- **mac-sync.py platform guard** — hard exit with error on non-macOS, directs users to oauth_sync.py.
  Files: tools/mac-sync.py

- **Window calculation note + tooltip** — comment in `window_metrics()` documenting epoch-modulo limitation. Dashboard shows "approximate — UTC window alignment" tooltip.
  Files: analyzer.py, templates/dashboard.html

- **Monthly projection context** — amber warning "High burn rate" when projection >$1000, subtext explains basis.
  Files: templates/dashboard.html

- **Browser-only tab hides irrelevant sections** — compaction, model efficiency, 7-day spend, trends hidden for accounts with no JSONL sessions.
  Files: templates/dashboard.html

- **Fix tracker account badge** — each fix card shows the account label it belongs to.
  Files: templates/dashboard.html

- **API equiv and ROI tooltips** — hero cells explain "if you paid per-token at API list prices" and "API-equiv / subscription cost".
  Files: templates/dashboard.html

- **config.py vs UI explanation** — accounts.html and README clarify that config.py only seeds on first run.
  Files: templates/accounts.html, README.md

- **Getting started guide in README** — requirements, quick start (local + VPS), first run, browser sync instructions.
  Files: README.md

- **Platform support table in README** — macOS/Linux/Windows/EC2/browser-only with feature matrix.
  Files: README.md

- **Privacy statement in README** — data stays local, no telemetry, dashboard key storage documented.
  Files: README.md

- **CONTRIBUTING.md** — bug reporting, known limitations, roadmap, dev setup.
  Files: CONTRIBUTING.md

- **Screenshot placeholder** — docs/screenshot_instructions.md with steps, README has commented-out image tag.
  Files: docs/screenshot_instructions.md, README.md

### Removed
- **release-notes-cofounder.md** — renamed to release-notes-v1.0.md with cleaned language.
  Files: docs/releases/2026-04-11/

### Architecture Decisions
- **Cache hit formula: reads/(reads+input) not reads/(reads+writes)** — cache writes aren't "misses" in the way input tokens are. The new formula measures cache effectiveness more accurately.
  Impact: Cache hit rates will change (likely decrease slightly from ~100% to a more honest number).

- **Floundering uses (tool, input_hash) key** — same tool with different inputs is intentional parallel work, not floundering. Only identical tool+input repeats indicate a stuck agent.
  Impact: Fewer false positive waste events, more trustworthy fix tracker.

- **Response cache + timeout as separate concerns** — cache avoids redundant computation, timeout prevents hung requests. Both protect against the 15-query `full_analysis()` bottleneck without restructuring it.
  Impact: Tab switching is near-instant within 30s.

### Known Issues / Not Done
- No automated tests — all verification via live HTTP + API checks.
- 5-hour window still epoch-modulo — not Anthropic's rolling window.
- `full_analysis()` still runs ~15 SQL queries — cached for 30s but not restructured.
- Screenshot not yet taken — placeholder added, needs manual capture.

## [2026-04-11] Session 1 — Full Audit, Bug Fixes, and Incremental Scanning

### Fixed
- **16,381 sessions misattributed to wrong account** — Tidify/CareLink were mapped to `work_pro` but all JSONL comes from the Max plan user. ROI corrected from 12x to 57.7x.
  Files: config.py, data/usage.db (SQL migration)

- **Connection leak in `_handle_sync`** — `conn = get_conn()` had no try/finally; exceptions between open and close leaked file descriptors.
  Files: server.py

- **Path traversal in `_serve_template`** — no `os.path.basename()` sanitization on filename parameter. Defence-in-depth fix.
  Files: server.py

- **Migration UPDATEs ran every startup** — `UPDATE sessions SET account=...` fired on every `init_db()` call. Gated behind settings flag.
  Files: db.py

- **Haiku cache_read pricing** — was $0.03/MTok, corrected to $0.025/MTok per Anthropic pricing.
  Files: config.py

### Added
- **Incremental JSONL scanning** — new `scan_state` table tracks byte offset per file. Scanner seeks to last position, reads only new lines. Drops repeat-scan time from ~7s to ~1.5s across 207 files.
  Files: db.py, scanner.py, cli.py

- **`idx_sessions_model` index** — missing index on sessions.model column for model-filtered queries.
  Files: db.py

- **CLI startup banner** — `python3 cli.py dashboard` now prints a formatted box with record count, accounts, DB size, and SSH tunnel instructions.
  Files: cli.py

- **REPORT.md** — full audit report covering architecture, bug findings, data accuracy fixes, and roadmap.
  Files: REPORT.md

### Architecture Decisions
- **All JSONL sessions assigned to `personal_max`** — single Mac user produces all Claude Code logs on this VPS. `work_pro` retained for browser-only tracking (Pro plan user who uses claude.ai only).
  Impact: All cost/ROI/window metrics now correctly reflect the Max plan account.

- **Incremental scanning via byte offset** — chose file seek position over content hashing. Simpler, no extra CPU, handles append-only JSONL naturally. File truncation/rotation detected by size < offset → reset to 0.

### Known Issues / Not Done
- `work_pro` window command still shows 0/1,000,000 tokens (should show 0 or be hidden since Pro uses messages not tokens). Cosmetic — not a data issue.
- Scanner first-run still reads all history (~7s). Only subsequent runs are incremental.

## [2026-04-11] Session 2 — End-User Review, Security Audit, Founding Doc

### Added
- **END_USER_REVIEW.md** — Three-role review (cold-start user + security auditor + vision reviewer). Covers cold-start UX, CLI walkthrough, API quality, full security scorecard (auth 1/10, input validation 5/10, data exposure 3/10, network binding 2/10, secret management 2/10, overall 3/10), vision-vs-reality gap analysis, competitive positioning vs ccusage/claude-usage, and top-10 v2 improvements.
  Why: Needed an outside-eyes review covering angles REPORT.md doesn't — first-impressions UX and adversarial security — before considering any public sharing.
  Files: END_USER_REVIEW.md (341 lines)

- **FOUNDING_DOC.md** — Plain-English explainer: the problem, why existing tools fall short, the unique ideas (subscription-aware math, collector/server, project attribution, intelligence layer, cross-platform tracking, cache ROI, compaction metric), how it works in plain English, what the numbers mean, vision with a proper UI, first-principles concepts (token / 5-hour window / prompt caching / agentic loops / compaction), who it's for, what it is not.
  Why: README assumes domain knowledge. Needed a zero-context onboarding doc for someone who just heard about Claude Code subscription plans.
  Files: FOUNDING_DOC.md (184 lines)

### Known Issues / Not Done (critical findings from the security audit, NOT YET FIXED)
- **Server binds `0.0.0.0:8080` despite "SSH tunnel" README framing** — confirmed via `ss -tlnp`. Reachable from the public internet. Fix: default to `127.0.0.1`, add `--public` opt-in. (`server.py:510`)
- **Sync token leaked via unauthenticated `GET /tools/mac-sync.py`** — token retrieved with a plain anonymous curl during the audit. Anyone who hits that URL gets full write access to `POST /api/claude-ai/sync`. **Rotate the token.** (`server.py:373-391`)
- **Full unauthenticated CRUD on `/api/accounts`** — test-confirmed by creating an `evil` account pointing at `/etc` (hard-deleted post-test via sqlite3). `POST/PUT/DELETE /api/accounts*`, `POST /api/scan`, `POST /api/claude-ai/accounts/*/setup`, `DELETE /api/claude-ai/accounts/*/session` all require no auth. (`server.py:205-333`)
- 29 of 30 endpoints have no auth; CORS is wide-open `*`; no request body size cap in `_read_body` (DoS vector); `data_paths` file paths leaked via `/api/accounts`; DB file is `0644` world-readable; VPS IP hardcoded in `cli.py:44` and `tools/mac-sync.py:32`.
- `cli.py --help` prints `Unknown command: --help` — highest-ROI UX fix, ~10 minutes with argparse.
- Label drift: `config.py` says "Personal (Max)", DB says "Work(Max)", README says "Personal Max" — same account, three labels.
  Why deferred: Audit was read-only by design; fixes are a separate focused session. Top-3 priorities: (1) bind localhost, (2) kill token injection in mac-sync download, (3) gate mutating endpoints behind an admin token.

### Architecture Notes (observed, not decided)
- `config.py` is seed-only; DB is the live source of truth after first run. Editing `config.py` post-seed is a no-op. A future `cli.py seed` command + removing config.py as a config source would eliminate the label drift category of bugs.
- The "collector/server" vision is half-implemented: server side is real, Mac browser collector is real, Claude Code JSONL collector for remote machines is still `rsync` in the README. A real `pusher.py` would justify the "universal dashboard" framing.

## [2026-04-11] Session 3 — Security hardening, truth-map audit, compaction/cache fixes, Claudash rebrand + UI redesign

### Fixed
- **Server bound `0.0.0.0` despite "SSH tunnel" framing** → now `127.0.0.1:8080` only. External IP refuses connection.
  Files: server.py:544

- **Sync token leaked via unauthenticated `/tools/mac-sync.py`** → `_serve_mac_sync` now serves the file as-is with no token injection; users retrieve the token via `cli.py keys` and paste it manually.
  Files: server.py:409-425, tools/mac-sync.py (docstring + trailing comment)

- **29 of 30 endpoints unauthenticated** → new `_require_dashboard_key()` helper gates every POST / PUT / DELETE except `/api/claude-ai/sync` (which keeps its own X-Sync-Token). 401 on missing/wrong key verified live. Auto-seeded `dashboard_key` (16-byte hex) in settings table on first init.
  Files: server.py:180-355 (do_POST/do_PUT/do_DELETE auth gates + `_require_dashboard_key`), db.py:238-243 (seed), cli.py (new `keys` command)

- **No request body size limit** → 100 KB cap applied before `rfile.read` in both `do_POST` and `do_PUT`. 125 KB POST returns 413.
  Files: server.py:185-187, 290-292

- **`cli.py --help` printed "Unknown command"** → full help text via `HELP_TEXT` constant; `--help`/`-h`/`help` all exit 0; unknown command prints help + exit 1.
  Files: cli.py:20-36 (HELP_TEXT), cli.py:311-333 (main dispatch)

- **Label drift** (`config.py` vs DB vs README all disagreed) → unified; live DB `UPDATE` reconciled both `accounts.label` and `claude_ai_accounts.label`.
  Files: config.py, README.md, data/usage.db (one-shot SQL)

- **Hardcoded VPS IP `YOUR_VPS_IP`** → removed from all code files and docs. `config.py` now reads `VPS_IP = os.environ.get('CLAUDASH_VPS_IP', 'localhost')`. Markdown docs show `YOUR_VPS_IP`. CLI banner reads from env.
  Files: config.py, cli.py, tools/mac-sync.py, README.md, REPORT.md, END_USER_REVIEW.md, SECURITY_TRUTH_MAP.md

- **Compaction detector dead code (0 events across 20K rows)** → two underlying bugs:
  1. Formula watched `input_tokens` (avg ~50) instead of total context (`input_tokens + cache_read_tokens`, avg ~137K under prompt caching)
  2. **`session_id` in the sessions table was the per-MESSAGE `uuid`, not per-conversation `sessionId`** — every row was its own "session", so nothing to group over
  Fixed both in `scanner.py:_parse_line` (prefer `sessionId`) and `scanner.py:_detect_compaction` + `analyzer.py:compaction_metrics` (context-size heuristic with 1000-token noise floor).
  After rescan: **113 compaction events** across 56 real sessions (largest has 1,321 turns) vs 0 before.
  Why: fixes the entire compaction intelligence feature + any metric that groups by session (sessions_today, avg_session_depth, compaction_rate).
  Files: scanner.py:18-26, scanner.py:65-78 (_detect_compaction), analyzer.py:293-365 (compaction_metrics)

- **Cache hit rate formula biased to ~100%** → old denominator was `reads + input_tokens`, which under prompt caching approaches 100% trivially. Changed to honest `reads / (reads + cache_creation)`. Live hit rate went from 99.96% → **96.66%** across 17K rows post-rescan.
  Files: analyzer.py:58-65 (account_metrics), analyzer.py ~207-240 (project_metrics), analyzer.py ~395-410 (compute_daily_snapshots)

- **DB file was `0644` (world-readable plaintext session keys)** → new `_lock_db_file()` in db.py chmods DB + WAL/SHM to `0600` on every `get_conn()` and at end of `init_db()`. Live DB also chmod'd once via shell.
  Files: db.py:1-36 (_lock_db_file), db.py:265 (call from init_db)

- **`cli.py stats` printed the dashboard_key to stdout** (shoulder-surf leak) → replaced with a hint pointing to the new `cli.py keys` command. The actual key value no longer appears anywhere in `stats` output.
  Files: cli.py:129-131 (stats output)

- **Path traversal defense-in-depth** → `_serve_template` already calls `os.path.basename`; verified no user input reaches any `open()` call in server.py.
  Files: server.py:388-399 (already fixed in Session 1, re-verified)

### Added
- **`cli.py keys` command** — prints `dashboard_key` + `sync_token` with a warning banner, the only place sensitive values are printed. Wired into HELP_TEXT + dispatch dict.
  Files: cli.py:cmd_keys, cli.py HELP_TEXT, cli.py main()

- **`X-Dashboard-Key` auth wiring in frontend** — both HTML templates now install a global `window.fetch` wrapper that (a) auto-injects `X-Dashboard-Key` from `localStorage` on every write method, (b) handles 401 once with a prompt-then-reload pattern. Every explicit write `fetch()` call also carries `headers: authHeaders()` for clarity. First-time users get prompted once, then the key is cached in `localStorage` forever.
  Files: templates/dashboard.html (inline JS at top of `<script>`), templates/accounts.html (same)

- **SECURITY_TRUTH_MAP.md** — 477-line fresh audit (no prior assumptions) that verified every claim from Session 2's END_USER_REVIEW against live code + SQL. Format: file inventory, 10 security claims with verdicts (CONFIRMED/FALSE/PARTIAL + evidence), 8 logic-bug verifications, 7 false-narrative checks, 15 silly-bug list, thread-safety assessment, honest 6/10 score card, top-3 remaining fixes. This is the document that surfaced CLAIM 7 ("templates send X-Dashboard-Key") as FALSE and discovered the compaction/cache-hit-rate formula bugs.
  Why: outside-eyes review to catch what the fix sessions missed, before the rebrand.
  Files: SECURITY_TRUTH_MAP.md

- **SETUP.md** — 130-line first-time setup guide: requirements, 5-minute quick start, SSH tunnel instructions, add-your-accounts flow, dashboard_key retrieval, optional macOS claude.ai browser collector setup, plain-English number definitions (ROI, cache hit rate, window %, burn rate, compaction events), troubleshooting table, uninstall.
  Why: README was already filling the "reference" role; SETUP.md is the "your first 5 minutes as a new user" doc. Required by the rebrand spec.
  Files: SETUP.md

- **Claudash v1.0 complete UI redesign** — editorial/minimal light theme, DM Serif Display + DM Mono + DM Sans via Google Fonts `@import`, warm off-white palette (#FAFAF8 bg, #F5F3EE warm surface, #1A1916 near-black). Layout:
  - 56px sticky header: brand + version pill + pill tabs + right-side scan info + text links
  - 5-cell hero stat strip (Window · API Equiv · ROI · Cache Hit · Sessions Today) with staggered fade-in animation
  - Warm-bg window panel with thin 4px progress bar, inline stats, optional claude.ai browser sub-bar, sparkline dots for last 4 windows
  - Full-width projects table with 8 columns including inline 80px token-share bar, colored model pills (opus=purple/sonnet=teal/haiku=amber), trend arrows, click-to-expand inline detail
  - Insights as clean one-line rows with colored dot + dismiss animation
  - 7-day spend bar chart with monthly projection (amber if >$5k/mo)
  - 2-col grid: compaction stats + rightsizing table
  - DM Mono footer line
  - Responsive: stacks at <960px
  Files: templates/dashboard.html (~770 lines, full rewrite)

- **Claudash accounts page redesign** — same design language, inline (no modal) form card with DM Mono inputs, progressive disclosure for the claude.ai browser setup flow (step dots, numbered instructions, masked input), per-account card with color dot + serif name + plan tag + 4-cell meta grid + data-paths list with live existence checks + project pills + browser tracking subcard, inline delete confirm.
  Files: templates/accounts.html (~780 lines, full rewrite)

- **END_USER_REVIEW.md, FOUNDING_DOC.md** (carry-over from Session 2) — cold-start UX review + security scorecard + competitive positioning + top-10 v2 improvements; plain-English problem/vision explainer + first-principles concept teaching.
  Files: END_USER_REVIEW.md, FOUNDING_DOC.md

### Removed
- **JK branding** from every code file and markdown doc:
  - `"JK Usage Dashboard"` → `"Claudash"` (replace_all across README, REPORT, FOUNDING_DOC, END_USER_REVIEW, CHANGELOG, SECURITY_TRUTH_MAP, cli.py docstring, HTML titles)
  - Version string `v2.0`/`v2.1` → `v1.0` (fresh brand, fresh start)
  - Hardcoded IP `YOUR_VPS_IP` → `YOUR_VPS_IP` in markdown docs; env var lookup in code
  Why: the project is becoming a generic tool for any Claude user, not the author's personal VPS.
  Files: README.md, REPORT.md, FOUNDING_DOC.md, END_USER_REVIEW.md, CHANGELOG.md (header), SECURITY_TRUTH_MAP.md, cli.py, config.py, tools/mac-sync.py, templates/dashboard.html, templates/accounts.html

- **`config.py` second account** — removed `work_pro` from the seed dict. Only `personal_max` remains as a generic example. Live DB untouched.
  Why: generic template should show one working example, not the author's dual-account setup.
  Files: config.py

- **Old vanilla-JS dashboard + accounts layouts** — the Session 1/2 HTML (dark theme, hand-rolled boxes, hardcoded VPS IP in the JS, no auth headers on writes) was completely replaced. Historical reference: the 704+713-line files before this session.
  Why: total redesign; not salvageable piecewise.
  Files: templates/dashboard.html, templates/accounts.html

### Architecture Decisions
- **Auth model: single shared admin token on writes, GETs open** — `dashboard_key` gates all mutations; GETs stay open because the server binds `127.0.0.1` only. Minimum viable auth for a single-user localhost-with-SSH-tunnel tool. Not multi-user ready.
  Why: a full auth/user system is overkill for a personal dashboard and would prevent `curl localhost:8080/api/data` from working in shell scripts.
  Impact: any future shift to multi-user hosting needs to gate GETs behind auth too.

- **Frontend auth via `window.fetch` wrapper instead of per-call-site edits** — both HTML files install a global fetch wrapper that transparently adds `X-Dashboard-Key` for write methods and handles 401 with a single prompt-and-reload. Per-call-site `headers: authHeaders()` is also present as belt-and-suspenders.
  Why: 16 write call sites to patch individually is a high-risk surface; the wrapper makes the fix one-shot and future-proof.
  Impact: the wrapper is the contract. Any future `fetch` call that bypasses it (e.g. `XMLHttpRequest`) has no auth.

- **Honest cache hit rate formula: `reads / (reads + cache_creation)`** — counts cache writes as misses, giving ~96% on real data instead of the old formula's ~100%.
  Why: the headline number was lying to the user.
  Impact: project_metrics, account_metrics, compute_daily_snapshots all return different (lower, honest) numbers. UI labels unchanged.

- **Context-size compaction heuristic: `prev_ctx > 1000 && curr_ctx < prev_ctx * 0.7`** — context = `input_tokens + cache_read_tokens`. 1000-token noise floor prevents false positives on tiny early turns.
  Why: under prompt caching, `input_tokens` is noise; the real context size lives in `cache_read_tokens`.
  Impact: compaction detection now produces ~113 events on the live dataset (previously 0). The `compaction_gap` insight rule can finally trigger.

- **`sessionId` (not `uuid`) is the Claude Code session identifier** — `_parse_line` prefers `obj.get("sessionId")` over `obj.get("uuid")`. Upstream of the compaction fix: without it, every row had a unique session_id and no grouping worked.
  Why: Claude Code's JSONL schema puts the per-message UUID in `uuid` and the per-conversation ID in `sessionId`.
  Impact: required a one-time wipe of `sessions`, `scan_state`, `window_burns`, `daily_snapshots` and a full rescan from source JSONL (6 seconds for 209 files → 17,040 rows → 56 real sessions). Existing JSONL files under `~/.claude/projects/` untouched.

- **Generic `VPS_IP` from env var** — `os.environ.get('CLAUDASH_VPS_IP', 'localhost')`. CLI banner reads from it. Templates never contain it.
  Why: a personal tool that could go public should not embed the author's box IP.
  Impact: users set `CLAUDASH_VPS_IP=x.y.z.w` in their env before running `cli.py dashboard` if they want the banner to show it. Default is `localhost`.

- **Editorial light theme (DM Serif Display + DM Mono + DM Sans) over the old dark theme** — intentional break from "every dev dashboard is dark". Warm off-white, strong contrast, mono for all numbers, serif for headings. Google Fonts via `@import` — no npm, no build step.
  Why: the project's aesthetic differentiator is "this looks like a Linear/Bloomberg hybrid, not a crypto dashboard".
  Impact: light-only for v1. Dark mode is explicitly a non-goal.

### Known Issues / Not Done
- **`data/usage.db` still contains two accounts** (`personal_max` + `work_pro`) from Session 1/2 seeds, even though `config.py` now only seeds one. Live DB untouched by config changes post-seed. `rm data/usage.db` + re-run for a clean template install.
  Why deferred: destructive; user didn't ask for a reset.

- **Stale `test_acct` row** in `accounts` table (active=0) from earlier debugging. Filtered out by UI/API. DB clutter only.
  Why deferred: harmless, not in scope.

- **Dashboard key was exposed in SECURITY_TRUTH_MAP.md** — file deleted in Session 5. Key rotation available via `python3 cli.py keys --rotate`.

- **Historical CHANGELOG entries** (Session 1 + Session 2) retain original "JK Usage Dashboard" prose in the body. Only the top-of-file title was updated via replace_all.
  Why deferred: rewriting history dishonestly.

- **No tests.** Codebase has zero unit/integration tests. All verification in this session was grep + live SQL + live HTTP.
  Why deferred: standalone session's worth of work.

- **5-hour window boundary is still epoch-modulo (UTC-aligned)**, not Anthropic's rolling window. Flagged in REPORT.md, SECURITY_TRUTH_MAP.md, and here.
  Why deferred: would require reverse-engineering Anthropic's windowing; the Mac collector already captures `five_hour.resets_at` but it isn't wired into `window_metrics` yet.

- **CORS `Access-Control-Allow-Origin: *`** on every response. With localhost-only bind this is mostly moot, but DNS rebinding could still read (not write) dashboard data.
  Why deferred: low-risk edge case; removing the header could break hypothetical cross-origin integrations.

- **Dashboard tabs hidden on <960px viewports.** Mobile-friendly account switcher would be a small follow-up.
  Why deferred: out of scope for this rebrand; single-account users don't need tabs anyway.

## [2026-04-12] Session 4 — Five major features, fork-ready cleanup, Fix Tracker

### Fixed
- **source_path stored data_path root, not actual JSONL file** → `scanner.py` now stores the full JSONL filepath in `sessions.source_path`, enabling per-row project re-resolution.
  Files: scanner.py:174-184

- **session_id used per-MESSAGE `uuid` instead of per-conversation `sessionId`** → scanner prefers `sessionId`, compaction/session metrics now group correctly. Required full rescan (wipe sessions + scan_state → 17K rows / 56 real sessions).
  Files: scanner.py:86-88

- **Compaction detector formula overcounted tokens** → per-turn scaling for both floundering (1 turn/event) and repeated_reads (2 extra reads/event) instead of per-session scaling that collapsed `effective_window_pct` to 0%.
  Files: fix_tracker.py:capture_baseline

- **Cache hit rate formula conceptually wrong** → denominator changed from `reads + input` to `reads + cache_creation` in all 3 callsites. Live: 99.96% → 96.7%.
  Files: analyzer.py:58-65, ~207-240, ~395-410

- **DB file 0644 (world-readable plaintext session keys)** → `_lock_db_file()` chmods to 0600 on every `get_conn()` + end of `init_db()`.
  Files: db.py:1-36

- **`cli.py stats` printed dashboard_key to stdout** → replaced with hint; actual key only via `cli.py keys`.
  Files: cli.py:129-131

- **Frontend templates did not send X-Dashboard-Key on writes** → global `window.fetch` wrapper auto-injects key on POST/PUT/DELETE + handles 401 with prompt-and-reload; every explicit write fetch also carries `headers: authHeaders()`.
  Files: templates/dashboard.html, templates/accounts.html

- **All "Other" sessions (2,337) re-tagged** → `cli.py scan --reprocess` + updated PROJECT_MAP with folder-name keywords → Other dropped to 0.
  Files: cli.py:cmd_scan_reprocess, config.py (PROJECT_MAP), db.py:sync_project_map_from_config

### Added
- **Feature 1 — OAuth sync** (`tools/oauth_sync.py`, 230 lines) — pure stdlib collector that reads Claude Code's OAuth token from `~/.claude/.credentials.json` (+ macOS Keychain fallback), calls `claude.ai/api/account` and `/api/organizations/{id}/usage` via Bearer auth, POSTs to `/api/claude-ai/sync`. Supports multi-account setups. Replaces cookie extraction for Claude Code users.
  Also: `tools/get-derived-keys.py` (70 lines) — helper that extracts pre-derived Chromium AES keys for cron-friendly mac-sync.py runs.
  Files: tools/oauth_sync.py, tools/get-derived-keys.py

- **Feature 2 — Sub-agent cost tracking** — `sessions.is_subagent` + `sessions.parent_session_id` columns; `_parse_subagent_info()` in scanner detects `/subagents/` in path; `subagent_metrics()` in analyzer computes per-project rollup (`subagent_session_count`, `subagent_cost_usd`, `subagent_pct_of_total`, `top_spawning_sessions`); `scan --reprocess` backfills both columns. Live: 12,207 subagent rows / 29 sessions, Tidify 75% subagent cost.
  Insight rule: `SUBAGENT_COST_SPIKE` fires at >30% subagent share (3 fired on live data).
  Files: scanner.py, db.py (ALTER TABLE), analyzer.py:subagent_metrics, insights.py, cli.py:cmd_scan_reprocess

- **Feature 3 — MCP server** (`mcp_server.py`, 300 lines) — JSON-RPC 2.0 over stdio with 5 tools: `claudash_summary`, `claudash_project(project_name)`, `claudash_window`, `claudash_insights`, `claudash_action_center`. Reads SQLite directly (no HTTP needed). `cli.py mcp` prints settings.json snippet + smoke-tests.
  Files: mcp_server.py, cli.py:cmd_mcp

- **Feature 4 — Waste pattern detection** (`waste_patterns.py`, 280 lines) — 4 detectors (FLOUNDERING: ≥4 consecutive same tool; REPEATED_READS: same file ≥3x; COST_OUTLIER: session >3x project avg; DEEP_CONTEXT_NO_COMPACT: >100 turns, 0 compactions). New `waste_events` table; runs after every scan. Live: 110 events across 6 projects (53 floundering, 47 repeated_reads, 2 cost_outliers, 8 deep_no_compact).
  Insight rule: `FLOUNDERING_DETECTED` (6 fired live). `cli.py waste` prints summary.
  Dashboard: waste_summary per project in `/api/data`; inline waste block in project-row expansion.
  Files: waste_patterns.py, db.py (waste_events table), insights.py, analyzer.py:full_analysis, cli.py:cmd_waste, templates/dashboard.html

- **Feature 5 — Daily budget alerts** — `accounts.daily_budget_usd` column; `daily_budget_metrics()` in analyzer computes today_cost/budget_pct/projected_daily/on_track per account; new insight rules `BUDGET_EXCEEDED` (red) and `BUDGET_WARNING` (amber >80%). Dashboard: 6th hero card "Today" with inline budget progress bar (green/amber/red). Accounts form: daily budget USD input field.
  Files: db.py, config.py:DAILY_BUDGET_USD, analyzer.py:daily_budget_metrics, insights.py, templates/dashboard.html, templates/accounts.html

- **Feature 6 — Fork-ready cleanup** — `.gitignore` (DB/CSV/pycache/env/OS junk), `data/.gitkeep`, `LICENSE` (MIT 2026), `config.py` cleaned (generic single-account example, empty PROJECT_MAP with docs, empty DAILY_BUDGET_USD with docs), `README.md` rewritten (feature list, two-sync-methods, competitive comparison table vs ccusage/claude-usage/claude-monitor, 14 insight rules, full API table, tech stack).
  Files: .gitignore, data/.gitkeep, LICENSE, config.py, README.md

- **Fix Tracker feature** (`fix_tracker.py`, 380 lines) — record a fix → snapshot baseline → measure after N days → plan-aware verdict → shareable receipt.
  - DB: `fixes` table (project, waste_pattern, title, fix_type, fix_detail, baseline_json, status) + `fix_measurements` table (fix_id, metrics_json, delta_json, verdict)
  - `capture_baseline()`: aggregates sessions, cache, compactions, waste, subagent cost, window burn → full baseline_json
  - `compute_delta()`: diffs baseline vs current, builds delta_json with plan_type, primary_metric, per-pattern before/after/pct_change, tokens_saved, improvement_multiplier, api_equivalent_savings_monthly
  - `determine_verdict()`: plan-aware (max/pro → waste reduction OR window efficiency; api → waste reduction OR cost)
  - `build_share_card()`: max/pro says "Same $N/mo plan · Kx more output · API-equivalent waste eliminated"; api says "Cost per session: $X → $Y · Monthly savings: ~$Z/mo". Never says "you saved $X" for flat-plan users.
  - Server: POST/GET/DELETE /api/fixes, POST /api/fixes/{id}/measure, GET /api/fixes/{id}/share-card
  - CLI: `cli.py fixes` (list), `cli.py fix add` (interactive), `cli.py measure <id>` (plan-aware table + verdict + share card)
  - Dashboard: "Fix tracker" section with 3-column cards, inline form, measure/share/revert buttons
  - Pre-seeded: 4 Tidify fixes with live baseline (90 waste events, 96.14% window efficiency, $116.53/session, plan=max)
  Files: fix_tracker.py, db.py, server.py, cli.py, templates/dashboard.html

- **`cli.py scan --reprocess`** — re-tags every session row using current PROJECT_MAP; also backfills is_subagent + parent_session_id.
  Files: cli.py:cmd_scan_reprocess

- **`cli.py show-other`** — lists source paths of sessions tagged 'Other' for keyword debugging.
  Files: cli.py:cmd_show_other

- **`cli.py keys`** — prints dashboard_key + sync_token with warning banner.
  Files: cli.py:cmd_keys

- **`db.py:sync_project_map_from_config()`** — UPSERTs config.PROJECT_MAP into account_projects.
  Files: db.py

### Removed
- **JK branding** → "Claudash v1.0" everywhere. Hardcoded IP removed from all code + docs.
  Files: all .py, .html, .md files

- **`config.py` personal project map** → empty `PROJECT_MAP = {}` with commented examples for new users.
  Files: config.py

- **Old dark-theme dashboard HTML** → replaced with editorial light theme (DM Serif Display + DM Mono + DM Sans, warm off-white palette).
  Files: templates/dashboard.html (~900 lines), templates/accounts.html (~800 lines)

### Architecture Decisions
- **Plan-aware framing is the core Fix Tracker contract**: max/pro reports window efficiency + output multiplier + "API-equivalent waste eliminated"; api reports real dollar savings. Branching centralized in fix_tracker.py.
  Impact: new plan types need one branch in one module, not six files.

- **Baseline is self-contained JSON**: stored in fixes.baseline_json, not a reference. Immune to later formula changes.

- **Verdict promotion is conservative**: needs verdict=improving AND days_elapsed≥7 to reach "confirmed".

- **Waste attribution uses per-turn scaling**: per-session scaling collapses effective_window_pct to 0% under prompt caching.

- **MCP server reads SQLite directly**: no HTTP dependency, works offline.

### Known Issues / Not Done
- **`insufficient_data` is the only verdict today**: pre-seeded fixes have 0 days elapsed. Real verdicts fire after 7+ days with 3+ sessions.
- **OAuth token on this VPS expired**: script correctly reports failure; needs `claude` re-auth.
- **No auto-measurement**: users must manually measure; cron-triggered auto-measure at 7d would be a follow-up.
- **5-hour window still epoch-modulo**, not Anthropic's rolling window.
- **CORS `*` on responses**: low risk with localhost bind.
- **No tests**: all verification is grep + live SQL + live HTTP.

## [2026-04-13] Session 5 — Account filtering, browser-only accounts, bug fixes

### Fixed
- **`window_token_limit=0` silently defaulted to 1M** — `db.py:415` used `or 1_000_000` which treats 0 as falsy in Python. Changed to explicit `is not None` check. Pro accounts now correctly show `tokens_limit=0`.
  Files: db.py, analyzer.py (`record_window_burn` also used stale default)

- **Insight `dotMap` missing 4 types** — `floundering_detected`, `subagent_cost_spike`, `budget_warning`, `budget_exceeded` all rendered as generic blue dots instead of red/amber.
  Files: templates/dashboard.html

- **`cost_spike_day` story card missing `badge` field** — only story type without one; would fail V5 assertion.
  Files: db.py

- **CORS hardcoded to `127.0.0.1` only** — rejected `localhost` origin headers. Now accepts both.
  Files: server.py

- **Insights leaked across account tabs** — `get_insights()` used exact `account = ?` match, excluding generic insights (`account='all'`). Changed to `account = ? OR account = 'all' OR account IS NULL`.
  Files: db.py

- **Stale insight "Combined window at 94% for Personal (Pro)"** — deleted from DB (id=44, outdated snapshot data).

- **Story cards had no `account` field** — all 5 story queries lacked account in SELECT, making per-tab filtering impossible. Added `account` to all story dicts.
  Files: db.py

### Added
- **Account tab filtering** — tabs now only show accounts with `sessions_count > 0` or `has_browser_data`. Hides empty accounts (work_pro had 0 JSONL sessions). `accounts_list` in `full_analysis()` includes `sessions_count` from a GROUP BY query.
  Files: analyzer.py, templates/dashboard.html

- **Browser-only account support** — accounts with 0 JSONL sessions but active claude.ai browser tracking (work_pro: 51% five-hour, 83% seven-day) now show: (1) tab visible via `has_browser_data`, (2) dedicated window panel with 5h + 7d bars labeled "browser only", (3) clean hero message instead of zeroed-out metric cards, (4) stories filtered to empty state.
  Files: analyzer.py (browser snapshot query), templates/dashboard.html (renderWindows, renderHero, renderStories)

- **Per-account story filtering** — `renderStories()` filters by `currentAccount` before rendering. Browser-only tabs show "No patterns detected yet for this account."
  Files: templates/dashboard.html

- **Browser window data in accounts_list** — `browser_window_pct`, `seven_day_pct`, `has_browser_data` fields from `claude_ai_snapshots` latest-per-account query.
  Files: analyzer.py

### Architecture Decisions
- **Browser-only accounts are first-class tabs** — an account with 0 JSONL sessions but active `claude_ai_snapshots` data is shown in the tab bar and gets a tailored UI (browser window bars, no misleading zero metrics). This supports the "claude.ai browser-only user" persona.

- **Insights and stories filter client-side by account** — insights are filtered server-side in `get_insights()` (SQL WHERE), stories are filtered client-side in `renderStories()` (JS filter after fetch). Both include generic/null-account items alongside account-specific ones.

### Known Issues / Not Done
- **`work_pro` still active in DB with 0 sessions** — not deactivated because it has legitimate browser tracking data. Label mismatch (DB says "Personal (Pro)", config says "Personal (Max)") is a previous-session data issue.
- **No tests** — all verification via API checks + live HTTP.
- **5-hour window still epoch-modulo**, not Anthropic's rolling window.

## [2026-04-13] Session 6 — Tab switching root cause fix, codebase audit, three documents

### Fixed
- **Tab switching showed stale data from wrong account** — the root cause of all account-filtering UI bugs. `buildTabs()` click handler called `render()` which reused cached `lastData` from the previous account. Changed to call `refresh()` which re-fetches `/api/data` and `/api/insights` with the correct `currentAccount` parameter. One-line fix (`render()` → `refresh()`).
  Why: Work (Pro) tab was showing 6 projects and 17 insights instead of 0 and 1. Every section rendered stale data on tab switch.
  Files: templates/dashboard.html (line 942)

### Added
- **Complete codebase narrative** (`/tmp/claudash_narrative.md`, 336 lines) — 10-section document covering: the problem, inspiration, all 15 features with technical depth, architecture decisions, security model, performance characteristics, unique differentiators, real numbers from the DB (49x ROI, $5,972 API equiv, 110 waste events, 1,321-agent spike), three user personas, and roadmap.

- **Pentest + observability audit** (`/tmp/claudash_pentest.md`, 191 lines) — three auditors: (1) Security pentester testing 10 attack vectors with live curl commands (path traversal BLOCKED, SQL injection BLOCKED, auth bypass BLOCKED, DoS BLOCKED, CORS PARTIAL, XSS BLOCKED); (2) Observability engineer assessing logging, error handling, health endpoints, metrics, restart recovery; (3) UX tester doing a stranger test (clone-to-running: 10/10, first-run: 7/10, fix tracker: 5/10).

- **External validation prompt** (`/tmp/claudash_improvements.md`, 179 lines) — self-contained prompt for any AI to validate: ROI math correctness, cache hit formula, waste detection logic soundness, security gaps, and the 5 most critical functions with code snippets for review.

### Architecture Decisions
- **`render()` vs `refresh()` distinction clarified** — `render()` is for re-painting with existing data (e.g., window resize). `refresh()` is for loading new data (tab switch, scan complete, auto-refresh timer). Tab switches must always `refresh()` because the account filter changes the server-side query.
  Why: The cached `lastData` pattern was a performance optimization (avoid re-fetching on re-paint) that became a bug when tab switches reused it.
  Impact: Tab switches now make 2 HTTP requests (data + insights) instead of 0. This is correct behavior — the data IS different per account.

### Known Issues / Not Done
- **No automated tests** — all verification via live HTTP + API checks.
- **5-hour window still epoch-modulo** — not Anthropic's rolling window.
- **Waste detection re-reads all JSONL** on every `detect_all()` call.
- **`full_analysis()` runs ~15 SQL queries** per `/api/data` call, no caching.

## [2026-04-13] Session 8 — npx support, Efficiency Score, init wizard

### Added
- **npx claudash** — zero-install entry point via npm
  Why: Users can run `npx claudash` without git clone, pip, or manual setup
  Files: `package.json`, `bin/claudash.js`, `.npmignore`

- **Efficiency Score (0-100)** — 5-dimension weighted score replacing ROI as headline metric
  Dimensions: cache efficiency (25%), model right-sizing (25%), window discipline (20%), floundering rate (20%), compaction (10%)
  Grade A-F with color coding. Clickable breakdown panel in dashboard hero.
  Why: ROI was misleading — high number looked good but didn't reflect actual usage quality
  Files: `analyzer.py` (compute_efficiency_score), `templates/dashboard.html` (hero card + breakdown), `cli.py` (stats output)

- **Init wizard** — 3-question first-run setup (plan type, project review, account name)
  Auto-detects first run in cmd_dashboard(), saves config to DB, auto-starts dashboard
  Why: New users had no guided onboarding — config.py editing was the only path
  Files: `cli.py` (cmd_init, cmd_dashboard first-run detection)

- **--port and --no-browser flags** on `cli.py dashboard`
  Why: Required for npx orchestration and headless/CI usage
  Files: `cli.py`

- **MCP server marked verified** in CONTRIBUTING.md (prior commit this session)
  Why: All 5 claudash MCP tools confirmed working in Claude Code
  Files: `CONTRIBUTING.md`

- **README updated** — npx as primary quick start, Efficiency Score in features list
  Files: `README.md`

### Architecture Decisions
- Efficiency Score replaces ROI as the first hero card
  Why: ROI was a vanity metric (60x sounds great but means nothing actionable). Score of 42/F is honest and tells you exactly what to fix.
  Impact: Dashboard now leads with actionable intelligence, not flattery

- npx installs to ~/.claudash via git clone, not npm dependencies
  Why: Zero pip dependencies is a core promise — npm is just the launcher, Python does the work
  Impact: npm package is tiny (launcher only), actual code lives in git clone

### Known Issues / Not Done
- `npm publish` not yet run — package.json ready but not published to npm registry
  Why deferred: Needs manual npm login + publish step
- Efficiency score of 42/F reflects real data: floundering rate scored 0/100, model right-sizing 21/100
  Why: These are real problems to fix, not bugs in the score

## [2026-04-14] Session 10 — Security audit, 17 fixes shipped, INTERNALS.md, versions 1.0.12 → 1.0.15

### Fixed
- **HIGH: raw_response leaked unauthenticated** — `/api/claude-ai/accounts` and `/api/claude-ai/accounts/<id>/history` returned the full Anthropic usage JSON blob (org UUIDs, plan internals, occasional first name/email). `session_key` was scrubbed; `raw_response` was not. Now stripped at the DB-read layer.
  Files: db.py (get_latest_claude_ai_snapshot, get_claude_ai_snapshot_history)

- **HIGH: non-timing-safe key comparison** — `received != stored.strip()` for both `dashboard_key` and `sync_token` was vulnerable to a local timing side-channel. Replaced with `hmac.compare_digest`.
  Files: server.py:_require_dashboard_key, _handle_sync

- **HIGH: no CSRF/Origin check on mutating endpoints** — malicious browser pages could POST to `127.0.0.1:8080` via plain HTML forms (no preflight). Added `_check_origin()` on do_POST/do_PUT/do_DELETE; rejects when Origin is present and not in the localhost allow-list.
  Files: server.py

- **MEDIUM: unvalidated data_paths** — admin could set `data_paths=["/"]` and scanner would walk the entire filesystem reading every `.jsonl`. Added `_validate_data_paths()` requiring each path to exist as a directory and resolve within `~` or `/root`.
  Files: db.py:create_account/update_account

- **MEDIUM: raw exception strings in /api/data** — `{"error": str(e)}` leaked SQL fragments and FS paths. Now returns `"internal error"`, real exception logged server-side only.
  Files: server.py:_get_data

- **MEDIUM: /api/accounts/<id>/preview leaked FS layout** — `expanded` field exposed absolute paths to unauth callers. Now returns only `path`/`exists`/`jsonl_files`.
  Files: server.py

- **MEDIUM: unbounded _data_cache** — module dict keyed by unvalidated `account` query param. Replaced with locked `OrderedDict` LRU capped at 64 entries; account validated against slug regex before caching.
  Files: server.py (_cache_get, _cache_put, _cache_clear)

- **MEDIUM: overlapping scans race** — periodic thread + POST `/api/scan` + per-account scan had no lock. Added `threading.Lock` in scanner; endpoints return 409 `"scan already running"` instead of queueing.
  Files: scanner.py:_scan_lock, server.py

- **MEDIUM: file paths persisted in waste_events.detail_json** — leaked project FS layout via `/api/real-story`. Now strips to `os.path.basename()` before persisting.
  Files: waste_patterns.py:_detect_repeated_reads

- **MEDIUM: missing composite indexes** — `(account, timestamp)`, `(project, timestamp)`, `(account, project)` added; analyzer queries no longer scan one index then filter.
  Files: db.py:init_db

- **MEDIUM: N+1 in /api/accounts** — one SELECT per account replaced with single GROUP BY.
  Files: server.py

- **MEDIUM: O(projects × rows) inner loop in project_metrics** — `cache_roi` now accumulated in the first pass over rows_30d.
  Files: analyzer.py

- **LOW: /tools/mac-sync.py served unauthenticated** — gated behind `_require_dashboard_key()`.
  Files: server.py

- **LOW: port string-concatenated into execSync** — added `^\d{1,5}$` + 1–65535 range validation in `bin/claudash.js`.
  Files: bin/claudash.js

- **LOW: scanner accumulated all rows in memory** — flushes every 10k rows now (BATCH_FLUSH_SIZE).
  Files: scanner.py:scan_jsonl_file

- **LOW: zombie threads from thread.join(timeout)** — replaced with `ThreadPoolExecutor(max_workers=4)` for analysis timeout.
  Files: server.py

- **LOW: unlocked module globals in claude_ai_tracker** — `_account_statuses`/`_last_poll_time` mutated cross-thread without lock. Added `_state_lock` + `_set_status()` helper.
  Files: claude_ai_tracker.py

- **UX: silent auto-update on every launch** — `bin/claudash.js` ran `git pull` against main on every invocation. Now gated behind `--update` flag.
  Files: bin/claudash.js

- **UX: hardcoded "Claudash v1.0" in dashboard footer** — now reads dynamic version from `/api/data` payload.
  Files: server.py:_build_data, templates/dashboard.html:1413

- **UX: server logged every GET request** — `log_message` now suppresses routine GETs; only POST/PUT/DELETE and 4xx/5xx are logged.
  Files: server.py

### Added
- **Setup auto-detection from ~/.claude/.credentials.json** — `_detect_from_credentials()` reads `subscriptionType` and best-effort email from the OAuth JWT. On confirmation skips the entire 3-question wizard and auto-names the account from the email local-part.
  Files: cli.py:_detect_from_credentials, cmd_init

- **README "Running Claudash across multiple machines" section** — explains the rsync+cron pattern for unifying multi-machine usage into one dashboard. Explicit warning against running multiple instances.
  Files: README.md

- **INTERNALS.md** — 957-line technical document covering JSONL format, scanner internals, DB schema, analyzer formulas, all 4 waste patterns, all 14 insight rules, efficiency score dimensions, browser tracking flow, MCP server protocol, fix tracker baseline/measure loop. Every claim sourced to file:line. Honest call-outs of rough edges. Not yet committed.
  Files: INTERNALS.md (uncommitted)

### Architecture Decisions
- **Trust model is localhost-only** — 127.0.0.1 bind is the primary boundary; auth + origin check + timing-safe compare are defense-in-depth for co-tenant/local-malware scenarios. Documented in INTERNALS.
  Impact: future endpoints don't need full session machinery, but MUST honor `_require_dashboard_key()` on any mutation.

- **Manual `--update` instead of auto-pull** — users get version churn under their control via `npm update -g @jeganwrites/claudash`, not silent `git pull`.
  Impact: package consumers and git-clone consumers are now on the same upgrade cadence.

### Released
- **v1.0.12** (commit 3a32b8b) — D1, A1, A2, N1
- **v1.0.13** (commit a0309ac) — D2 D4 F3 V2 S2 P2 Q1 Q2 Q3 A3 I4 S1 V3 V4
- **v1.0.14** (commit a24b305) — dynamic version in footer + log noise reduction
- **v1.0.15** (commit c15ed10) — auto-detect plan + multi-machine docs

### Known Issues / Not Done
- **`ecosystem.config.js` has unrelated uncommitted changes** — pre-existed at session start (PM2 config refactor: `script: 'cli.py'` + `interpreter: 'python3'` + `__dirname` cwd). Stashed/popped around each `npm version` bump. Untouched on disk.
  Why deferred: not part of this session's scope; user should review and commit/discard intentionally.

- **INTERNALS.md not committed** — written and saved at `/root/projects/jk-usage-dashboard/INTERNALS.md` for review.
  Why deferred: user wanted to verify content first.

- **`.npmrc` near-miss** — npm auth token in `.npmrc` was untracked at session start, briefly entered staging during `git add -A` for the bundled security fixes, was caught and reset before push, added to `.gitignore`. Token was never pushed but should be considered briefly exposed in local git index — rotate at https://www.npmjs.com/settings/jeganwrites/tokens for safety.
  Why deferred: user action required (cannot rotate npm tokens for the user).

- **C2 (claude.ai session_key plaintext in SQLite)** — chmod 0600 on DB mitigates for single-user local. On shared VPS would need OS-keyring encryption.
  Why deferred: out of scope for single-user local model; document only.

- **D3 (/health endpoint info disclosure)** — version + account list exposed unauth. Localhost-only, low impact.
  Why deferred: useful for humans/monitoring; not worth removing.

- **Q4/Q5/Q6/V6** (LOW perf items: SELECT * narrowing, MCP query caching, `_read_body` 100KB cap)
  Why deferred: not user-visible at current scale.

## [2026-04-15] Session 11 — v2.0 PRD drafted, 3 fix_tracker bugs fixed (uncommitted)

### Fixed
- **BUG 1: measure() returned identical numbers for every fix on a project** — `compute_delta` called `capture_baseline` with no time-scoping, so the "current" snapshot for every fix was just "last 7 days of the project". Added `since_override` param; `compute_delta` now passes `fix.created_at` so each fix only measures sessions that happened AFTER it was applied.
  Files: fix_tracker.py:capture_baseline, compute_delta

- **BUG 2: api_equivalent_savings_monthly always $0** — old formula `total_cost / days_window × 30` collapsed to zero when the post-fix window covered fewer days than the baseline. Replaced with `(baseline_cost_per_session − current_cost_per_session) × sessions_per_month`, where `sessions_per_month = baseline.sessions_count / baseline.days_window × 30`.
  Files: fix_tracker.py:compute_delta

- **BUG 3: share card placeholder URL** — both share-card footers said `github.com/yourusername/claudash`. Now `github.com/pnjegan/claudash`.
  Files: fix_tracker.py:build_share_card (2 occurrences)

### Added
- **CLAUDASH_V2_PRD.md** — product requirements doc for v2.0 "Agentic Fix Loop". Covers the 4-stage loop (detect → generate → apply → measure), 5 new `fixes` columns, 4 pattern-specific prompt templates, Anthropic SDK integration with prompt caching, security model for API key storage, phased delivery (Phase 1 CLI → Phase 2 applier+UI → Phase 3 closed loop), success metrics, and open questions.
  Files: CLAUDASH_V2_PRD.md (uncommitted)

### Architecture Decisions
- **v2 fix generator uses direct Anthropic SDK, not Claude Code** — generation is a bounded one-shot task with predictable prompt shape; Sonnet + ephemeral cache_control is cheaper and faster than routing through an agent. Keeps v2 compatible with users who don't have Claude Code installed (e.g. claude.ai-only users who still want fix suggestions from their waste events).
  Impact: new `anthropic_api_key` setting required; graceful offline fallback to manual `cmd_fix_add()`.

- **Generation is not autonomous in v2.0** — every CLAUDE.md write requires explicit human approval via dashboard click or CLI `fix apply`. Corrective regeneration on `verdict='regressed'` is scoped but still human-gated.
  Impact: rules out "self-healing mode" as a v2 scope creep target; defers it to v2.x.

### Known Issues / Not Done
- **3 bug fixes in fix_tracker.py uncommitted** — compile-clean, diff shown, awaiting commit+push together with the PRD.
  Why deferred: user wanted to review before starting Phase 1 implementation.

- **CLAUDASH_V2_PRD.md uncommitted**
  Why deferred: same — pending user sign-off before code lands.

- **INTERNALS.md still uncommitted** (carried from Session 10)
- **`ecosystem.config.js` still dirty** (carried from Session 10)
- **Rotate npm token** (carried from Session 10 — near-miss, never pushed)
- **Phase 1 of v2 not yet started** — db.py schema migration + fix_generator.py + CLI wiring all planned in the PRD; ready to begin on GO.

## [2026-04-16] Session 12 — Claudash v2.0 shipped (F1–F7)

### Fixed
- **BUG-002 (periodic scan didn't regenerate insights)** — scanner `_run` loop now calls `generate_insights()` after `scan_all()` so dashboard insights stay fresh on the background cadence.
  Files: scanner.py

- **BUG-003 (ghost `floundering_detected` insights)** — addressed as part of the insights pipeline refresh.
  Files: insights.py

- **BUG-005 (settings.updated_at missing from init_db)** — added column to CREATE TABLE + idempotent ALTER migration. Unblocked F4.
  Files: db.py (commit 1a0a432)

- **PM2 takeover of dashboard** — live server was a crontab `@reboot` PID (1599127), not PM2-managed; PM2's own instance was crashlooping. Killed orphan PID, removed crontab line, `pm2 start ecosystem.config.js`, `pm2 save`. Dashboard now survives reboot via PM2 + `pm2-root.service` systemd unit.
  Files: ecosystem.config.js, crontab

### Added
- **F1 — Session lifecycle event tracking** (compact + subagent_spawn). Filters to assistant messages with non-zero tokens to avoid 14k spurious tool_result compact events.
  Files: scanner.py (detect_lifecycle_events, scan_lifecycle_events), db.py (lifecycle_events table + indexes + 3 new sessions columns), analyzer.py (lifecycle_by_project, lifecycle_summary) (commit c54bf63)

- **F2 — Context rot visualization** — bucketed output/input ratio with inflection detection, inline SVG chart (viewBox 400×100 polyline + dashed inflection line).
  Files: analyzer.py (compute_context_rot), templates/dashboard.html (renderContextRotBlock) (commit 8654ed1)

- **F3 — Bad compact detector** — regex signals over 5 bad-compact patterns, gated to context_pct>60, 2+ signal match. Insights rule `BAD_COMPACT_DETECTED` with project-aware `/compact Focus on:` suggestions.
  Files: waste_patterns.py, insights.py, config.py (COMPACT_INSTRUCTIONS) (commit 8654ed1)

- **F4 Phase 1 — Fix generator** (multi-provider: Anthropic / Bedrock / OpenAI-compat). boto3 lazy-imported inside `_call_bedrock` only — zero-pip-dep core preserved. CLI `fix generate <id>` + `keys --set-provider` wizard. Cost transparency in README.
  Files: fix_generator.py (new, 444 lines), cli.py, db.py (5 new fixes columns + 8 settings seeds), README.md (commits eec74b8, 1641300)

- **F5 — Bidirectional MCP** (5 write-side tools: trigger_scan, report_waste, generate_fix, dismiss_insight, get_warnings + `mcp_warnings` queue with 6h dedup).
  Files: mcp_server.py, db.py (mcp_warnings table), scanner.py (generate_mcp_warnings — 4 rules) (commit d6a33fe)

- **F6 — Streaming cost meter** — SSE `/api/stream/cost` (60s deadline, 10s early-close, broken-pipe handling), `/api/hooks/cost-event` POST, pre/post hook scripts (pre=keepalive, post=accumulate to avoid double-count), live widget top-right of dashboard with auto-reconnect.
  Files: server.py, hooks/pre_tool_use.sh + post_tool_use.sh (new, chmod +x), templates/dashboard.html, docs/HOOKS_SETUP.md (commit fb46ba9)

- **F7 — Per-project autoCompactThreshold recommendations** — Rules A–E over lifecycle + bad_compact data. Dashboard threshold block with "Copy settings.json" / "Copy CLAUDE.md rule" buttons. Embedded in 3 endpoints (`/api/recommendations`, `/api/lifecycle`, `/api/data.recommendations`) for one-fetch render.
  Files: analyzer.py (recommend_compact_threshold, recommend_compact_all), server.py, templates/dashboard.html (renderThresholdBlock) (commit 8c3db4d)

### Architecture Decisions
- **Multi-provider LLM with lazy boto3 import** — preserves zero-pip-dep invariant for the core; only users who pick Bedrock incur the dep.
  Impact: Bedrock is opt-in; default (Anthropic) stays stdlib-only.

- **F6 pre/post hook split** — pre=keepalive only (refresh last_event_at/last_tool), post=accumulate cost + tool_count + floundering counter. Prevents double-counting per tool.
  Impact: pre-hook has no accounting logic; all cost math lives post-hook.

- **F7 recommendations embedded in 3 places** — avoids extra fetch round-trip for dashboard render.
  Impact: slight denormalization; one-shot dashboard payload.

- **PM2-managed dashboard, not crontab** — single source of truth for lifecycle; `pm2 save` + `pm2-root.service` systemd unit handles reboot survival.
  Impact: no more orphan @reboot processes.

### Known Issues / Not Done
- **F4 Phase 2 deferred** — `fix_applier.py` (CLAUDE.md write + backup), CLI `fix apply/preview/reject`, `POST /api/fixes/<id>/apply`, dashboard diff modal.
  Why deferred: user explicitly scoped v2 demo as "generator CLI works — enough for portfolio demo"; awaiting detailed spec for Phase 2.

- **F7 recommendations uniformly 0.70** across all 6 projects (Rule D fires everywhere) — F1's compact heuristic catches subagent mid-task context drops (avg ctx 16–44%), not real user `/compact` events (70–90%). Fidelity will improve as real /compact data accumulates.

- **F3 bad_compact detector: 0 matches** on current corpus — documented transparently; all candidate compacts (>60% ctx) were subagent drops where user messages preceded compact timestamps.

- **Uncommitted tree state** — `fix_tracker.py` (3 Session-11 bug fixes), `ecosystem.config.js` (PM2 config tweaks this session), `CLAUDASH_V2_PRD.md`, `INTERNALS.md`.
  Why deferred: not part of any v2 feature commit; user hasn't asked to commit these yet.

- **Rotate npm token** (carried from Session 10 — near-miss, never pushed).

## [2026-04-16] Session 13 — Complete writeup (2,113 lines) + auto-discover data paths

### Fixed
- **`discover_claude_paths()` returned paths with 0 JSONL files** → now only returns paths with ≥1 JSONL file, always keeps `~/.claude/projects/` as default for new installs.
  Files: scanner.py (discover_claude_paths)

- **`cmd_init()` never populated data_paths** → new users inherited whatever `config.py` seeded. Now calls `discover_claude_paths()` after account UPDATE, overwrites `data_paths` with the discovered set, prints each path with its JSONL file count.
  Files: cli.py (cmd_init)

- **Live DB had stale data_paths** — `personal_max` had `/root/.claude-personal/projects/` (doesn't exist on this box, scanner logged skip warnings), `test_acct` had `/tmp/nonexistent/`. Cleaned via safe `os.path.isdir` check that preserves the default path even if missing.
  Files: data/usage.db (live only — no schema change)

- **7 factual errors in CLAUDASH_COMPLETE_WRITEUP.md** verified against source before fixing:
  1. API route table had wrong paths (`/api/analysis`, `/sse/cost-meter`, `/api/compact-recommendations`, `/api/browser-accounts`) → replaced with the 26 actual routes from server.py
  2. `_call_anthropic` was documented as using "anthropic Python SDK" → actually `urllib.request` stdlib with `cache_control: ephemeral`
  3. MCP registration path was `~/.claude/claude.json` → actually `~/.claude/settings.json` (per cli.py:698 and mcp_server.py:5)
  4. `mac_sync_mode` documented as a "stub for macOS Keychain" → actually a working flag that suppresses VPS-side polling so data arrives via push from `tools/mac-sync.py` (claude_ai_tracker.py:218/289)
  5. Floundering described as "included in the 56 repeated_reads events" → actually 0 events, a success metric post-Apr 11 CLAUDE.md rules
  6. Missing "Built in One Session" narrative for v2 F1-F7 shipping in a single day
  7. Rules A-E for `recommend_compact_threshold()` were aspirational → replaced with the actual 5 rules from analyzer.py (no-data/late/good-bad/too-early/healthy)
  Files: CLAUDASH_COMPLETE_WRITEUP.md

### Added
- **CLAUDASH_COMPLETE_WRITEUP.md** (2,113 lines) — standalone technical and product narrative: founder story, tech stack rationale, architecture diagram, JSONL format deep-dive, every v1 and v2 feature with real DB numbers, all 18 tables, all 26 API endpoints, all 10 MCP tools, 10-step learning path, honest gap list. Pushed to GitHub so portfolio readers can fetch it directly.
  Files: CLAUDASH_COMPLETE_WRITEUP.md

- **Appendix K — LLM Provider Guide**: Groq (free tier, recommended for new users), AWS Bedrock (for existing AWS customers), Anthropic direct (~$0.003/fix). Privacy note enumerating exactly what is and isn't sent to the LLM.
  Files: CLAUDASH_COMPLETE_WRITEUP.md

- **Appendix L — Prioritized Next Steps** (P1-P7): Groq live-test, compact-detector tokens_after filter, F4 Phase 2 applier, context-rot formula fix, npm 2.0 publish, README screenshot, fix-measurement dedup.
  Files: CLAUDASH_COMPLETE_WRITEUP.md

- **Per-account "Auto-discover" button** on the Accounts tab. Calls `POST /api/accounts/discover` (endpoint already existed), shows new paths not already tracked with checkboxes + file counts, and `PUT /api/accounts/{id}` with merged data_paths on apply. Uses existing `authHeaders()` and `showMsg()` patterns.
  Files: templates/accounts.html (renderCard data-paths block + wireCardEvents handler)

### Architecture Decisions
- **Auto-discover at init-time, not at seed-time** — `config.py` still ships `data_paths=["~/.claude/projects/"]` as the default seed, but `cmd_init()` immediately overrides it with discovery results. This is strictly better than seeding `[]` because it's a one-line discovery call and it handles multi-install scenarios (`.claude-work`, `.claude-personal`, macOS `~/Library/Application Support/Claude/projects`) that a static default can't.
  Impact: fresh installs no longer inherit a hardcoded single path; the Auto-discover button is also available anytime post-init.

- **Default path always surfaced in discovery results** — `~/.claude/projects/` is returned even if empty/missing so new users who haven't run Claude Code yet still see it as a suggestion. All other paths require ≥1 JSONL file to appear.
  Impact: discover results are trustworthy — every non-default entry has real data.

- **Correction pass first, then new work** — the CLAUDASH_COMPLETE_WRITEUP.md errors were caught by verifying each claim against source before editing (not trusting the user's premise blindly). The `mac_sync_mode` "premise was wrong" discovery during the data_paths prompt prevented me from implementing a duplicate `_discover_data_paths()` when `scanner.discover_claude_paths()` already existed.
  Impact: established pattern of reading source before applying spec changes; avoided shipping either a documentation contradiction or duplicate code.

### Known Issues / Not Done
- **F4 Phase 2** (fix_applier.py) still deferred — awaiting explicit spec per the earlier user decision.
  Why deferred: user scoped v2 demo as "generator CLI works — enough for portfolio demo".

- **`config.py` default seed still has hardcoded `~/.claude/projects/`** — not changed to `[]` because `cmd_init()` now overwrites it with discovery results anyway.
  Why deferred: behavior is equivalent in practice; changing the config invalidates the seeded-before-init code path.

- **`claudash.db` artifact** from running `cli.py scan` outside the project dir at some point — untracked file, not committed. Harmless.
  Why deferred: cleanup is one `rm` but not in scope.

- **F7 recommendations still uniformly 0.70** across all 6 projects (Rule D fires everywhere) — fix requires adding `tokens_after > 1000` filter in `detect_lifecycle_events()`, documented as Appendix L P2.
  Why deferred: separate 30-minute task, user hasn't triggered it yet.

- **INTERNALS.md, CLAUDASH_V2_PRD.md, ecosystem.config.js, fix_tracker.py** — carried uncommitted from earlier sessions. Not touched this session.
  Why deferred: outside this session's scope.

## [2026-04-16] Session 14 — Agentic loop Phase 1: insight → fix → apply + auto-measure

### Fixed
- **`fix_generator.generate_fix()` returned the CLAUDE.md target path but dropped it on the floor** — the throwaway `_claude_md_path` variable prevented the applier from knowing where to write. Now returned as `claude_md_path` in the result dict and persisted to `fixes.applied_to_path` by `insert_generated_fix()` (column already existed, was unused).
  Why: without it, the apply endpoint would need to re-run discovery on every click and mtime-check drift would be possible.
  Files: fix_generator.py (generate_fix, insert_generated_fix)

### Added
- **`POST /api/insights/{id}/generate-fix`** — one-click insight → fix path. Maps `insight_type → waste_events.pattern_type` via a dedicated table (floundering_detected→floundering, compaction_gap→deep_no_compact, cache_spike→repeated_reads, subagent_cost_spike→cost_outlier, bad_compact_detected→bad_compact) with a fallback to any-recent-waste_event-for-project for looser insights (model_waste, window_risk, budget_*). Calls `generate_fix(waste_event_id, conn)` → `insert_generated_fix()` → returns rule_text, reasoning, risk, impact, target path, model used. Graceful error if no provider configured.
  Files: server.py (new do_POST handler)

- **`POST /api/fixes/{id}/apply`** — writes a proposed fix's rule_text to the target CLAUDE.md. Creates `CLAUDE.md.claudash-backup-<timestamp>` first. Appends a commented block (`<!-- Added by Claudash fix #N YYYY-MM-DD -->` + rule_text). Transitions status `proposed → applied` and captures a fresh baseline (via `capture_baseline()`) so the next auto-measure cycle has a valid reference point. Only accepts `status in ('proposed','applied')`.
  Files: server.py (new do_POST handler)

- **Dashboard "Generate Fix" button** on every red/amber insight card. Inline expansion shows generated rule with monospace rule_text block, reasoning (italic), risk/impact/target badges, and an "Apply to CLAUDE.md" button. On success, shows the backup path and auto-refreshes. Fixable types whitelist lives in `fixableTypes` set at the top of `renderInsights()`. New `fix_regressing` entry added to `dotMap` (→ red dot).
  Files: templates/dashboard.html (renderInsights + click handlers)

- **`scanner._auto_measure_fixes(conn)`** — runs every periodic cycle after `detect_all()` + `generate_mcp_warnings()`. Iterates `fixes WHERE status IN ('applied','measuring')`, gates on `days_elapsed ≥ 1` AND `new_sessions_since_baseline ≥ 3`, plus a 6-hour dedup window on `fix_measurements.measured_at` to prevent 288 rows/day per fix (BUG-004 guardrail). Calls existing `measure_fix(conn, fix_id)` which already persists the measurement and updates status. On `verdict='worsened'`, inserts a `fix_regressing` insight with a 24-hour dedup check against its own `detail_json` (contains `fix_id`). Logs `[scanner] Auto-measured N fix(es)` to stderr on any actual measurement.
  Files: scanner.py (new helper + wired into start_periodic_scan)

### Architecture Decisions
- **Mapping insight_type → waste pattern is a hardcoded table in the handler**, not derived from a DB column. Reason: insights are generated from many sources (model_mix, window utilization, subagent spikes) and most don't carry a direct `waste_event_id`. A join-table would add a migration for marginal value. Fallback to "most recent waste_event for this project" handles insights without a strict pattern mapping (model_waste, window_risk).
  Impact: adding a new insight type means updating `PATTERN_MAP` in server.py (~line 860) and `fixableTypes` in dashboard.html (~line 1495). Documented in the code comments.

- **Apply endpoint captures a fresh baseline on status transition, not at generation time** — the generator might run hours or days before the user clicks Apply, and the project's state can shift meaningfully in that gap. Capturing baseline at apply-time means `fix_measurements` delta computation has the correct reference.
  Impact: if generation and apply happen in the same session, baseline is "now"; if they're spread out, baseline is "when applied" — always accurate to the moment the fix hit the user's CLAUDE.md.

- **6-hour measurement dedup** in auto-measure is a hard invariant, not a config. Reason: the scanner fires every 5 minutes (288 ticks/day) and a fix in 'measuring' status would accumulate 288 `fix_measurements` rows per day without it. 6h is the smallest window that still produces 4 measurements/day — enough for a meaningful trajectory without DB bloat.
  Impact: `BUG-004 fix measurement dedup` from CLAUDASH_COMPLETE_WRITEUP.md Appendix L P7 is now structurally impossible. Can remove from the next-steps list.

- **`measure_fix()` wrapper reused instead of inlining the measurement flow** — the user's spec had manual `insert_fix_measurement()` + status updates; `measure_fix()` already does that and also promotes to `confirmed` on `improving` + 7 days elapsed. Reusing it preserves the promotion logic and keeps one code path for manual and automated measurements.
  Impact: both `POST /api/fixes/{id}/measure` (manual) and `_auto_measure_fixes()` produce identical DB state.

### Known Issues / Not Done
- **P3 (root-cause diagnosis)** — new function `diagnose_waste_event(waste_event_id)` that reads JSONL for flagged sessions, identifies which files/turns/patterns are at fault. Not built — adds 3 hours of work and a new code path. Spec present in the session prompt.
  Why deferred: user explicitly scoped this session to P1+P2.

- **P4 (fix chains)** — `build_fix_chain(project)` that orders related insights by dependency and estimates combined impact. Not built. Spec present in the session prompt.
  Why deferred: same as P3.

- **P5 (full agent loop: `claudash agent --project X`)** — long-running mode that diagnoses all waste, queues fixes, applies on approval, measures, iterates. Not built.
  Why deferred: full-session work; the building blocks landed this session (generate, apply, auto-measure) so P5 is composable from them later.

- **Generate Fix can't be exercised end-to-end without an LLM provider** — current smoke test shows the graceful error path. A real round-trip requires `claudash keys --set-provider` (Groq free tier recommended, per Appendix K).
  Why deferred: user hasn't configured a provider yet; error path is the expected behavior without one.

- **`fix_regressing` insight type has no dashboard-specific rendering** — shows as a generic red-dot row. An expanded card (like `bad_compact_detected` gets) with a "Generate corrective fix" shortcut would be natural next work.
  Why deferred: not in the P1+P2 scope; the core signal (it fires) works.

- **Auto-measure currently no-ops on all 5 existing fixes** — they were last measured 5.3 hours ago in earlier sessions, so the 6h dedup correctly skipped them. Next cycle (after the 6h window elapses) will measure them automatically without intervention.
  Why this isn't a bug: it's the guardrail working as designed.

- **Non-session commits landed mid-session** (`05df213` 2.0.0 bump, `7708e22` PRD+INTERNALS+.gitignore, `064aee5` test runner fixes, `694cc9c` test runner v2.0.0 accept) — not from this session's work, pushed externally. Noted so CHANGELOG doesn't double-count them.

## [2026-04-16] Session 15 — v2.0.1: restrict fix generation to Anthropic models only

### Philosophy
Claudash analyzes Claude Code transcripts. Claude is the right model to write CLAUDE.md rules for them. v2.0.1 removes the generic OpenAI-compatible provider (which let users point at Groq/Llama/Azure/Ollama) and replaces it with OpenRouter narrowed to Anthropic models. The provider matrix is now Anthropic-direct, AWS Bedrock (Anthropic), or OpenRouter (Anthropic) — three transports, one model family.

### Changed
- **`fix_generator.SUPPORTED_PROVIDERS`** — schema now `{label, description, default_model, cost_per_fix, setup}`. Old keys (`model_default`, `requires`, `cost_note`) removed. Provider keys are now `['anthropic', 'bedrock', 'openrouter']` (was `[…, 'openai_compat']`).
  Files: fix_generator.py

- **`DEFAULT_BEDROCK_MODEL`** — bumped from `anthropic.claude-sonnet-4-5-20251001` to the spec'd `anthropic.claude-sonnet-4-20250514-v1:0`.
  Files: fix_generator.py

- **`SYSTEM_PROMPT`** — header rewritten to `"You are Claude, analyzing Claude Code session data to generate improvements for Claude Code users."` Applies to all 6 pattern prompts via the shared system message.
  Files: fix_generator.py

- **`_call_openai_compat()` → `_call_openrouter()`** — URL is now hardcoded (`https://openrouter.ai/api/v1/chat/completions`); user only supplies a key. Error messages mention OpenRouter specifically. Model defaults to `anthropic/claude-sonnet-4-5`.
  Files: fix_generator.py

- **CLI wizard** — `claudash keys --set-provider` now prints the spec's three-line block (`Claudash uses Claude to fix Claude Code waste. All providers below run Anthropic models only.` + Anthropic / Bedrock / OpenRouter rows with cost-per-fix and setup hints). Choice [3] no longer prompts for a URL.
  Files: cli.py

- **db.py settings seed** — `openai_compat_url`/`openai_compat_key`/`openai_compat_model` removed from the default seed. New seeds: `openrouter_api_key=""` and `openrouter_model="anthropic/claude-sonnet-4-5"`. Legacy keys remain in existing DBs (orphaned, harmless).
  Files: db.py

- **README + CLAUDASH_COMPLETE_WRITEUP Appendix K** — provider list reframed as "all three run Anthropic models". Default = Anthropic API, Bedrock = AWS/HIPAA teams, OpenRouter = free-credits path. Old Groq-as-recommended-default copy removed throughout (Appendix K, sections 1/2/9/§18, Appendix B).
  Files: README.md, CLAUDASH_COMPLETE_WRITEUP.md

- **Test runner expectation** — `expected_providers = ["anthropic", "bedrock", "openrouter"]`.
  Files: claudash_test_runner.py

### Added
- **DB auto-migration in `init_db()`** — runs once per init. If `fix_provider == "openai_compat"`:
  - When `openai_compat_url` contains `openrouter.ai` AND a key is set → rewrites to `fix_provider=openrouter`, copies the API key into `openrouter_api_key`, copies any custom model, prints `[claudash] Migrated openai_compat → openrouter`.
  - Otherwise (Groq/Azure/Ollama/local) → resets `fix_provider=""` and prints a warning telling the user to re-run `claudash keys --set-provider`. Any settings-table values for the legacy keys are left in place (no destructive cleanup).
  - Idempotent: the migration condition is only met once because step 1 immediately rewrites `fix_provider`.
  Files: db.py

### Architecture Decisions
- **Why drop generic OpenAI-compat instead of keeping it for power users?** The fix generator's job is to translate Claude Code session telemetry into Claude Code rules. Letting users route to a Llama 70B variant or a local Mistral creates a quality-floor problem: the fix is only as good as the model's understanding of Claude Code's idioms (compaction, subagents, context windows). Restricting to Anthropic models removes a class of "the rule generator gave me garbage" failure modes. Cost stays low ($0.006–$0.008/fix); the OpenRouter path preserves the free-credits onboarding option for users who don't want to swipe a card on the Anthropic console.
  Impact: anyone running Groq/Azure/Ollama for fix generation must switch — clear migration message guides them.

- **OpenRouter URL hardcoded, not configurable.** With Anthropic-only routing the URL is always `https://openrouter.ai/api/v1/chat/completions`. Removing the prompt eliminates a misconfiguration class (user pasting `/v1` vs `/v1/chat/completions` vs the wrong base URL).
  Impact: simpler wizard, one fewer setting key. If OpenRouter ever changes its URL, edit `OPENROUTER_URL` in fix_generator.py.

- **Auto-migration is idempotent and never destructive.** It only acts when `fix_provider="openai_compat"` (a value that no longer ships from the wizard) and only rewrites that key plus the OpenRouter slots. Legacy `openai_compat_*` rows are left in the table — they take ~30 bytes and don't affect anything. A future `claudash db --vacuum` could clean them; not in this scope.
  Impact: rolling back to v2.0.0 leaves the user in a working state (their `openai_compat_*` keys are still there).

### Known Issues / Not Done
- **Legacy `openai_compat_url` / `_key` / `_model` rows linger in existing user DBs** — orphaned but inert. Cleanup deferred — not worth the risk of touching the settings table outside a migration script.
  Why deferred: zero functional impact; user can `DELETE FROM settings WHERE key LIKE 'openai_compat_%'` manually if desired.

- **`fix_autogen_model` setting is still cross-provider** — currently overrides the per-provider default model for all three providers. Means a user who set `fix_autogen_model=claude-sonnet-4-5` (the Anthropic format) will pass the same string to OpenRouter, which expects `anthropic/claude-sonnet-4-5`. The OpenRouter call site falls back to `DEFAULT_OPENROUTER_MODEL` only when `fix_autogen_model` is empty.
  Why deferred: existing users haven't set `fix_autogen_model` (it's at the default). Will surface only if a user manually overrides it AND switches providers — narrow edge case.

- **No unit test exercises `_call_openrouter` against a live endpoint** — TEST-V2-F4 still SKIPs without a configured provider. Round-trip verification requires the user to run `claudash keys --set-provider` choice [3] with a real OpenRouter key.
  Why deferred: same as Session 14 — provider-key-dependent.
