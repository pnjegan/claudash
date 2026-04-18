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

## [2026-04-16] Session 15 (cont.) — v2.0.2: find_claude_md fuzzy matching for renamed/versioned project dirs

### Fixed
- **`find_claude_md()` returned None for every project with a versioned, renamed, or non-`~/projects/` source dir** — broke the apply endpoint for almost all real users. The old 4-step lookup only checked `~/projects/<exact-DB-name>/CLAUDE.md`, but DB-normalized names (`Tidify`, `WikiLoop`, `CareerOps`, `Knowl`, `Brainworks`, `Claudash`) almost never match the on-disk dir verbatim — projects get version-suffixed (`Tidify15`), live under non-projects roots (`~/wikiloop`, `~/resumestiffs/career-ops`, `~/newprojects/knowl`), use kebab-case, or get renamed entirely (`Claudash` → `jk-usage-dashboard`).

  Replaced with an 8-step search that resolves all 6 known DB projects to their real CLAUDE.md:
  - Step 0: `_PROJECT_ALIASES` map for irreconcilable renames (`claudash → jk-usage-dashboard`)
  - Step 1: Legacy `~/.claude/projects/<encoded>/` walk (kept; rarely populated since those dirs hold JSONL, not CLAUDE.md)
  - Steps 2–4: Exact and lowercase `~/projects/<project>/`
  - Steps 5–6: Prefix glob `~/projects/<project>*` with descending sort (picks `Tidify15` over `Tidify12`); excludes `backup`, `node_modules`, `archive` tokens
  - Step 7: HOME walk depth 2 with **alphanumeric-normalized** substring matching (`careerops` resolves to `career-ops`)
  - Step 8: Global `~/.claude/CLAUDE.md` fallback

  Verified end-to-end: `POST /api/fixes/12/apply` (WikiLoop) returned `success:true` with `path=/root/wikiloop/.claude/CLAUDE.md` and `lines_added=11`. Backup file created.
  Files: fix_generator.py (find_claude_md, new helpers _excluded/_normalize/_check_dir, _PROJECT_ALIASES const)

- **Test runner version expectation was hardcoded** — `TEST-I-01` had `version not in ("1.0.15", "2.0.0")` which warned on every release until manually bumped (commit `694cc9c` did this for v2.0.0). Now reads `package.json` at test time so the runner stays in sync with releases automatically.
  Files: claudash_test_runner.py (test_i01_server_health)

### Architecture Decisions
- **Explicit alias map for the irreconcilable case (`Claudash → jk-usage-dashboard`).** Pure fuzzy matching can't bridge two unrelated identifiers. The alternative — adding a DB column to record the source dir at scan time — is more invasive and only pays off if multiple projects need this. Currently one entry handles it; the `_PROJECT_ALIASES` dict scales as additional renames surface.
  Impact: a maintainer adding a new alias edits one constant; no migration, no schema change.

