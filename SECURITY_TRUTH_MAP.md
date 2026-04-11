# Security & Code Truth Map
Generated: 2026-04-11 — fresh read, no prior assumptions

Every verdict below is backed by a file:line reference, a grep result, or a live SQL/HTTP query against the running system.

---

## File inventory

| File | LOC | What it actually does | External calls |
|---|---|---|---|
| `config.py` | 63 | Plain-Python constants: `VPS_IP`, `VPS_PORT`, `ACCOUNTS`, `PROJECT_MAP`, `MODEL_PRICING`, `MAX_WINDOW_HOURS`, `CLAUDE_AI_ACCOUNTS`, `COST_TARGETS` | None |
| `db.py` | 816 | SQLite schema/migration/CRUD. Defines `get_conn()` (WAL, busy_timeout=5000), `init_db()` (creates 12 tables, seeds `sync_token` + `dashboard_key`), account/project/session/insights/snapshot CRUD helpers, settings kv store | `sqlite3` |
| `scanner.py` | 309 | Walks `data_paths` → parses JSONL → `insert_session`. Incremental via `scan_state` (byte offset). Has `normalize_model`, `compute_cost`, `_detect_compaction` (30% input-token drop heuristic), `resolve_project` (keyword match). Runs `start_periodic_scan` thread every 300s | `os.walk`, `open` |
| `analyzer.py` | 605 | Pure Python over SQLite rows: `account_metrics`, `project_metrics`, `window_metrics`, `compaction_metrics`, `model_rightsizing`, `trend_metrics`, `full_analysis`, `generate_alerts`, `record_window_burn` | None |
| `insights.py` | 279 | 11 insight rules: model_waste, cache_spike, compaction_gap, cost_target, window_risk, roi_milestone, heavy_day, best_window, window_combined_risk, session_expiry, pro_messages_low. Dedup via `_insight_exists_recent` (created_at < cutoff, default 12h). Stale cleanup `_clear_stale_insights` (default 24h) | None |
| `claude_ai_tracker.py` | 358 | Polls `claude.ai/api/account` and `/api/organizations/{id}/usage` via `urllib` with `sessionKey` cookie. `poll_single`, `poll_all`, `setup_account`, `start_periodic_poll` thread. Module-level `_last_poll_time` + `_account_statuses` dict | `urllib.request.urlopen` → `claude.ai` |
| `server.py` | 550 | `http.server.BaseHTTPRequestHandler` subclass. 30 routes across GET/POST/PUT/DELETE. Helpers: `_read_body`, `_require_dashboard_key`, `_serve_template`, `_serve_json`, `_serve_mac_sync`, `_handle_sync`. Binds `127.0.0.1:8080` (line 544) | None (just dispatches to db/analyzer/scanner/insights/claude_ai_tracker) |
| `cli.py` | 337 | 7 subcommands: `dashboard`, `scan`, `stats`, `insights`, `window`, `export`, `claude-ai` (with `--sync-token` and `--setup` flags). `--help`/`-h`/`help` prints usage. Imports split around `HELP_TEXT` (ugly but valid) | None |
| `tools/mac-sync.py` | 374 | macOS-only collector: reads Chrome/Vivaldi Cookies SQLite DB, decrypts via `security find-generic-password` + `openssl enc -aes-128-cbc`, POSTs to `/api/claude-ai/sync` with `X-Sync-Token` | `subprocess`, `urllib.request.urlopen` → `claude.ai` and VPS |
| `templates/dashboard.html` | 704 | Vanilla JS dashboard. Makes 4 fetch calls: `GET /api/data`, `GET /api/insights`, `POST /api/scan`, `POST /api/insights/{id}/dismiss` | In-browser `fetch` to same origin |
| `templates/accounts.html` | 713 | Vanilla JS account admin UI. 14 fetch calls, most are POST/PUT/DELETE to `/api/accounts*` and `/api/claude-ai/accounts*` | In-browser `fetch` to same origin |

---

## Security claims: verified vs actual

### CLAIM 1: "Server binds to 127.0.0.1"
**Verdict: CONFIRMED**
Evidence: `server.py:544` — `server = HTTPServer(("127.0.0.1", port), DashboardHandler)`. Grep for `0\.0\.0\.0` in source returns nothing except prior review docs. Live: `ss -tlnp | grep 8080` (confirmed in the fix session) showed `LISTEN 127.0.0.1:8080`. External IP refuses connection.

### CLAIM 2: "Session key never logged"
**Verdict: CONFIRMED — with a caveat about on-disk storage**
Evidence: grep for `session_key|sessionKey` across all `.py` files. Every hit is either (a) a DB column or SQL parameter, (b) an HTTP Cookie header construction, (c) a function parameter name, or (d) an explicit scrub (`a.pop("session_key", None)` at `server.py:162` and `server.py:273`, with inline comments "Never expose session_key"). No `print(... session_key ...)` or equivalent f-string logging anywhere. `claude_ai_tracker.py:51` even has a docstring `NEVER logs session_key`.
**Caveat**: `session_key` is stored **plaintext** in `claude_ai_accounts.session_key` TEXT column (`db.py:182`). The DB file is world-readable (`-rw-r--r--` / `0644`, verified via `stat`). Any non-root OS user on the box can `sqlite3 data/usage.db "SELECT session_key FROM claude_ai_accounts"`. Session keys are not logged, but they are persisted insecurely.

