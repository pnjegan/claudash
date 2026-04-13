# Claudash — Changelog

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