- **Alphanumeric normalization for fuzzy matching** (`_normalize` strips everything that isn't a-z/0-9). Lets `careerops` match `career-ops`, `wiki_loop`, etc. without per-project rules. Risk: theoretical false positive if a project named `ab` exists and a directory `aab` is on disk — acceptable, the depth-2 HOME walk is bounded and excludes typical noise dirs.
  Impact: handles the kebab-case / snake_case / no-separator variants users actually create.

- **Prefix glob with `reverse=True` sort picks the latest version automatically** — `Tidify15` beats `Tidify14` beats `Tidify12` lexicographically (works as long as version suffixes stay zero-padded or single-digit). Avoids hardcoded version awareness.
  Impact: when the user spins up `Tidify16`, the fix generator follows automatically without code changes.

### Known Issues / Not Done
- **Two-digit version suffix flip risk** — `Tidify9` would sort *higher* than `Tidify10` lexicographically. Not a current user; flag for `Tidify20` era.
  Why deferred: 6+ months out, simple natural-sort fix when needed.

- **The legacy step (1) `~/.claude/projects/<encoded>/CLAUDE.md` walk is effectively dead code** — those encoded dirs hold JSONL transcripts, not CLAUDE.md. Kept per spec ("preserve existing logic") and because the cost is one cheap `os.listdir` call.
  Why deferred: removing it is a separate cleanup; not blocking the fix.

## [2026-04-17] Session 17 — Full codebase self-audit, CLAUDASH_AUDIT.md written (not committed)

### Added
- **CLAUDASH_AUDIT.md** (3,458 words, 12 sections + 2 appendices) — read-only engineering self-review produced via a structured 6-phase audit prompt. Opens with the headline proof-point ($7,981.58 API-equivalent on $100/mo Max = 79.8× ROI over 30 days), enumerates 63 features with file:line citations, splits v1 shipped (36 features) from v2 shipped (9 items: F1–F7, P1, P2) and v3 deferred (2) / out-of-scope (3), and reports two blog-blocking flags as the honest-content centerpiece.
  Files: CLAUDASH_AUDIT.md (untracked, repo root)

### Architecture Decisions
- **Audit data window: 30 days (2026-03-19 → 2026-04-17), single account (`personal_max`).** Every number in the doc is backed by an inline SQL query against `data/usage.db`, not paraphrased.
  Why: the audit doubles as a blog source — quoted numbers must survive later re-verification.
  Impact: the SQL queries are themselves artefacts the blog can reuse; DB size (14 MB, 72 sessions, 21,830 rows, 206 MB JSONL parsed) is the anchor for anyone else running Claudash.

- **Two flags elevated to headline content rather than fixed.** User decision during Phase 5.5 investigation: "blog-now-with-caveats, the two flaws are the blog's most honest content." Audit dedicates §7 to them with full diagnosis (Flag 1: floundering detector run against top Tidify session — 567 tool_use blocks, longest consecutive identical `(tool, input_hash)` run = 1; Flag 2: fixes 5/6/7/8 created in the same second, all four show identical −21.1% from the same project-level 90→71 measurement).
  Why: shipping a self-audit that names its own gaps is the story.
  Impact: Flag 1 fix (count non-consecutive repeats) queued for v2.1; Flag 2 (per-fix attribution) queued for v3 as formal Phase-4 gap #31.

### Known Issues / Not Done
- **CLAUDASH_AUDIT.md is untracked** — user decision: commit + push + publish are three separate decisions for a later session. Do not `git add` this file without explicit approval.
  Why deferred: the user wants to sleep on publication scope before the doc enters git history.

- **Flag 1 — floundering detector too strict** (`waste_patterns.py:36,120-145`). Current `FLOUNDER_THRESHOLD = 4` with consecutive matching produces 0 events on real workloads (top session has 7 repeats of `('Bash', '233564f8')` but longest consecutive run = 1). Fix: count total in-session repeats of `(tool, input_hash)` keys, mirroring `_detect_repeated_reads`.
  Why deferred: one-session's-work fix, but user decided against bundling it with the audit commit to keep the audit read-only.

- **Flag 2 / Phase-4 gap #31 — closed-loop attribution is project-scoped** (`fix_tracker.py:287-404`). `compute_delta` returns identical deltas for N concurrent fixes on the same project. Needs per-fix behavioural attribution (e.g., fix-specific waste-pattern subset tracking).
  Why deferred: structural change to the fix tracker; scheduled for v3.

- **12 untested v2 paths** (Phase-4 gaps #9–#12, #22, #23). P1 `/api/insights/{id}/generate-fix`, P2 `_auto_measure_fixes`, `/api/fixes/{id}/apply`, `find_claude_md` v2.0.2 fuzzy matching — all ship and work in production (DB evidence: 4 applied fixes, 25 measurements) but have no named test in `claudash_test_runner.py`.
  Why deferred: v2.1 maintenance batch.

- **Stale-doc drift** (Phase-4 gaps #6, #7, #8, #24): `mcp_server.py:21-27` docstring says "5 tool schemas" (code ships 10); README says "14 rules" (code emits 16 insight types); PRD says "4 write-side MCP tools" (code ships 5); PRD §11 mentions `fix_applier.py` that doesn't exist (apply logic lives in `server.py:896+`).
  Why deferred: batched doc-reconciliation pass for v2.1.

- **`MODEL_PRICING` hardcoded** (`config.py:81-84`, gap #25) — no refresh procedure. Every ROI number in the dashboard silently drifts when Anthropic updates the rate card.
  Why deferred: design decision needed (env var vs config file vs tagged-release check).

## [2026-04-17] Session 18 — v2.0.3: floundering detector rewrite + doc reconciliation + Anthropic-only test

### Fixed
- **Floundering detector — was silently returning zero events for all real workloads.** Rewrote `_detect_floundering` (`waste_patterns.py:120-145`) to count ≥4 identical `(tool, input_hash)` calls within any 50-call sliding window, instead of requiring 4 *consecutive* identical calls. Real Claude Code sessions interleave Read/Grep/Edit between retries, so the consecutive requirement almost never fired.
  Impact on the live DB: **0 → 8 events, $0 → $2,323.73 surfaced waste, 8 sessions flagged across 5 projects**. Efficiency score dropped from 65/D to 45/F as the dimension flipped from false-positive (100/100) to real signal (0/100, 11.1% flounder rate).
  Files: waste_patterns.py (FLOUNDER_WINDOW=50 added, detector rewritten)

- **Docstring and README tool/rule counts drifted from code.** `mcp_server.py` docstring said "5 tool schemas" while the TOOLS registry shipped 10; README said "14 rules" while the code emits 16 distinct insight types.
  Files: mcp_server.py (docstring rewritten with Read/Write-side grouping), README.md (headline bullet + §Insight rules table updated, bad_compact_detected row added, budget_warning/budget_exceeded split)

### Added
- **Negative-path test for Anthropic-only provider policy** (`TEST-V2-F4b`). Seeds a scratch SQLite DB with `fix_provider='openai'`, calls `fix_generator._call_provider`, and asserts it raises `ValueError("Unknown fix_provider 'openai' …")`. Verifies the v2.0.1 policy at code level — any provider not in `{anthropic, bedrock, openrouter}` is rejected cleanly.
  Files: claudash_test_runner.py (test_v2_f4b_non_anthropic_rejected + ALL_TESTS registration)

- **CLAUDASH_AUDIT.md** (433 lines) — the engineering self-review that produced this patch. Every claim cited to file:line, SQL, or git commit. Headline: $7,981.58 API-equivalent spend on $100/mo Max over 30 days = 79.8× subscription ROI.
  Files: CLAUDASH_AUDIT.md

- **FIXES_TODO.md** — living follow-up queue. v2.1 and v3 items carried from the audit.
  Files: FIXES_TODO.md

### Architecture Decisions
- **Floundering detection is now density-based, not consecutive-based.** Rule: ≥4 occurrences of same `(tool, input_hash)` key within ≤50 consecutive tool calls. Mirrors the `_detect_repeated_reads` pattern at `waste_patterns.py:147-181`. Window=50 chosen after sensitivity testing (window=20 under-fired at 2 total events / 1 Tidify; window=50 lands at 8 events / 3 Tidify, right at the user-specified sensitivity boundary).
  Why: consecutive matching never triggered in real sessions because Read/Grep/Edit calls interleave between retries. Density within a window captures the classic "stuck in retry loop" signal without flagging intentional re-runs that are spread across hundreds of turns.
  Impact: flips the efficiency-score `flounder` dimension from a false-positive 100 to a real 0–100 signal. Changes the grade from D to F on the live DB — honest reading.

### Known Issues / Not Done
- **Gap #31 — per-fix attribution remains deferred to v3.** `compute_delta` at `fix_tracker.py:287-404` still produces identical verdicts for N concurrent fixes on the same project. Blocked on structural redesign (fix-specific waste-pattern subset tracking). See FIXES_TODO.md.
- **Untested v2 closed-loop paths** — `/api/insights/{id}/generate-fix`, `/api/fixes/{id}/apply`, `_auto_measure_fixes`, `find_claude_md` fuzzy matching (audit gaps #9-#12). Deferred to v2.1 maintenance batch.
- **MODEL_PRICING refresh procedure** (audit gap #25). Hardcoded at `config.py:81-84` with no update path. Decision deferred — env var vs config file vs tagged-release check.

## [2026-04-17] Session 19 — Audit of v2.0.4, 6-fix sprint → v2.0.5, emergency WAL fix → v2.0.6

### Fixed
- **`minutes_to_limit` restored** (v2.0.5) — after Session 18's rolling-window fix, `burn_per_second` was averaged across the full 5h window, producing a stable ~892 min prediction that never tripped the `window_risk` <60-min threshold. Rewrote to sample peak burn from the last 30 minutes only. Live DB now shows `minutes_to_limit=1, burn_per_minute=511116` (honest — reflects heavy audit session).
  Files: analyzer.py (window_metrics burn calculation)

- **Daily budget TODAY card** (v2.0.5) — prior code showed static "no budget set" text. Now: over-budget (>=100%) renders red with "OVER BUDGET $X.XX limit"; within-budget renders green/amber with "within budget ($X.XX limit, N%)"; unset renders grey with clickable "configure in Accounts" link. Also added `subHtml` support to hero-cell renderer so the anchor tag renders instead of being escaped.
  Files: templates/dashboard.html (renderHero todayCell + cells.map renderer)

- **favicon 404** (v2.0.5) — browsers hit `/favicon.ico` on every page load and got 404. Added a 70-byte transparent 1x1 ICO response with 24h cache-control. Live verification requires server restart.
  Files: server.py (do_GET /favicon.ico route)

- **`.gitignore` duplicates** (v2.0.5) — `data/usage.db`, `data/usage.db-wal`, `data/usage.db-shm`, `__pycache__/`, `*.pyc` each appeared twice in the file. Deduped to one occurrence each. All other entries preserved.
  Files: .gitignore

- **`fix_generator.py` docstring drift** (v2.0.5) — claimed direct Anthropic API as primary transport. Updated to accurately reflect live config: PRIMARY/LIVE = openrouter (fix_provider in DB, model=anthropic/claude-sonnet-4-5); SECONDARY = direct Anthropic (needs ANTHROPIC_API_KEY env) and AWS Bedrock (needs boto3). Added explicit Anthropic-only policy note with TEST-V2-F4b reference.
  Files: fix_generator.py

- **SQLite "database is locked" errors under concurrent load** (v2.0.6) — scanner + claude_ai poller + API handlers + cost-event hooks can all hit the DB simultaneously. `get_conn()` already had WAL mode and 5s busy_timeout; bumped busy_timeout to 30s to match the Python-level `sqlite3.connect(timeout=30)`, and added `synchronous=NORMAL` to reduce fsync contention on writers. Verified 0 lock errors over a 60s live run after restart.
  Files: db.py (get_conn PRAGMAs)

### Added
- **Orphan MCP process cleanup on Claudash startup** (v2.0.5) — `cleanup_orphan_mcp()` called in `_run_dashboard` before `start_periodic_scan`. Uses `pgrep -f mcp_server.py` and SIGKILLs every non-self match. Active Claude Code sessions respawn their MCP child on next tool call — brief blip, no data loss. Known blunt: the implementation has no age check or active-session check, despite the docstring suggesting otherwise. Tighten in a follow-up if needed.
  Files: cli.py

### Architecture Decisions
- **Read-only audit produced 12 findings; shipped fixes for 6.** Findings 1-12 were produced by a read-only audit of v2.0.4 (no code written during the audit phase, per user instruction). Prioritised: 1 CRITICAL (window_risk inert), 3 HIGH (minutes_to_limit broken, fix_provider=openrouter misdocumented, TODAY card dead-end), 6 MEDIUM (favicon, OAuth cron, orphan MCP, gitignore dupes, NO_DASH_KEY fragility, sync-token test), 5 LOW. All 4 CRITICAL+HIGH addressed in v2.0.5 along with 2 of the 6 MEDIUM. Remaining MEDIUM/LOW logged implicitly in commit messages; no dedicated tracking doc created this session.
  Why: user asked for "brutal, no marketing" findings list with explicit prioritisation, then directed fixes in order without scope creep.
  Impact: audit-driven maintenance sprint produced 2 patch releases in one session (v2.0.5, v2.0.6) without feature regression.

- **WAL mode stays on by default; synchronous=NORMAL becomes new default.** WAL was already enabled in `get_conn` before this session — adding synchronous=NORMAL trades a very small durability window (at-most-one lost commit on power loss) for substantially fewer fsyncs per transaction. For a single-user local dashboard this tradeoff is correct. Note for posterity: if Claudash ever runs on a disk that could power-fail mid-write and the user cares about the last few seconds of data, revisit to synchronous=FULL.
  Why: lock contention during concurrent scanner + poller + hook-writer + API reads was surfacing transient OperationalError.
  Impact: all DB-writing code paths across the codebase benefit automatically; no per-caller changes needed.

### Known Issues / Not Done
- **Running dashboard process `1709234` on port 8080 is on pre-fix code** — it auto-respawned via `cmd_dashboard`'s exception handler when I killed the original, but Python doesn't reload modules on in-process restart. The new `busy_timeout=30000` and `synchronous=NORMAL` are NOT active in that process. Restart with `kill 1709234 && python3 cli.py dashboard --no-browser` to activate. New installs via `npx @jeganwrites/claudash@2.0.6` get the new code directly.
  Why deferred: no urgent failure mode; WAL (already on) + the pre-existing 5s busy_timeout was sufficient to produce 0 lock errors in the 60s sample.

- **MCP cleanup is blunt** — `cleanup_orphan_mcp()` in cli.py kills ALL non-self `mcp_server.py` processes regardless of age or active-session status. Docstring overstates safety. Tighten with age check (e.g., only kill if older than 1h AND no open stdin).
  Why deferred: user authorised the code as written; behaviour is correct-enough for single-machine use.

- **README and PRD doc drift audit gaps** #9-#12, #22 (untested v2 closed-loop paths) and #25 (MODEL_PRICING refresh procedure) from the original v2.0.0 audit remain open. No tests added this session for `/api/insights/{id}/generate-fix`, `/api/fixes/{id}/apply`, `_auto_measure_fixes`, or `find_claude_md` fuzzy matching.
  Why deferred: this session was audit→fix of v2.0.4, not backfill of prior-session gaps.

- **Medium-severity findings #9, #10 from this session's audit not fixed**: `_NO_DASH_KEY` bypass set fragility (needs framework-level guardrail), negative-path test for `/api/claude-ai/sync` token missing.
  Why deferred: 6-fix budget reached; these were deprioritised below the highest-impact items.

## [2026-04-17] Session 20 — Pre-flight audit of 7-item plan → 4 real fixes shipped as v2.0.7; 3 confirmed no-ops

### Fixed
- **README broken screenshot** (v2.0.7) — `README.md:13` pointed to `docs/screenshot.png`, which has never existed in the repo. Updated to `screenshots/Claudash_V2.0.4.png` (the PNG uploaded via GitHub web UI in Session 19 merge). Added a caption: "Claudash v2.0.6 — efficiency score, window usage, API equivalent cost, cache hit rate".
  Files: README.md

- **Ambiguous "+" nav tab** (v2.0.7) — the dashboard account-tab bar ended with `<a class="tab add-tab" href="/accounts">+</a>`. Users read the "+" as "add new account" even though /accounts handles both add AND edit flows. Replaced with `⚙ Accounts` label and `title="Manage accounts"` tooltip.
  Files: templates/dashboard.html:963

### Added
- **Cron watchdog for Claudash liveness** (not in repo — crontab only) — runs every 5 minutes, probes `/api/data?account=all`, and only restarts if both (a) the endpoint is down AND (b) `pgrep -f 'cli.py dashboard'` returns no match. Uses `cd /root/projects/jk-usage-dashboard` before launching so python3 resolves `cli.py`. The double-gate prevents cron-storm duplicate processes when the endpoint is slow but the process is alive.
  Files: user's crontab (not tracked in repo)

- **4 efficiency rules appended to Tidify's CLAUDE.md** (not in jk-usage-dashboard repo) — appended to `/root/projects/Tidify15/.claude/CLAUDE.md`: floundering-retry cap, phase-handoff read-once rule, 60 %-context early-compact rule, 1000-row file-size pre-check. Backup at `/root/projects/Tidify15/.claude/CLAUDE.md.bak-2026*` for rollback. These rules correspond to the 4 fixes that were created in DB but never applied to the actual file.
  Files: /root/projects/Tidify15/.claude/CLAUDE.md (outside this repo)

### Architecture Decisions
- **Pre-flight audit before execution saved 3 of 7 planned fixes from being built redundantly.** Before touching code, verified each proposed fix against live state. Findings: Fix 1 (`/api/data` version=None) was a 60-s stale-cache artefact — fresh requests return '2.0.6' correctly. Fix 4 (window_risk not firing) — insight IS firing (1 active in DB). Fix 5 (subagent tracking absent) — fully built: 12,443 rows, 35 sessions, $4,008.67 tracked; `subagent_metrics()` exists at `analyzer.py:576-640`; `dashboard.html:1457` has `renderSubagentBlock`; `insights.py:277-296` has `SUBAGENT_COST_SPIKE` rule with 4 active insights.
  Why: user's plan cited a prior audit's findings that had since been addressed or were misdiagnosed. Building what already exists wastes time and adds drift risk.
  Impact: session shipped 4 fixes (2 code commits, 2 system-level edits) instead of 7; no-op work was reported with verification evidence instead of being forced through.

- **Watchdog probes `/api/data?account=all` instead of `/favicon.ico`.** User's original spec specified favicon, but the favicon route was only added in v2.0.6 and the running process doesn't reload modules on auto-restart — so the favicon would 404 indefinitely and trigger restart loops until the old process was manually killed. `/api/data?account=all` is available across all deployed versions.
  Why: chose a probe endpoint that was already stable in the running process, not one that relied on new-code being live.
  Impact: watchdog activates cleanly today without requiring a manual process restart first.

### Known Issues / Not Done
- **Fix 6's "commit in jk-usage-dashboard" was infeasible** — the fix edits a file in another project (`/root/projects/Tidify15/.claude/CLAUDE.md`). No jk-usage-dashboard commit for this step; the DB-level "applied" status update for the 4 fixes (via `/api/fixes/{id}/apply` or direct DB update) was not performed. Claudash's own Fix Tracker UI will still show those 4 fixes as "measuring" / unapplied, even though the rules are now live in Tidify.
  Why deferred: spec inconsistency; would need a separate `UPDATE fixes SET status='applied', applied_to_path=...` round-trip to reconcile.

- **Running Claudash process (pid 1709234) still on pre-Fix-2/3 code.** Python module cache survives auto-restart. Fixes 2 and 3 will only go live after a real process kill + relaunch (manually or via the new cron watchdog when it fires). New `npx @jeganwrites/claudash@2.0.7` installs get the code directly.
  Why deferred: no urgent failure mode; would have severed the user's live dashboard mid-session.

- **Medium-severity findings from Session 19's audit still open**: `_NO_DASH_KEY` bypass-set fragility (server.py:650), missing negative-path test for `/api/claude-ai/sync` token, and the `MODEL_PRICING` refresh procedure (config.py:81-84) — all carried forward.
  Why deferred: this session was a bounded 7-fix plan, not a full gap-closure pass.

- **Background task leak detected at session end** — background sleep-monitor from the earlier WAL-fix verification (task ID `br83pkbyu`) was polling on a pattern that never matched a real PID and eventually failed. Harmless but should be cleaned up in the harness; real verification ran fine via foreground commands.
  Why deferred: not a code or product issue; a local-session ergonomics artefact.

## [2026-04-18] Session 21 — Claudash v3.0.0 architecture-compliance intelligence (schema-reconciled)

### Fixed
- **v3 plan column mapping reconciled against real DB** — original v3 prompt referenced `sessions.total_cost_usd`, `sessions.turns`, `waste_events.tokens_wasted`, `insights.rule_id/title/severity`, `lifecycle_events.context_pct`, and `insights.run_all_rules()` — none of which exist. Real columns: `cost_usd`, derived via `COUNT(*) GROUP BY session_id` (per-turn rows → 72 sessions not 22,546), `token_cost`, `insight_type/message/detail_json`, `context_pct_at_event`, `insights.generate_insights()`. Full mapping in the session transcript; no code changed based on wrong schema.
  Files: (planning only; snapshot at `.dev-cdc/REAL_DATA_SNAPSHOT_20260418.md`, local-only)

- **`four_tier_compaction` threshold** — v3 prompt had `context_pct > 0.80` assuming 0-1 fraction. Actual column `context_pct_at_event` is 0-100 scale; max observed value across 297 events = 66.78. Corrected backfill rule to `violated = max_pct > 50`, which yielded 4 real violator sessions (Tidify 1, Claudash 2, Brainworks 1).

### Added
- **3 new DB tables** (additive, no existing schema touched): `compliance_events` (127 rows backfilled — 74 prompt_cache passes + 4 four_tier_compaction violated + 49 passed), `skill_usage` (0 rows, awaits JSONL tool-call extraction in v3.1), `generated_hooks` (0 rows, awaits hook generator).
  Files: data/usage.db (additive schema only)

- **4 new insight rules in insights.py** — grounded in real-data snapshot; all fire on current data with zero duplication of prior rules:
  - `repeated_reads_project` (Rule 15) — fires on **3 projects / $6,790 waste surfaced** (Tidify $4,876.71, Claudash $1,596.23, WikiLoop $358.68). Was previously tracked only in `waste_events` and `mcp_warnings`; insights.py had no rule reading it.
  - `multi_compact_churn` (Rule 16) — fires on **35 churn sessions across 3 projects** (Tidify 26, Claudash 6, WikiLoop 3); worst session had 7 compacts in one sitting. Orthogonal to existing `compaction_gap` (didn't compact) and `bad_compact_detected` (single lossy compact).
  - `cost_outlier_session` (Rule 17) — fires on **4 spike sessions / $1,941.39** surfaced individually with session_id + date (Tidify 3, Claudash 1). `waste_events.pattern_type='cost_outlier'` was populated but no insight surfaced it to the user.
  - `fix_never_measured` (Rule 18) — fires on **1 fix** (#12 WikiLoop repeated_reads, applied 36h ago with 0 measurements). Closes the QA gap before `fix_regressing` can fire.
  Files: insights.py

- **`cli.py realstory --project X`** — prints verified facts only (no estimates). Session-level aggregation, session-scoped waste, compliance-score-per-pattern, fix list with latest verdict. Empty sections say "no data" instead of hiding.
  Files: cli.py

- **`GET /api/realstory?project=X&days=30`** — JSON mirror of the CLI output. Returns 400 with `{"error":"project parameter required"}` when `project` is missing. Verified live on a throwaway port-9091 server (live process untouched).
  Files: server.py

- **`.dev-cdc/REAL_DATA_SNAPSHOT_20260418.md`** (178 lines, local-only) and **`.dev-cdc/BUG_HUNT_V3_20260418.md`** (8-dimension audit, zero V3 blockers). Both gitignored per .gitignore:50.

### Dropped from original plan after real-data review
- **`subagent_chain_cost`** rule — max observed children-per-parent is 1. Rule would never fire. Existing `SUBAGENT_COST_SPIKE` (insights.py:277-299) already covers the real signal (project-wide share).
- **`prompt_cache_absent`** rule — 0 sessions across 30 days have `cache_creation_tokens=0 AND turns>10`. Rule would never fire.
- **`output_input_ratio_low`** rule — actual ratios 631-33,878% (inverted from v3 hypothesis). `model_waste` already surfaces the intended signal.
- **`single_session_spike`** rule — duplicates `waste_events.pattern_type='cost_outlier'`; replaced by `cost_outlier_session` Rule 17 which surfaces the already-populated data.
- **`memory_md` and `jit_skills` compliance patterns** — require tool-call data not stored in current schema. Deferred to v3.1 when JSONL-level extraction lands.
- **6th efficiency-score dimension `arch_compliance`** — deferred per user request; compliance_events only has 127 rows (mostly passes). TODO comment added at `analyzer.py:1172`. Revisit when 2+ weeks of real data accumulates.

### Architecture Decisions
- **Per-turn vs per-session disambiguation.** `sessions` is a per-turn table (22,546 rows across 72 distinct session_ids). Every new v3 query uses a CTE that first rolls turns up to sessions via `GROUP BY session_id`, then aggregates. The `realstory` CLI and API, and all 4 new insight rules, follow this pattern. Querying `sessions` directly without this rollup (as the v3 prompt did) would inflate session counts by ~300×.
  Why: avoided a silent-wrong-numbers bug class that would have made every v3 metric cosmetically plausible but quantitatively wrong.

- **Pre-flight schema audit saved implementing 3 dead rules.** Before writing any insight rule, I ran a COUNT query for each proposed rule's trigger against real data. Three of four originally-proposed rules (`prompt_cache_absent`, `output_input_ratio_low`, `subagent_chain_cost`) returned 0 rows. They were replaced with 4 rules (A/B/C/D) that each produce non-empty output on today's DB.
  Impact: zero shipped rules that would have been dead-on-arrival.

- **Test server on port 9091 for API verification.** Live dashboard on 8080 (pid 1815106) left untouched. Smoke-tested `/api/realstory?project=Tidify` and `?project=WikiLoop` on an ephemeral process, which was killed after verification. Session 20's "don't restart mid-session" lesson honored.

### Known Issues / Not Done
- **Live dashboard process (pid 1815106) still serving pre-v3 code.** New `/api/realstory` endpoint and new insight rules won't be reachable from the live UI until a process restart. Follow-up: kill + relaunch at a low-usage window, or let the cron watchdog from Session 20 catch the next natural restart.
  Why deferred: Session 20's carried-forward guidance — don't sever the live dashboard mid-session.

- **Compliance backfill coverage incomplete** — only `prompt_cache` and `four_tier_compaction` patterns backfilled. `memory_md` and `jit_skills` patterns require tool-call data from raw JSONL, not stored in current schema. Needs v3.1 scanner extension to extract tool invocations.

- **`skill_usage` and `generated_hooks` tables are empty.** Tables exist; no code writes to them yet. Awaiting JSONL tool-call extraction (skill_usage) and the hook generator (generated_hooks).

- **`compliance_events` shows `status='passed'` for 121 of 127 rows.** Useful baseline, but surfaces as "everything's fine" until more violators accumulate. Dashboard UI should probably default-hide passes.

- **Medium-severity findings from Session 19/20 audit still open**: `_NO_DASH_KEY` bypass-set fragility (server.py:650), missing negative-path test for `/api/claude-ai/sync` token, and the `MODEL_PRICING` refresh procedure (config.py:81-84) — carried forward to v3.1.

## [2026-04-18] Session 21 (cont.) — v3.0.1 row_factory fix

### Fixed
- **`insights.generate_insights(conn)` crashed on raw sqlite3 connection** — Latent pre-v3 bug: callers who passed a `sqlite3.connect()` result directly (without `row_factory = sqlite3.Row`) hit `TypeError: tuple indices must be integers or slices, not str` inside `get_accounts_config()` and downstream helpers. In-repo callers use `get_conn()` (which sets row_factory), so this never surfaced in production. External scripts — including the v3.0.0 audit script — tripped it.
  Two-line fix: at function entry, check `conn.row_factory` and upgrade to `sqlite3.Row` if `None`. Also added `import sqlite3` for the type reference.
  Files: insights.py

## [2026-04-18] Session 21 (cont.) — v3.1.0 Sub-agent Work Classification

### Added
- **8 tool classification columns on `sessions`** — `tool_call_count`, `bash_count`, `read_count`, `write_count`, `grep_count`, `mcp_count`, `max_output_tokens`, `work_classification`. Added via the existing `_column_exists()` / `ALTER TABLE` migration loop at `db.py:108-114`; additive only, zero impact on existing rows. Session-aggregate semantics — same value repeated on every per-turn row; downstream collapses with `MAX() GROUP BY session_id`.
  Files: db.py

- **`scanner.classify_session_tools()` + `update_session_tool_classification()`** — extends `scan_lifecycle_events()` to count `tool_use` blocks per session. Reuses the existing `_iter_assistant_tool_uses()` helper (which was previously used only for `SUBAGENT_SPAWN` lifecycle events). Name mapping: `Bash` → bash_count; `Read`/`cat`/`LS` → read_count; `Write`/`Edit`/`MultiEdit`/`NotebookEdit` → write_count; `Grep` → grep_count; `mcp__*` → mcp_count. `max(output_tokens)` across assistant turns → `max_output_tokens`.
  Backfill: ran against 235 tracked JSONL files. 35/35 sub-agent sessions now have tool data populated. Top sub-agent: `ad536966-83a` (Tidify, 454 tools: 62 bash, 181 read, 69 write, 137 grep).
  Files: scanner.py

- **`analyzer.classify_subagent_work(s)`** — per-session verdict from the 8 tool counts. Additive score: `write>0` (+2), `mcp>2` (+1), `max_output_tokens≥2000` (+1), `tool_call_count≥40` (+1), `bash>15 AND write>0` (+1). Map: score 0 = mechanical; score ≥ 2 = reasoning; else mixed.
  Files: analyzer.py

- **`analyzer.subagent_intelligence(conn, account)`** — per-project rollup. Query uses CTE with `GROUP BY session_id` to collapse per-turn rows to sessions before classifying. Returns each project's mechanical/reasoning/mixed counts and costs, `haiku_savings_estimate = mechanical_cost × 0.95`, top 5 sessions by cost, and verdict:
    - `optimize_possible` → `mechanical_cost / total > 30%`
    - `review_mechanical` → mechanical work exists but < 30% share
    - `justified` → no mechanical work
  Real verdicts on today's DB: Tidify `review_mechanical` ($547.81 mech / 20.9%), Claudash `review_mechanical` ($1.52 / 0.5%), Brainworks `justified`.
  Files: analyzer.py

- **`/api/data` response includes `subagent_intelligence`** — `full_analysis()` now attaches the intel dict alongside existing `subagent_metrics`. Response time 3.28s (warm cache) vs 4.24s baseline — classifier query benefits from `idx_sessions_project`, no cache layer needed.
  Files: analyzer.py

- **Dashboard "Work Classification" block** — `renderSubagentIntelBlock()` added to `templates/dashboard.html`. Renders below existing "Sub-agents" section, reuses existing `kvs`/`kv`/border-top-dashed CSS (no new stylesheet). Shows mechanical/reasoning/mixed counts + costs, colored verdict line, and — if `optimize_possible` — the `CLAUDE_CODE_SUBAGENT_MODEL=claude-haiku-4-5` snippet with savings estimate. Top 5 sub-agent sessions mini-list. Served from disk on each request; no restart required for this change.
  Files: templates/dashboard.html

- **Insight rule 19 — `subagent_model_waste`** — appended after rule 18 in `insights.py::generate_insights()`. Fires when a project's verdict is `optimize_possible` AND `mechanical_cost > $10`; 12h per-project debounce. Actionable message: `"{project}: ${mech_cost} in mechanical sub-agent work Haiku could handle. Set CLAUDE_CODE_SUBAGENT_MODEL=claude-haiku-4-5 to save ~${savings}."` Currently silent — no project crosses the 30% threshold (Tidify closest at 20.9%). Latent, not dead: realistic path to firing as workload shifts.
  Files: insights.py

- **Tests SA-001 through SA-005** — new `v3.1` section in `claudash_test_runner.py`. Covers mechanical/reasoning/mixed classification (SA-001–003), `subagent_intelligence` structure + valid verdict values (SA-004), and all 8 tool columns present in the schema (SA-005). Full suite: 26/28 passed, 0 FAIL, 1 WARN (git status — uncommitted, expected during this work), 1 SKIP (fix generator needs API key, pre-existing). Zero regressions.
  Files: claudash_test_runner.py

### Fixed
- **Duplicate-dashboard-process gap (from Session 20)** — `_acquire_pid_lock()` in `cli.py` acquires `fcntl.flock(LOCK_EX|LOCK_NB)` on `/tmp/claudash.pid` at the top of `cmd_dashboard()`. A second `cli.py dashboard` invocation now exits 1 with `"Claudash already running (pid N). Kill it first or rm /tmp/claudash.pid"`. `atexit` cleans the pidfile on clean shutdown. Stale pidfiles from crashed processes are reclaimable (flock is per-file-description, not per-inode).
  Key implementation detail: pidfile opened in `"a+"` mode (not `"w"`), so the content survives a failed lock acquire — the losing process reads the winner's pid to report it. Earlier draft used `"w"` and the error message showed an empty pid.
  Files: cli.py

### Architecture Decisions
- **Per-turn vs per-session disambiguation, redux.** Every v3.1 query follows the CTE-first pattern: `WITH s AS (SELECT session_id, SUM(cost_usd), MAX(tool_call_count) ... GROUP BY session_id)` before aggregating. Rejected alternative: a `session_aggregates` side-table. Per-turn storage + MAX() collapse keeps the read path index-friendly (`idx_sessions_project`) and avoids a cross-table write barrier.

- **Dropped 3 of 4 originally-proposed insight rules during planning.** Pre-flight count queries showed `subagent_chain_cost` (fan-out per parent never exceeds 1), `prompt_cache_absent` (zero sessions qualify), and `output_input_ratio_low` (inverted by cache_read volume) would fire on zero rows. Replaced upstream (v3.0.0) with 4 rules that each fire on ≥1 row of real data today. Rule 19 (`subagent_model_waste`) here follows the same rule: ships silent rather than firing on manufactured signal.

- **Version numbering reconciled.** Git commits through Session 21 referenced v3.0.0/v3.0.1/v3.1.0 but `package.json` was 2.0.7 the whole time. Ran `npm version 3.1.0` explicitly (not `npm version minor`, which per semver would have produced 2.1.0) to make the public artifact match the history. The 3.0.0 and 3.0.1 tags were never pushed, so nobody external sees a version gap.

### Known Issues / Not Done
- **Rule 19 is latent** — silent until a project's sub-agent mechanical share crosses 30%. Tidify is at 20.9%. Not manufactured signal; waiting for real movement.

- **`compliance --score` CLI command** — planned in v3 spec, deferred. Only `realstory` shipped as the CLI anchor.

- **`arch_compliance` 6th efficiency-score dimension** — TODO comment at `analyzer.py:1172` only. Revisit when `compliance_events` has 2+ weeks of data (127 rows today, mostly passes — thin signal).

- **`skill_usage` and `generated_hooks` tables empty** — schema exists; no writers. Needs v3.2 JSONL tool-call extraction (skill_usage) and a hook generator (generated_hooks).

- **Cron watchdog still has a pre-bind race** — the pidfile lock is the second defensive layer; the watchdog's `pgrep`/endpoint probe logic itself could be tightened (detects "no process" before the port bind completes). Fine as-is for now.

- **Medium-severity findings carried from Session 19/20**: `_NO_DASH_KEY` bypass fragility (server.py:650), missing negative-path test for `/api/claude-ai/sync` token, `MODEL_PRICING` refresh procedure (config.py:81-84). Still open.