### CLAIM 3: "Sync token not served in mac-sync.py download"
**Verdict: CONFIRMED**
Evidence: `server.py:409-425` (`_serve_mac_sync`) — opens `tools/mac-sync.py` in binary mode and writes it verbatim. There is no `content.replace('SYNC_TOKEN = ""', ...)` anywhere — the old string-injection code has been removed. Grep for `SYNC_TOKEN` in `server.py` returns zero hits. Grep in `tools/mac-sync.py` shows `SYNC_TOKEN = ""` (line 34, empty string). Live `curl http://localhost:8080/tools/mac-sync.py | grep SYNC_TOKEN` returns `SYNC_TOKEN = ""`.

### CLAIM 4: "POST endpoints require X-Dashboard-Key"
**Verdict: CONFIRMED (for the server) — but see CLAIM 7**

Full map of `do_POST` routes in `server.py` and their auth state:

| Route | Line | Auth |
|---|---|---|
| `POST /api/scan` | 196 | ✅ gated by `_require_dashboard_key` at line 191 |
| `POST /api/insights/{id}/dismiss` | 203 | ✅ same gate |
| `POST /api/claude-ai/poll` | 211 | ✅ same gate |
| `POST /api/accounts` | 216 | ✅ same gate |
| `POST /api/accounts/{id}/projects` | 226 | ✅ same gate |
| `POST /api/accounts/{id}/scan` | 238 | ✅ same gate |
| `POST /api/accounts/discover` | 247 | ✅ same gate |
| `POST /api/claude-ai/accounts/{id}/setup` | 252 | ✅ same gate |
| `POST /api/claude-ai/accounts/{id}/refresh` | 264 | ✅ same gate |
| `POST /api/claude-ai/sync` | 280 | ⚠️ gate intentionally skipped (`path != "/api/claude-ai/sync"` at line 191), uses X-Sync-Token instead at line 430 |

The single auth skip is deliberate and correct — mac-sync.py doesn't have the dashboard key.

Live: `curl -X POST http://localhost:8080/api/scan` returns `HTTP 401 {"error":"unauthorized"}`; with correct `X-Dashboard-Key` returns `{"status":"ok", ...}`.

### CLAIM 5: "Request body capped at 100KB"
**Verdict: CONFIRMED — cap applied BEFORE rfile.read**
Evidence:
- `server.py:185` — in `do_POST`, the Content-Length check and 413 response are the first thing after path parsing, executed **before** `_read_body()` at line 194.
- `server.py:290` — same in `do_PUT`.
- `do_DELETE` has no body, no check — correct.
- Live: sending a 125 KB POST returns `HTTP 413 {"error":"request too large"}`.

Edge case: if the client sends `Content-Length: 0` (or no header) and then pushes a body, `_read_body` reads 0 bytes — safe. If the client lies (says 50 KB, sends 500 KB), `rfile.read(50000)` still reads only 50 KB — safe. Chunked transfer encoding is not handled by `http.server`'s default BaseHTTPRequestHandler — Python stdlib treats `Content-Length` as authoritative.

### CLAIM 6: "Path traversal fixed in _serve_template"
**Verdict: CONFIRMED**
Evidence: `server.py:388-399`. `_serve_template` calls `filename = os.path.basename(filename)` before `os.path.join(TEMPLATE_DIR, filename)`. `basename` strips any `../` sequences. Additionally, the only callers pass hardcoded strings (`"dashboard.html"`, `"accounts.html"`) so the attack surface was empty even without the guard. `_serve_mac_sync` also uses a hardcoded path at line 414 — no user input flows into the path. No constructable attack reaches outside `templates/` or `tools/`.

### CLAIM 7: "dashboard.html and accounts.html send X-Dashboard-Key"
**Verdict: FALSE — this is the single most important active bug**

Grep against both templates for `X-Dashboard|dashboard.key|Dashboard.Key` returns **zero hits**. Every `fetch` call in the UI is either missing a `headers` object or includes only `{'Content-Type':'application/json'}`. Concretely:

| Template | Line | Call | Sends X-Dashboard-Key? |
|---|---|---|---|
| dashboard.html | 246 | `fetch('/api/scan', {method:'POST'})` | ❌ No headers at all |
| dashboard.html | 547 | `fetch('/api/insights/' + id + '/dismiss', {method:'POST'})` | ❌ No headers |
| accounts.html | 348,356,388,427 | `POST /api/accounts/discover` | ❌ Only `Content-Type` |
| accounts.html | 480 | `POST`/`PUT /api/accounts` | ❌ Only `Content-Type` |
| accounts.html | 509 | `POST /api/accounts/{id}/projects` | ❌ Only `Content-Type` |
| accounts.html | 515 | `DELETE /api/accounts/{id}/projects/{name}` | ❌ No headers |
| accounts.html | 531 | `POST /api/accounts/{id}/scan` | ❌ No headers |
| accounts.html | 551 | `DELETE /api/accounts/{id}` | ❌ No headers |
| accounts.html | 650 | `POST /api/claude-ai/accounts/{id}/setup` | ❌ Only `Content-Type` |
| accounts.html | 673 | `POST /api/claude-ai/accounts/{id}/refresh` | ❌ No headers |
| accounts.html | 685 | `DELETE /api/claude-ai/accounts/{id}/session` | ❌ No headers |

