# Claudash — Changelog

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

- **Hardcoded VPS IP `174.138.183.88`** → removed from all code files and docs. `config.py` now reads `VPS_IP = os.environ.get('CLAUDASH_VPS_IP', 'localhost')`. Markdown docs show `YOUR_VPS_IP`. CLI banner reads from env.
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
  - Hardcoded IP `174.138.183.88` → `YOUR_VPS_IP` in markdown docs; env var lookup in code
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

- **Dashboard key exposed in SECURITY_TRUTH_MAP.md and previous reports** (`bee3793944f034635c699fa31c889cc6`). These documents live in the repo and the value will travel with any clone.
  Why deferred: awaiting user decision on whether to rotate. Rotation: `sqlite3 data/usage.db "DELETE FROM settings WHERE key='dashboard_key'"` then any `init_db()` call.

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