**Impact**: The dashboard UI (`dashboard.html`) is still usable as a read-only view because `GET /api/data` doesn't require auth. But the "Scan now" button, the "Dismiss insight" button, and **every** button in the `/accounts` admin UI will silently 401. The UI currently has no way to discover/enter the dashboard key.

This was flagged at the end of the previous fix session and never wired up. **It is the #1 fix remaining.**

### CLAIM 8: "sync_token auto-generated in db.py"
**Verdict: CONFIRMED (and same for dashboard_key)**
Evidence:
- `db.py:231-236` — after `CREATE TABLE IF NOT EXISTS settings`, check for `sync_token` row; if missing, `secrets.token_hex(32)` → insert.
- `db.py:238-243` — same pattern for `dashboard_key` with `secrets.token_hex(16)` (32 hex chars).
- `init_db()` is called by every `cli.py` subcommand that touches the DB, so first-run seeding is reliable.
- If the `settings` table exists but the specific key is missing (e.g., on upgrade from a pre-dashboard_key deployment), the `if not row` guard correctly re-seeds it.

Live check:
```
SELECT key, length(value) FROM settings;
  sync_token              64
  account_migration_done  1
  dashboard_key           32
```

Both keys exist. 32 hex chars = 16 random bytes = 128 bits of entropy for dashboard_key. 64 hex chars = 32 random bytes = 256 bits for sync_token. Adequate.

### CLAIM 9: "DELETE endpoints require auth"
**Verdict: CONFIRMED**
Evidence: `server.py:316-355`. `do_DELETE` calls `_require_dashboard_key()` at line 320 before any route dispatch. Routes gated:
- `DELETE /api/accounts/{id}` (line 323)
- `DELETE /api/accounts/{id}/projects/{name}` (line 334)
- `DELETE /api/claude-ai/accounts/{id}/session` (line 346)

Live: `curl -X DELETE http://localhost:8080/api/accounts/personal_max` returns `HTTP 401 {"error":"unauthorized"}`.

### CLAIM 10: "No eval/exec anywhere"
**Verdict: CONFIRMED — with expected subprocess use in mac-sync.py**
Evidence: grep for `eval\(|exec\(|os\.system\(|subprocess\.call|subprocess\.Popen|subprocess\.check_output|shell=True` across all Python files returns:
- `tools/mac-sync.py:166` — `subprocess.check_output(["security", "find-generic-password", "-w", "-s", ...])` — fixed-list argv, no shell. Reads macOS keychain.
- `tools/mac-sync.py:182` — `subprocess.check_output(["openssl", "enc", "-d", "-aes-128-cbc", "-K", key.hex(), "-iv", iv.hex(), "-in", tmp, "-nosalt"])` — fixed-list argv, no shell. `tmp` is `tempfile.NamedTemporaryFile` output, not user-controlled.

No `eval`, no `exec`, no `shell=True`, no `os.system`. Not exploitable.

---

## Logic bugs: verified vs actual

### VERIFY 1: Model name normalization
**Verdict: PASS with a minor latent bug**
Evidence: `scanner.py:18-26`.
- `"claude-opus-4-6"` → contains "opus" → returns `"claude-opus"` ✓
- `"claude-sonnet-4-5"` → no opus, no haiku → falls to `"claude-sonnet"` ✓
- `"claude-haiku-4-5-20251001"` → contains "haiku" → returns `"claude-haiku"` ✓
- Empty string / `None` → returns `"claude-sonnet"` (documented default)
- **Latent bug**: `"gemini-pro"` also returns `"claude-sonnet"` — no warning, no fall-through marker. If Anthropic ever ships a model whose name contains neither "opus" nor "haiku" and isn't a Sonnet, its usage will be silently priced at Sonnet rates. Low severity today, but it's a silent misbehavior.

### VERIFY 2: Pricing math
**Verdict: PASS**
Evidence: `config.py:45-49` (MODEL_PRICING dict: opus $15/$75, sonnet $3/$15, haiku $0.25/$1.25, cache_read and cache_write columns included). `scanner.py:40-47` (`compute_cost`):
```python
cost += (input_tokens / 1_000_000) * pricing["input"]
cost += (output_tokens / 1_000_000) * pricing["output"]
cost += (cache_read / 1_000_000) * pricing["cache_read"]
cost += (cache_create / 1_000_000) * pricing["cache_write"]
```
Formula is standard per-million-token billing. Division by `1_000_000` (not 1024*1024). Rounds to 8 decimals. Correct.

### VERIFY 3: Cache hit rate formula
**Verdict: FAIL — conceptually wrong, numerically close**
Evidence: `analyzer.py:58-61`:
```python
total_cache_read = sum(r["cache_read_tokens"] for r in rows_30d)
total_input = sum(r["input_tokens"] for r in rows_30d)
total_input_plus_cache = total_input + total_cache_read
cache_hit_rate = (total_cache_read / total_input_plus_cache * 100) if total_input_plus_cache > 0 else 0
```

The denominator is `input + cache_read` — not `cache_read + cache_creation`. A traditional cache hit rate is `hits / (hits + misses)` where a miss is a cache *write*. The code's denominator treats fresh `input_tokens` as "misses", which is only approximately right for Anthropic's billing model (where a cache-write costs more than a fresh input read and is emitted into a separate column).

Live SQL on the 20,303-row dataset:

| Formula | Value |
|---|---|
| Code's (reads / (reads + input)) | **99.96%** |
| True hits/(hits+writes) (reads / (reads + cache_creation)) | **96.1%** |

The UI and CLI currently report ~100% cache hit rate. The actual cache hit rate is 96.1%. Still very high, but the headline number is inflated because the formula doesn't count cache writes as misses. A cache that makes 100 fresh requests (all cache writes) and 100 cache reads should be 50%, not 100%.

**This is a legitimate bug worth fixing.** The "100% cache hit rate" claim in `END_USER_REVIEW.md` and `REPORT.md` is wrong.

### VERIFY 4: ROI calculation
**Verdict: PASS**
Evidence: `analyzer.py:69-78`. Per-account: `total_cost_30d / monthly_cost_usd`, gated by `if monthly_cost > 0`. All-accounts: divides by sum of plan costs, gated by `if total_plan > 0`. Division-by-zero is correctly guarded — a $0 plan stays at 0x ROI rather than raising. `work_pro` with `monthly_cost_usd=20` and 0 sessions gives `0.0 / 20 = 0.0` which is correct.
Live: `SELECT SUM(cost_usd)/100.0 FROM sessions WHERE account='personal_max' AND timestamp > now-30d` → **60.3x**. The earlier audit claimed 57.7x; trajectory is correct, number drifted upward as more data accumulated.

### VERIFY 5: 5-hour window calculation
**Verdict: PARTIAL — code is correct by its own definition, but does NOT match Anthropic's actual windowing**
Evidence: `analyzer.py:123-156`.
```python
window_seconds = MAX_WINDOW_HOURS * 3600  # 18000
last_ts = row["last_ts"] if row and row["last_ts"] else now
window_start = last_ts - (last_ts % window_seconds)
if window_start + window_seconds < now:
    window_start = now - (now % window_seconds)
window_end = window_start + window_seconds
```
This snaps `window_start` to the nearest multiple of 18000 seconds since epoch. In UTC that means windows at 00:00, 05:00, 10:00, 15:00, 20:00. Live verification: `strftime('%s','now') % 18000 = 13420` → we are 13,420 seconds (~3h 43m) into the current epoch window, which ends at 15:00 UTC.

**Anthropic's actual 5-hour windows are NOT epoch-aligned.** They roll from the user's first request in a given period, reset to that rolling window, and are tied to Anthropic's internal clock. The code's windowing will diverge from Anthropic's reported "window used %" for any user whose first request is not exactly on a 5-hour-since-epoch mark.

This is a **known-limitation bug** already called out in the prior `REPORT.md` ("Window calculations use epoch-modulo, not Anthropic's actual window boundaries"). Not fixed. Impact is that the dashboard's `window_pct` can be wildly off from `claude.ai`'s reported number.

### VERIFY 6: Compaction detection
**Verdict: FAIL — the heuristic cannot fire on this dataset**

Evidence: `scanner.py:65-72`:
```python
def _detect_compaction(session_rows):
    events = []
    for i in range(1, len(session_rows)):
        prev_input = session_rows[i - 1].get("input_tokens", 0)
        curr_input = session_rows[i].get("input_tokens", 0)
        if prev_input > 0 and curr_input < prev_input * 0.7:
            events.append((i, prev_input, curr_input))
    return events
```

The heuristic is: consecutive turns in the same session, a >30% drop in **`input_tokens`** from turn N-1 to turn N counts as a compaction event.

Live SQL truth:
```
avg_input:       50.02
avg_cache_read:  137,493.04
avg_output:      241.54
min_input:       0
max_input:       13,088
rows_with_meaningful_input (>100): 596 out of 20,303 (2.9%)
SELECT COUNT(*) FROM sessions WHERE compaction_detected=1:  0
```

**Across 20,303 sessions the compaction detector has fired exactly 0 times.** The reason: Claude Code's prompt caching means `input_tokens` is effectively zero (average 50 tokens) while the entire prompt history sits in `cache_read_tokens` (average 137,493 tokens per row). The heuristic is looking at the wrong column. It should be computing the drop on `input_tokens + cache_read_tokens` (total inbound context) rather than `input_tokens` alone.

The downstream insight rule `compaction_gap` (`insights.py:106-116`) depends on `compaction_metrics()` producing non-zero counts, which depends on `_detect_compaction` firing. Neither can fire on real Claude Code data. **The entire compaction-detection feature is dead code in practice.** The `sessions_needing_compact` counter will always be 0, so the `COMPACTION_GAP` insight will never trigger.

This is a **silent correctness failure** — the feature is shipped, documented in the README and insights table, displayed in the dashboard, but doesn't actually work.

### VERIFY 7: Insight deduplication
**Verdict: PASS**
Evidence: `insights.py:42-48` (`_insight_exists_recent`) runs a `SELECT COUNT(*)` over `insights` filtered by `insight_type = ? AND project = ? AND created_at > cutoff AND dismissed = 0`. Default window is 12h, with 168h (7d) for ROI milestones / best windows / heavy days. Dedup is query-based, not schema-enforced — the `insights` table has no UNIQUE constraint on (insight_type, project). If the dedup query is ever bypassed (or the code path changes), nothing stops duplicates. Acceptable for this scale.

### VERIFY 8: Account tagging
**Verdict: PASS — with one latent bug**
Evidence: `scanner.py:29-37`:
```python
def resolve_project(folder_path, project_map=None):
    if project_map is None:
        project_map = get_project_map_config()
    path_lower = folder_path.lower()
    for project_name, info in project_map.items():
        for kw in info["keywords"]:
            if kw in path_lower:
                return project_name, info["account"]
    return UNKNOWN_PROJECT, "personal_max"
```

Walkthrough:
1. `folder_path` comes from `os.walk(data_path)`'s `root` argument (`scanner.py:241`) — the directory containing the JSONL file, not the file itself.
2. Lowercased as `path_lower`.
3. Each project's keyword list is scanned; first `kw in path_lower` substring match wins.
4. No match → `("Other", "personal_max")`.
5. Iteration order: Python 3.7+ dicts preserve insertion order, which for `get_project_map_config()` is the SQL row order from `SELECT * FROM account_projects` (no ORDER BY → effectively insert order). First match wins; collisions between projects sharing a keyword would be resolved by insertion order.

**Latent bug**: the no-match fallback hardcodes `"personal_max"` as the account_id. If a user ever deletes the `personal_max` account, unmatched folders will produce rows with a dangling foreign-ish key. Minor; no current damage.

Live: `SELECT DISTINCT account FROM sessions` → only `personal_max`. Every matched project and the `Other` fallback all resolve to `personal_max`. The tagging is working as intended.

---

## False narratives found

### NARRATIVE 1: "100% cache hit rate"
**Verdict: MISLEADING**
Evidence (live SQL over all sessions):
```
SUM(cache_read_tokens)      = 2,791,521,107
SUM(cache_creation_tokens)  =   113,336,189
SUM(input_tokens)           =     1,015,504
code formula (reads/(reads+input))    = 99.96 %
true formula (reads/(reads+writes))   = 96.10 %
```
Code and UI report **99.96% ≈ 100%**. True cache hit rate is **96.1%**. The 100% claim in `REPORT.md` and `END_USER_REVIEW.md` is an artifact of the formula choice, not a fact about the cache. Still a very high hit rate, but the headline is wrong by ~4 percentage points and the denominator is wrong in principle.

### NARRATIVE 2: "57.7x ROI"
**Verdict: TRUE at the time, currently 60.3x**
Evidence (live SQL):
```
SELECT ROUND(SUM(cost_usd), 2), ROUND(SUM(cost_usd)/100.0, 2)
FROM sessions
WHERE account='personal_max'
  AND timestamp > strftime('%s','now') - 2592000;
→ total_30d = 6030.42, roi = 60.3
```
The earlier `57.7x` in `REPORT.md` reflected the state at Session 1. Since then more sessions were ingested, pushing the 30-day rolling total up. Trajectory is correct, the number drifts naturally.

### NARRATIVE 3: "19,893 records"
**Verdict: STALE**
Evidence: `SELECT COUNT(*) FROM sessions → 20,303`. `END_USER_REVIEW.md` says 20,130 (also stale). The number grows with each scan; this is expected and neither figure was wrong when it was written. Not a bug — just a naturally moving target.

### NARRATIVE 4: "Compaction events = 0"
**Verdict: TRUE — but this is a BUG, not a feature**
Evidence: `SELECT COUNT(*) FROM sessions WHERE compaction_detected=1 → 0`. The reason is VERIFY 6: the detector watches `input_tokens` which averages 50, while the real prompt history lives in `cache_read_tokens` (avg 137K). The feature is shipped but functionally dead. `REPORT.md` and `FOUNDING_DOC.md` both describe compaction detection as a working differentiator; in reality it has never fired on a single row in the entire 20K-row dataset.

### NARRATIVE 5: "Work (Pro) has 0 sessions"
**Verdict: TRUE**
Evidence: `SELECT account, COUNT(*) FROM sessions GROUP BY account → personal_max 20303`. `work_pro` has 0 rows. The account tagging post-Session-1 is consistent.

### NARRATIVE 6: "All projects under personal_max"
**Verdict: TRUE**
Evidence: `SELECT account, project, COUNT(*) FROM sessions GROUP BY account, project ORDER BY n DESC`:
```
personal_max | Tidify   | 16539
personal_max | Other    |  2425
personal_max | WikiLoop |  1339
```
Only `personal_max` appears. Also `SELECT DISTINCT account_id FROM account_projects` confirms all 6 project-map entries are `personal_max`. Consistent.

### NARRATIVE 7: "Incremental scanner works"
**Verdict: TRUE**
Evidence: `SELECT COUNT(*) FROM scan_state` → 209 rows. `SELECT COUNT(*) FROM scan_state WHERE last_offset > 0` → 209 (100%). Top row shows `last_offset=10,232,945` and `lines_processed=4,750` for the largest Tidify session. Incremental scanning is real and saves significant I/O on repeat scans.

### EXTRA NARRATIVE: "Labels are consistent"
**Verdict: TRUE (after the fix session)**
Evidence:
- `config.py:9,21`: `"Work (Max)"`, `"Personal (Pro)"`
- `accounts` table (live): `personal_max → "Work (Max)"`, `work_pro → "Personal (Pro)"`
- `claude_ai_accounts` table (live): same
- `README.md`: updated
- **One leftover**: `accounts` table still contains an inactive row `test_acct | "Test Account (Updated)" | active=0`. Not user-visible (get_accounts_config filters `active=1`) but clutters the DB. Pre-existing, not introduced by the fix session.

---

## Silly bugs found

| # | Severity | File:line | Bug |
|---|---|---|---|
| 1 | 🔴 Critical | `templates/dashboard.html:246,547` and `templates/accounts.html` (all 14 fetch calls) | No `X-Dashboard-Key` header sent — every UI write is now 401 |
| 2 | 🔴 Critical | `scanner.py:65-72` + `analyzer.py:293-350` | Compaction detector watches `input_tokens`, which is ~0 under prompt caching. Zero detections across 20,303 sessions |
| 3 | 🟡 Medium | `analyzer.py:58-61` | Cache hit rate formula uses `reads/(reads+input)` instead of `reads/(reads+writes)` — headline is ~100% when reality is ~96% |
| 4 | 🟡 Medium | `analyzer.py:123-156` | Window boundary is `epoch % 18000` — aligned to 00:00/05:00/10:00/15:00/20:00 UTC, not Anthropic's actual rolling windows. Dashboard `window_pct` can diverge from `claude.ai`'s real number |
| 5 | 🟡 Medium | `data/usage.db` (filesystem, `0644`) | World-readable DB contains plaintext `session_key` values. Not exposed over HTTP but any non-root OS user can read them |
| 6 | 🟠 Low | `cli.py:12-48` | Imports split in two groups with the multi-line `HELP_TEXT` string sandwiched between. Works (imports are valid anywhere), but violates PEP 8 and confuses linters |
| 7 | 🟠 Low | `scanner.py:37` | Hardcoded `"personal_max"` as the no-match fallback account_id. Breaks silently if user renames/removes that account |
| 8 | 🟠 Low | `scanner.py:18-26` | `normalize_model` falls through to `"claude-sonnet"` for unknown model names with no warning — future Anthropic model names that don't contain "opus"/"haiku" silently get Sonnet pricing |
| 9 | 🟠 Low | `config.py:55-58` | `CLAUDE_AI_ACCOUNTS` list is dead code — `get_claude_ai_accounts_all` reads from the DB, never from this constant. Safe to delete |
| 10 | 🟠 Low | `server.py:357-362` | `do_OPTIONS` sends `Access-Control-Allow-Headers: Content-Type` only — does not advertise `X-Dashboard-Key` or `X-Sync-Token`. Cross-origin preflight for those headers would fail. In practice the UI is same-origin so preflight is skipped, so this never fires, but the header is inconsistent with the new auth scheme |
| 11 | 🟠 Low | `server.py:359,405` | `Access-Control-Allow-Origin: *` on every response. Combined with 127.0.0.1 bind, this enables a DNS-rebinding attack path where a malicious page the user visits could read dashboard state (writes are still protected by the dashboard key). Low probability but removable |
| 12 | 🟠 Low | `accounts` table | Stale inactive row `test_acct | Test Account (Updated) | active=0`. Filtered by UI/API but clutters the table |
| 13 | 🟢 Cosmetic | `server.py:139-152` (`/api/accounts/{id}/preview`) | Walks the filesystem for every data_path — if dashboard_key is compromised and paths are set to `/`, this could be a DoS via full-disk walk. Only reachable with auth, so not high severity |
| 14 | 🟢 Cosmetic | `server.py:196-197` | `POST /api/scan` runs a full scan synchronously — an authenticated caller can hammer it to keep SQLite busy. No rate limiting |
| 15 | 🟢 Cosmetic | `server.py:121` | `int((__import__("time").time()) - 30 * 86400)` — uses `__import__` as an inline import in the route handler. Works but is a code smell; `time` should be imported at module top |

### Reachability — dead vs live endpoints

Routes defined in `server.py` but not actually called by any template (GET-side):
- `/api/alerts` (line 81) — 0 template refs
- `/api/trends` (line 73) — 0 template refs  
- `/api/window` (line 66) — 0 template refs
- `/api/projects` (line 51) — 0 template refs
- `/api/claude-ai` (line 87, the top-level one, not `/api/claude-ai/accounts`) — 0 template refs
- `/api/claude-ai/accounts/{id}/history` (line 166) — 0 template refs
- `POST /api/claude-ai/poll` (line 211) — 0 template refs

These are legitimate — the UI pulls everything through `/api/data` which aggregates via `full_analysis()`. But they are still unauthenticated reachable endpoints if someone uses the API directly. Not a bug, just dead surface.

---

## Thread safety assessment

**Threads in play**:
1. Main thread → runs `HTTPServer.serve_forever()` — handles each request synchronously in the main thread (Python's `HTTPServer` is `ThreadingMixIn`-free by default, so it's single-threaded for requests).
2. `scanner.start_periodic_scan` → daemon thread, wakes every 300s, calls `scan_all`.
3. `claude_ai_tracker.start_periodic_poll` → daemon thread, wakes every 300s, calls `poll_all`.

**Shared mutable state**:

| Name | Type | Writers | Readers | Lock? |
|---|---|---|---|---|
| `scanner._last_scan_time` | int | scanner thread (`scanner.py:248`) | HTTP handler (`server.py:108,514`) | No — int assignment is atomic under GIL |
| `claude_ai_tracker._last_poll_time` | int | poll thread (`claude_ai_tracker.py:298`) | HTTP handler (`server.py:97,534`) | No — same |
| `claude_ai_tracker._account_statuses` | dict | poll thread (5 assignment sites) | HTTP handler (`get_account_statuses()` returns `dict(_account_statuses)`) | No — Python's `dict(other_dict)` copy snapshots under GIL. Simple `d[k]=v` is atomic per-key |
| `sqlite3` connection pool | n/a — each `get_conn()` opens a fresh connection; SQLite WAL + `busy_timeout=5000` handles concurrent readers/writers | all | all | SQLite file-level + WAL |

**Verdict**: Thread safety is **adequate but not bulletproof**. Python's GIL prevents data corruption in the simple read/write patterns used here. The worst case is a transient inconsistency (reader sees `_account_statuses` without the key that was just written, or the previous `_last_poll_time` for one request). No crashes, no data loss, no DB corruption. Acceptable for a single-user personal tool. Would need explicit locking if this were ever turned into a multi-user hosted service.

---

## Honest security score

| Area | Score | Reason |
|---|---|---|
| **Authentication** | **6/10** | Server enforces `X-Dashboard-Key` on every write endpoint (confirmed for all POST / PUT / DELETE handlers). `/api/claude-ai/sync` correctly uses the separate `X-Sync-Token`. GET endpoints are unauthenticated but only reachable from 127.0.0.1. **Losing 4 points** because the UI does not send the key — writes from the intended interface (the browser dashboard) are broken. The auth is enforced but unusable. |
| **Input validation** | **7/10** | Body size capped at 100 KB **before** `rfile.read` (good). `account_id` regex-validated on create (`db.py:364`). Path-parameter regexes constrain `[a-z][a-z0-9_]*`. JSON body fields defaulted via `.get()`. Weak spots: `data_paths` accepts any string (could be `/` — DoS-via-walk), Content-Length values aren't bounded to sane ints in `_read_body` itself (only in `do_POST`), no JSON schema validation. |
| **Data exposure** | **6/10** | `session_key` is scrubbed from API responses (2 callsites with inline comments). `dashboard_key` and `sync_token` are only read via `get_setting`, never returned in a response. The DB file is world-readable on disk (0644) — anyone on the host reads session keys. `/api/accounts` still leaks filesystem paths, but only to localhost. Stack traces are not exposed (no `traceback` imports in server.py). |
| **Network binding** | **9/10** | `127.0.0.1:8080` confirmed live. External connect refused. Lose 1 point for the open CORS `*` header enabling DNS rebinding as a theoretical attack path. |
| **Code quality** | **5/10** | No tests. Single 550-line server.py. Compaction detector is broken in practice (0 hits in 20K rows). Cache hit rate formula is conceptually wrong. `cli.py` has weird import placement. `CLAUDE_AI_ACCOUNTS` dead config constant. Stale `test_acct` row in DB. Globals-without-locks pattern works but is fragile. |
| **Secret management** | **5/10** | `sync_token` and `dashboard_key` are auto-seeded with `secrets.token_hex` (good randomness). Never logged. Never returned over the API. But stored plaintext in an `0644` SQLite file on disk, and the CLI prints the `dashboard_key` to stdout whenever you run `stats` (line 130) — a shoulder-surf leak if you share your screen. |
| **Overall** | **6/10** | **Significantly better than pre-fix (3/10)**. The server side of the auth story is real and enforced. The two gaps keeping this from being higher are (a) the UI doesn't send the key so the admin UI is unusable, and (b) the compaction/cache-hit-rate code is telling lies to the user. |

---

## What is genuinely solid (do not undersell)

1. **The localhost binding is real.** `127.0.0.1:8080` verified live; external curl refused. The #1 pre-fix risk is gone.
2. **The auth enforcement on the server is real.** Every POST/PUT/DELETE handler routes through `_require_dashboard_key` with a single deliberate exception for the mac-sync push path. Confirmed by (a) grep, (b) code walkthrough of every handler, (c) live curl tests returning 401 without the header and 200 with the correct value.
3. **The body size guard is in the right place.** `Content-Length > 102400` fails 413 before `rfile.read` runs, in both `do_POST` and `do_PUT`. This kills the "send me a 10 GB POST" DoS vector.
4. **Session keys are not logged.** Grep confirms every reference to `session_key` is either storage, transmission, parameter passing, or explicit scrubbing. The claim from `claude_ai_tracker.py:51` ("NEVER logs session_key") holds up under scrutiny.
5. **No eval/exec/os.system/shell=True anywhere.** Subprocess only exists in `tools/mac-sync.py` with fixed argv arrays.
6. **The incremental scanner actually works.** 209 `scan_state` rows, all non-zero offsets, top offset in the tens-of-megabytes. Session 1's incremental rework is real.
7. **The secret generation is correct.** `secrets.token_hex` is cryptographically random, 128 bits of entropy for `dashboard_key` and 256 for `sync_token`. Seeded idempotently on every `init_db()`.
8. **Path traversal is genuinely closed.** Even with the `basename` guard removed, there is no user-controlled input flowing into any `open()` call. Hardcoded strings only.
9. **Pricing math is correct.** Standard per-million-token billing formula. Division by `1_000_000`. No off-by-one, no `/1024`. Rounds to 8 decimals.
10. **The account tagging story is consistent.** `config.py`, live DB, README, and the actual session rows all agree after the fix session. Post-Session-1 all rows are in `personal_max`; `work_pro` is browser-only.

---

## What is genuinely broken (do not oversell)

1. **The dashboard UI and the accounts admin UI can no longer perform writes.** `templates/dashboard.html` and `templates/accounts.html` make **16 fetch calls** between them that don't send `X-Dashboard-Key`. Every "Scan Now", "Dismiss insight", "Add account", "Update account", "Delete account", "Add project", "Delete project", "Discover paths", "Connect claude.ai session", "Refresh claude.ai", and "Disconnect claude.ai session" button will now silently 401. The dashboard is read-only from the browser until this is fixed.
2. **Compaction detection is dead code.** 0 detections across 20,303 sessions because the heuristic measures the wrong column (`input_tokens` instead of `input_tokens + cache_read_tokens`). The feature is documented, displayed in the UI, and mentioned in insights rules — but it has never fired. The `compaction_gap` insight rule cannot trigger.
3. **The cache hit rate headline is wrong.** Code reports 99.96%; true cache-hit-over-cache-operations rate is 96.1%. The formula counts fresh inputs as "misses" but does not count cache writes as misses, which is backwards. The "100% cache hit rate" claim is a formula artifact, not a fact about the cache.
4. **The 5-hour window is not Anthropic's 5-hour window.** Code snaps to epoch % 18000 (UTC 00:00/05:00/...); real windows roll from the user's first request. The dashboard's `window_pct` will diverge from `claude.ai`'s reported window percentage, and the `predicted_limit_time` insight is based on the wrong boundary.
5. **Session keys are plaintext on disk.** `data/usage.db` is `0644`. Any non-root OS user with filesystem access gets the raw `sessionKey` values from `claude_ai_accounts`. Not reachable over HTTP, but a real risk if the VPS hosts untrusted users.
6. **Dashboard key is shoulder-surfable.** `cli.py stats` (line 130) prints the dashboard_key to stdout in plain text. If you run `stats` on a shared screen or send a screenshot of your dashboard CLI output, you're sharing your admin key.

---

## The three most important fixes remaining

### 1. Wire the dashboard key into the templates (🔴 critical, half a day)

Both HTML files need:
- A small "enter your dashboard key" UI, persisted to `localStorage`
- A wrapper `api(method, path, body)` that attaches `X-Dashboard-Key` from `localStorage` automatically
- A 401-handler that prompts for the key and retries

Without this, the dashboard is unusable for admin operations and the previous security fix is self-defeating. I flagged this at the end of the fix session and you went straight into this audit without asking me to land it — it's still the #1 gap.

### 2. Fix the compaction detector (🔴 correctness, 1 hour)

`scanner.py:65-72` and `analyzer.py:293-350`: change the comparison basis from `input_tokens` alone to `input_tokens + cache_read_tokens`. Re-run a backfill over existing sessions if you want historical compaction stats to reflect reality. Without this fix, the `compaction_gap` insight is a false promise and the "compaction rate %" in `account_metrics` is always 0.

Concrete change in `_detect_compaction`:
```python
prev_context = prev.get("input_tokens", 0) + prev.get("cache_read_tokens", 0)
curr_context = curr.get("input_tokens", 0) + curr.get("cache_read_tokens", 0)
if prev_context > 1000 and curr_context < prev_context * 0.7:
    ...
```
Also apply the same fix to `compaction_metrics` in `analyzer.py`. Add a unit test with a synthetic 3-turn session with cache-read drop.

### 3. Fix the cache hit rate formula (🟡 medium, 15 minutes)

`analyzer.py:58-61`: change the denominator from `input + cache_read` to `cache_read + cache_creation`. Also keep the old formula around under a different name if you want "% of context that was cached" as a separate metric — it's a valid thing to measure, just not "cache hit rate". Update the dashboard label so users aren't told 100% when the real number is 96%.

```python
true_hit_rate = cache_read / (cache_read + cache_creation) * 100 if (cache_read + cache_creation) > 0 else 0
```

---

## Appendix — evidence log

- `ss -tlnp | grep 8080` → `LISTEN 127.0.0.1:8080 users:(("python3",pid=273375,fd=7))` (fix session verification)
- `curl http://YOUR_VPS_IP:8080/api/data` → `Failed to connect` (fix session verification)
- `curl http://localhost:8080/tools/mac-sync.py | grep SYNC_TOKEN` → `SYNC_TOKEN = ""`
- `curl -X POST http://localhost:8080/api/scan` → `HTTP 401 {"error":"unauthorized"}`
- `curl -X POST -H 'X-Dashboard-Key: bee37939...' /api/scan` → `HTTP 200 {"status":"ok",...}`
- 125 KB `POST /api/scan` → `HTTP 413 {"error":"request too large"}`
- `python3 cli.py --help` → prints usage and exits 0
- `python3 -c "import config, db, scanner, ..."` → `all imports OK`
- `SELECT key, length(value) FROM settings` → `sync_token 64`, `dashboard_key 32`, `account_migration_done 1`
- `SELECT account, COUNT(*) FROM sessions GROUP BY account` → `personal_max 20303`
- `SELECT COUNT(*) FROM sessions WHERE compaction_detected=1` → `0`
- `SELECT account_id, label FROM accounts WHERE active=1` → `personal_max | Work (Max)`, `work_pro | Personal (Pro)`
- `SELECT COUNT(*) FROM scan_state WHERE last_offset > 0` → `209` (100% of rows)
- `stat -c '%a' data/usage.db` → `644`
