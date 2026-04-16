# Claudash — Internals

This document is a working map of every major subsystem in Claudash, for the
author. It is intentionally dense. Every claim is sourced to `file:line`.
Where the implementation is rough, that is called out explicitly.

Repo root: `/root/projects/jk-usage-dashboard/`.

---

## 1. JSONL format — what Claude Code writes

### 1.1 Directory layout

Claude Code writes one JSONL file per conversation-session under
`~/.claude/projects/`. The folder name is the absolute path of the project's
working directory with `/` replaced by `-`. For this repo the directory is:

```
~/.claude/projects/-root-projects-jk-usage-dashboard/
    0973e545-22d9-47c9-bd86-3f63db150c32.jsonl   # one file per session
    709337c5-707e-4f36-bb53-0333456767c1.jsonl
    ...
    subagents/
        agent-<uuid>.jsonl                        # subagent files
```

The filename (minus extension) is the session UUID; it also appears as every
row's `sessionId`. `scanner.py` walks these trees via `os.walk` over each
account's `data_paths` (`scanner.py:302-310`).

Platform candidates are discovered in `scanner.discover_claude_paths`
(`scanner.py:334-392`), which probes `~/.claude/projects/`,
`~/Library/Application Support/Claude/projects/`, the Windows
`AppData\Roaming\Claude\projects\` variants, and globs `~/.claude-*/projects`.

### 1.2 Row shape — one JSON object per line

Rows are untyped JSON objects. There are many `type` values
(`permission-mode`, `file-history-snapshot`, `user`, `assistant`,
`tool_result`, etc.). The scanner only extracts ingestion fields it
understands and ignores the rest.

Fields the ingestion path actually reads (`scanner._parse_line`,
`scanner.py:95-147`):

| Field | Source path | Consumer |
|-------|-------------|----------|
| `sessionId` | top-level, with fallbacks to `session_id` then `uuid` | `scanner.py:108` |
| `timestamp` | top-level ISO 8601 string (`..Z`), falls back to `ts` | `scanner.py:109-110` |
| `model` | top-level `model`, else `message.model` | `scanner.py:114-116` |
| `message.usage.input_tokens` | assistant turn usage | `scanner.py:124` |
| `message.usage.output_tokens` | assistant turn usage | `scanner.py:125` |
| `message.usage.cache_read_input_tokens` | cache hits | `scanner.py:126` |
| `message.usage.cache_creation_input_tokens` | cache writes | `scanner.py:127` |
| `message.content[].type == "tool_use"` | for waste detection (separate pass) | `waste_patterns.py:43-86` |

Crucial: `uuid` is **per-message**, not per-session. Using it as `session_id`
silently breaks every per-session metric. `scanner.py:105-108` comments this
and forces the priority `sessionId > session_id > uuid`.

Rows with `input_tokens == 0 and output_tokens == 0` are dropped — they are
tool results or user messages with no billing impact (`scanner.py:129-130`).

### 1.3 Example: an `assistant` row with usage

This is a real line from a local session (tool-use input and thinking text
scrubbed). Field-by-field commentary follows.

```json
{
  "parentUuid": "41dd0c6e-9b15-407c-a493-728e34f8fa3a",
  "isSidechain": false,
  "message": {
    "model": "claude-opus-4-6",
    "id": "msg_01NifAZZVYSNqxgoUzRZLVqK",
    "type": "message",
    "role": "assistant",
    "content": [
      {"type": "thinking", "thinking": "<scrubbed>", "signature": "..."}
    ],
    "stop_reason": "tool_use",
    "usage": {
      "input_tokens": 5,
      "cache_creation_input_tokens": 37973,
      "cache_read_input_tokens": 0,
      "output_tokens": 324,
      "cache_creation": {
        "ephemeral_1h_input_tokens": 37973,
        "ephemeral_5m_input_tokens": 0
      },
      "service_tier": "standard"
    }
  },
  "requestId": "req_011Ca35hUoC8GYgSno8QW24v",
  "type": "assistant",
  "uuid": "47d35a2d-4a64-4652-ae4f-8f08e244ca89",
  "timestamp": "2026-04-14T05:05:56.996Z",
  "userType": "external",
  "entrypoint": "cli",
  "cwd": "/root/projects/jk-usage-dashboard",
  "sessionId": "0973e545-22d9-47c9-bd86-3f63db150c32",
  "version": "2.1.105",
  "gitBranch": "main"
}
```

Commentary:

- `sessionId` → row's `session_id`. Same for every row in this file.
- `timestamp` → epoch via `scanner.parse_timestamp` (strips `Z`, fractional
  seconds, and the `+00:00` suffix — `scanner.py:66-72`). Fractional seconds
  are **dropped** (the `%Y-%m-%dT%H:%M:%S` strptime format has no `.%f`).
- `message.model` → normalized by `scanner.normalize_model` to one of
  `claude-opus`, `claude-sonnet`, `claude-haiku` via substring match
  (`scanner.py:31-39`). `claude-opus-4-6` becomes `claude-opus`.
- `message.usage.input_tokens = 5` → non-cached tokens Claude re-processed
  (mostly the new turn's user message). Under prompt caching most of the
  prompt lives in `cache_read_input_tokens`; `input_tokens` is almost always
  tiny. This is why the compaction heuristic sums `input + cache_read` rather
  than watching `input_tokens` alone (`scanner.py:83-92`).
- `cache_creation_input_tokens = 37973` → cache-write tokens, billed at the
  cache-write rate (opus $18.75/M; `config.py:82`).
- `cache_read_input_tokens = 0` → cold start / cache miss.
- `output_tokens = 324` → assistant-generated tokens.

### 1.4 Example: `tool_use` block (same envelope)

Content blocks within an assistant message can be `"text"`, `"thinking"`, or
`"tool_use"`. Waste detection (`waste_patterns._iter_assistant_tool_calls`,
`waste_patterns.py:43-86`) only looks at `tool_use`:

```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_01...",
        "name": "Bash",
        "input": {"command": "ls /tmp", "description": "list tmp"}
      }
    ]
  }
}
```

The waste detector yields `(turn_index, tool_name, input_dict)` tuples; the
row's `type` must be `"assistant"` and `message.content` must be a list
(`waste_patterns.py:68-84`).

### 1.5 Example: `user` row with no usage (ignored by scanner)

```json
{
  "type": "user",
  "message": {"role": "user", "content": "Do the thing"},
  "timestamp": "2026-04-14T05:05:40.000Z",
  "sessionId": "0973e545-22d9-47c9-bd86-3f63db150c32",
  "uuid": "41dd0c6e-9b15-407c-a493-728e34f8fa3a"
}
```

No `message.usage` → `_parse_line` extracts zeros, hits the guard at
`scanner.py:129`, returns `None`, row is skipped.

### 1.6 Subagent files

When a main session spawns a subagent, Claude Code writes the subagent's
transcript under a `subagents/` folder **inside the parent session folder**:

```
<data_path>/<project-slug>/subagents/agent-<sid>.jsonl
```

`scanner._parse_subagent_info` (`scanner.py:174-185`) detects this by
substring `/subagents/` and grabs the parent-session UUID as
`os.path.basename(parent_dir)`. For project resolution the scanner walks up
*two* levels (`scanner.py:196-199`) so the subagent inherits the parent
project's keyword-matched tag, even though the `subagents/` directory itself
has no matching keyword.

Rows parsed from a subagent file set `is_subagent=1` and
`parent_session_id=<parent uuid>` on the DB row. This powers
`analyzer.subagent_metrics` (`analyzer.py:576-641`) and Story 4 in
`db.get_real_story_insights` (`db.py:1144-1168`).

---

## 2. Scanner (`scanner.py`)

### 2.1 Responsibilities

- Walk every configured `data_paths` folder, discover `.jsonl` files.
- For each file, read **only new bytes** since last scan (incremental).
- Parse each line into a row dict, compute cost, detect compaction within
  the session, insert into `sessions`.
- Record last byte offset back to `scan_state` so next scan resumes there.

Entry points: `scan_all()` (`scanner.py:278-283`) is the mutex-guarded
public API; `_scan_all_locked` does the work; `scan_jsonl_file` does one
file. A daemon thread calls `scan_all` every `interval_seconds`
(`scanner.py:395-406`, default 300s).

### 2.2 Serialization

A module-level `threading.Lock` (`scanner.py:12`) wraps all scans.
`is_scan_running()` (`scanner.py:19-25`) is a non-blocking probe that
tries `acquire(blocking=False)` and immediately releases — used by the HTTP
layer to avoid spamming concurrent scans.

### 2.3 File discovery

```python
for root, dirs, files in os.walk(data_path):     # scanner.py:302
    for fname in files:
        if not fname.endswith(".jsonl"):
            continue
        ...
```

No filter on directory depth. Subagent files are included by design — the
`subagents/` folder lives *inside* a project-session directory.

### 2.4 Incremental offset tracking

The `scan_state` table (`db.py:115-121`) holds:

| column | meaning |
|--------|---------|
| `file_path` (PK) | absolute path |
| `last_offset` | byte offset at which to resume |
| `last_scanned` | epoch of last touch |
| `lines_processed` | running count |

`scan_jsonl_file` reads `last_offset` via `_get_scan_state`
(`scanner.py:150-158`), `f.seek(last_offset)` if non-zero
(`scanner.py:247-248`), streams to EOF, records `f.tell()` back via
`_set_scan_state` (`scanner.py:161-171`, UPSERT on `file_path`).

Truncation / rotation detection: `if file_size < last_offset` →
reset both to 0 (`scanner.py:210-212`). This is correct but coarse — it
won't catch a rewrite where the file size happens to match.

### 2.5 `_parse_line` field extraction

`scanner.py:95-147` — see §1.2 for the extracted fields. Key points:

- Timestamp required — rows with unparseable `timestamp` return `None`
  (`scanner.py:111-112`).
- Usage block is checked at `message.usage` first, then top-level `usage`
  (`scanner.py:118-122`).
- `compute_cost` (`scanner.py:53-60`) prices per million, summing
  `input × rate + output × rate + cache_read × rate + cache_create × rate`
  against `config.MODEL_PRICING` (see §4.1).

### 2.6 Oversized-line guard

`scanner.py:250-252`:

```python
if len(line) > 1_000_000:  # 1MB max line
    print(f"WARNING: skipping oversized line ({len(line)} bytes) in {filepath}", ...)
    continue
```

Protects against a single mis-rotated JSONL row eating all RAM. Known
trade-off: a legitimate huge `tool_result` with a big file is discarded.

### 2.7 Project & account resolution

`scanner.resolve_project` (`scanner.py:42-50`) lowercases the folder path
and scans every project in `PROJECT_MAP` (DB-backed) for any keyword
substring. First match wins; otherwise returns `(UNKNOWN_PROJECT,
"personal_max")`.

The fallback account `"personal_max"` at `scanner.py:50` is **hard-coded**
— if a user has no `personal_max` account, unknown projects get orphan
rows. This matches the seed-config convention but is rough.

For subagent files, resolution is against the grandparent of `subagents/`,
not the file's own folder (`scanner.py:196-199`).

### 2.8 Batched flush (added recently)

Before the batching change, the scanner buffered all rows in memory before
insert. On cold re-scans of multi-GB JSONL trees this blew up RAM. Now:

```python
BATCH_FLUSH_SIZE = 10_000                               # scanner.py:28
...
if len(raw_rows) >= BATCH_FLUSH_SIZE:                   # scanner.py:265
    added += _flush(raw_rows)
    raw_rows = []
```

`_flush` (`scanner.py:218-240`) groups rows by `session_id`, runs
compaction detection **within the batch only**, inserts each row via
`insert_session`, commits. This means a compaction event spanning a batch
boundary can be missed — accepted trade-off for bounded memory.

### 2.9 Compaction detection

`_detect_compaction` (`scanner.py:78-92`) walks consecutive turns in a
single session sorted by timestamp. A compaction is flagged when:

```
prev_ctx > 1000 AND curr_ctx < prev_ctx * 0.7
where ctx = input_tokens + cache_read_tokens
```

Uses total *inbound context* (input + cache_read), not input alone —
because under prompt caching the real prompt size lives in `cache_read`.
This is also mirrored in `analyzer.compaction_metrics`
(`analyzer.py:320-326`) so both paths agree.

### 2.10 Idempotent inserts

The `sessions` table has a `UNIQUE(session_id, timestamp, model)`
constraint (`db.py:63`). `insert_session` uses
`INSERT OR IGNORE` (`db.py:655`). Rescanning the same file from offset 0 is
safe.

---

## 3. Database schema (`db.py`)

### 3.1 File protection

The SQLite file lives at `data/usage.db`. On every `get_conn()` call
(`db.py:24-31`), `_lock_db_file` (`db.py:11-21`) chmods the main DB plus
its `-wal` and `-shm` side files to `0600` (user rw only). This matters
because:

- `claude_ai_accounts.session_key` holds plaintext `sk-ant-...` session
  keys scraped from browser cookies.
- `settings.sync_token` and `settings.dashboard_key` are the only
  auth tokens for write endpoints (`server.py:312`).

### 3.2 WAL mode

`db.py:28-29`:

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

WAL lets the web server, scanner thread, claude.ai poller, and MCP CLI
read concurrently while one writer commits. `busy_timeout=5000` means a
blocked writer waits up to 5s instead of failing instantly. The `-wal`
journal file persists between connections; `_lock_db_file` protects it.

### 3.3 `sessions` table — the core

Defined at `db.py:51-64`, plus migrated columns at `db.py:96-105`.

| column | type | meaning |
|--------|------|---------|
| `id` | INTEGER PK | auto |
| `session_id` | TEXT | Claude Code `sessionId` |
| `timestamp` | INTEGER | epoch seconds |
| `project` | TEXT | from `PROJECT_MAP` keyword match |
| `account` | TEXT | account slug |
| `model` | TEXT | normalized (`claude-opus` / `claude-sonnet` / `claude-haiku`) |
| `input_tokens` | INTEGER | non-cached inbound |
| `output_tokens` | INTEGER | assistant output |
| `cache_read_tokens` | INTEGER | cache hits (cheap) |
| `cache_creation_tokens` | INTEGER | cache writes (expensive) |
| `cost_usd` | REAL | computed by `compute_cost` |
| `source_path` | TEXT | JSONL filepath (debugging provenance) |
| `compaction_detected` | INTEGER | 1 if `_detect_compaction` fired at this turn |
| `tokens_before_compact` | INTEGER | prev-turn context size |
| `tokens_after_compact` | INTEGER | curr-turn context size |
| `is_subagent` | INTEGER | 1 if file was under `/subagents/` |
| `parent_session_id` | TEXT | parent uuid for subagents |
| UNIQUE | `(session_id, timestamp, model)` | idempotent rescan |

### 3.4 Indexes

Base indexes (`db.py:65-67`):
- `idx_sessions_timestamp` — time-range scans
- `idx_sessions_project`
- `idx_sessions_account`

Composite indexes added later (`db.py:108-111`):

| index | columns | why |
|-------|---------|-----|
| `idx_sessions_model` | `model` | rightsizing `WHERE model LIKE '%opus%'` |
| `idx_sessions_account_ts` | `(account, timestamp)` | `account_metrics` etc. do `WHERE account=? AND timestamp >= ?` — the single-column indexes forced full-range scans then filtered. |
| `idx_sessions_project_ts` | `(project, timestamp)` | waste queries filter `project=? AND timestamp >= ?` (30-day outlier window in `waste_patterns.py:243-247`) |
| `idx_sessions_account_project` | `(account, project)` | project rollup per account in `analyzer.project_metrics` + `claudash_project` MCP tool |

### 3.5 Other tables

| table | purpose | defined |
|-------|---------|---------|
| `alerts` | red/amber/green strings for UI alerts bar | `db.py:69-76` |
| `claude_ai_usage` | legacy claude.ai snapshots (pre-split) | `db.py:79-90` |
| `scan_state` | incremental offsets | `db.py:115-121` |
| `daily_snapshots` | per (date, account, project) rollup | `db.py:131-141` |
| `window_burns` | historical 5h window buckets | `db.py:143-152` |
| `insights` | generated by `insights.py` | `db.py:156-165` |
| `accounts` | dynamic account config (seeded from `config.py`) | `db.py:173-184` |
| `account_projects` | keyword map (DB source of truth) | `db.py:186-192` |
| `waste_events` | one row per (session, pattern) | `db.py:201-213` |
| `fixes` + `fix_measurements` | fix tracker | `db.py:221-245` |
| `claude_ai_accounts` | session keys / org ids | `db.py:249-261` |
| `claude_ai_snapshots` | polled claude.ai usage | `db.py:263-277` |
| `settings` | `sync_token`, `dashboard_key`, `last_waste_scan`, migration flags | `db.py:298-302` |

### 3.6 Seeding and migration

`init_db` seeds `accounts` and `account_projects` from `config.ACCOUNTS` /
`config.PROJECT_MAP` on empty DB (`db.py:321-323`, via `_seed_from_config`
at `db.py:342-363`). After first run the DB is source of truth; editing
`config.py` has no effect until `cli.py scan --reprocess` runs
`sync_project_map_from_config` (`db.py:366-378`, UPSERT on
`(account_id, project_name)`).

Schema migrations are idempotent `ALTER TABLE` guarded by `_column_exists`
(`db.py:34-36`). Known migrations: `source_path`, `compaction_detected`,
`is_subagent`, `parent_session_id` (`db.py:96-105`); `daily_budget_usd`
(`db.py:196-197`); `mac_sync_mode` (`db.py:283-284`);
`five_hour_utilization` et al on snapshots (`db.py:287-294`).

---

## 4. Analyzer (`analyzer.py`)

### 4.1 Cost model

`config.MODEL_PRICING` (`config.py:81-85`) is USD per million tokens:

| model | input | output | cache_read | cache_write |
|-------|------:|-------:|-----------:|------------:|
| claude-opus | 15.00 | 75.00 | 1.50 | 18.75 |
| claude-sonnet | 3.00 | 15.00 | 0.30 | 3.75 |
| claude-haiku | 0.25 | 1.25 | 0.025 | 0.30 |

`scanner.compute_cost` (`scanner.py:53-60`) sums all four; `cost_usd` is
persisted per row.

### 4.2 ROI

`account_metrics` (`analyzer.py:72-82`):

```
subscription_roi = total_api_cost_30d / monthly_plan_cost
```

If `account == "all"`, the denominator sums every account's
`monthly_cost_usd`. A ROI of `4.0` means "I spent the equivalent of 4×
what I pay Anthropic if I'd been on pay-per-token pricing." Drives the
`roi_milestone` insight (`insights.py:148-164`) and is the core brag-card
metric.

### 4.3 Cache hit rate

`analyzer.py:58-64`:

```
cache_hit_rate = cache_read_tokens / (cache_read_tokens + input_tokens)
```

`input_tokens` is *non-cached* inbound, so the denominator is the total
fresh-or-cached inbound volume and the ratio answers "what fraction of my
prompt was served from cache?".

The same formula is used as Dimension 1 of the efficiency score
(`analyzer.py:700-707`).

### 4.4 The 5-hour window

Anthropic enforces a rolling 5-hour token budget per account (the "window").
Claudash approximates this with UTC epoch-modulo boundaries:

```python
window_seconds = MAX_WINDOW_HOURS * 3600   # 18000
window_start = last_ts - (last_ts % window_seconds)
if window_start + window_seconds < now:
    window_start = now - (now % window_seconds)
window_end = window_start + window_seconds
```

(`analyzer.py:137-152`). Known caveat — commented at `analyzer.py:127-130`:
this is UTC-anchored, but Anthropic's real `resets_at` drifts per-account
up to 5 hours. For exact tracking the browser collectors (§8) fetch the
real `resets_at` from claude.ai.

Inside the window: sum `input + output` tokens, compute
`window_pct = total / window_limit * 100`, estimate burn rate and
`minutes_to_limit` from elapsed seconds (`analyzer.py:168-183`).

`window_intelligence` wraps `window_metrics` and layers on 7-day history
(`analyzer.py:478-506`): best 5-hour quiet-block (min of all 24 starting
hours of the day), average window pct, count of windows that hit the
limit, and `safe_for_heavy_session = window_pct < 50`.

### 4.5 Subagent separation

All queries that care about subagents use `is_subagent` and
`parent_session_id`. `analyzer.subagent_metrics` (`analyzer.py:576-641`)
rolls up per-project:

- `subagent_cost_usd` = `SUM(cost_usd) WHERE is_subagent=1`
- `subagent_pct_of_total` = subagent cost / total project cost
- `top_spawning_sessions` = top 5 parent sessions ordered by subagent cost

Drives the `subagent_cost_spike` insight (`insights.py:277-299`) and Story
4 (`db.py:1144-1168`).

### 4.6 Compaction intelligence

`analyzer.compaction_metrics` (`analyzer.py:299-363`) groups every
session's rows, re-applies the same `prev_ctx > 1000 && curr_ctx <
prev_ctx * 0.7` rule used by the scanner, and aggregates:

- `avg_savings_pct` — average `(prev-curr)/prev` across detected events
- `compaction_count` — number of events
- `sessions_needing_compact` — sessions whose peak context was
  `> 70%` of `window_token_limit` but had zero compaction events
  (`analyzer.py:330-334`)

### 4.7 Model rightsizing

`model_rightsizing` (`analyzer.py:368-395`):

```
if dominant_model == "claude-opus" and avg_output < 800:
    sonnet_ratio = sonnet_output / opus_output   # 15 / 75 = 0.2
    savings = opus_cost * (1 - sonnet_ratio)     # 80% of opus_cost
```

The 800-output-token threshold is the "Opus is wasted on a short answer"
heuristic. Below 800 tokens, Sonnet would almost certainly have been
sufficient.

### 4.8 Right-sizing in project rollup

`project_metrics` surfaces the same calculation per-project
(`analyzer.py:270-273`), exposed as `rightsizing_savings` on the project
card. Both paths use the ratio `sonnet.output / opus.output`
(`config.py:82-83`: 15/75 = 0.2) — i.e. Sonnet is ~5× cheaper on output.

---

## 5. Waste pattern detection (`waste_patterns.py`)

Four patterns. All detections UPSERT a row into `waste_events` keyed on
`UNIQUE(session_id, pattern_type)` (`db.py:212`). Running detection
repeatedly is idempotent and refreshes `severity`, `turn_count`, `cost`
(`db.insert_waste_event`, `db.py:680-697`).

Incremental gating: `detect_all` reads `settings.last_waste_scan`
(`waste_patterns.py:175-177`), and only reprocesses files whose
`scan_state.last_scanned` is newer than that (`waste_patterns.py:183-189`).
On first run it does a full pass after `clear_waste_events`
(`waste_patterns.py:178-180`).

Thresholds (`waste_patterns.py:35-38`):

```python
FLOUNDER_THRESHOLD        = 4      # consecutive identical tool calls
REPEATED_READ_THRESHOLD   = 3      # same file Read N times
COST_OUTLIER_MULTIPLIER   = 3.0    # session cost > N× project avg
DEEP_TURN_THRESHOLD       = 100    # turns in a session
```

### 5.1 Floundering

`_detect_floundering` (`waste_patterns.py:119-143`). Walks
`(turn, name, input_dict)` tuples, groups consecutive runs keyed by
`(tool_name, hash(str(input)[:200]))`, flags any run of length ≥ 4. The
input-hash dedup means `Bash("npm test")` called 5 times intentionally is
*not* flagged — only identical (tool, input) pairs count. Severity is
`red` if ≥ 2 such runs in one session, else `amber`
(`waste_patterns.py:220`).

Why wasteful: Claude is stuck retrying the same call. Each retry burns
prompt tokens; the signal is binary ("got stuck").

Cost: session-level `SUM(cost_usd)` attributed as the floundering cost —
attribution, not a precise waste $ (see `fix_tracker.capture_baseline` for
a more careful per-turn attribution at `fix_tracker.py:186-194`).

### 5.2 Repeated reads

`_detect_repeated_reads` (`waste_patterns.py:146-159`). Counts `Read` tool
calls per `os.path.basename(file_path)`; any basename with ≥ 3 reads is
flagged. Always `amber`.

Path is stripped to basename specifically to avoid leaking project FS
layout into `waste_events.detail_json` (see comment `waste_patterns.py:155`).

### 5.3 Cost outlier

`waste_patterns.py:237-268`. For every project, compute the 30-day average
session cost; any session with `cost > 3× avg` is flagged as
`cost_outlier`, severity `amber`. Detail JSON includes
`{session_cost, project_avg, multiplier}`.

Why wasteful: a single session spending way more than your own norm is
usually a stuck tool-loop, runaway subagent, or forgotten long-running
job. Even if legit, it deserves attention.

### 5.4 Deep context, no compaction

`waste_patterns.py:270-286`. Sessions with `> 100` turns and zero
`compaction_detected` rows. Severity `amber`. `/compact` never fired, so
the later turns paid full-context prices.

### 5.5 Per-project rollup

`waste_summary_by_project` (`waste_patterns.py:304-336`) aggregates waste
events over the last N days (default 7) and exposes them on
`full_analysis.waste_summary` (`analyzer.py:862-869`) for the UI.

---

## 6. Insights engine (`insights.py`)

All 14 rules run from `generate_insights` (`insights.py:51-359`). Stale
active insights (`dismissed=0, created_at < now - 24h`) are cleared first
(`insights.py:36-39`). `_insight_exists_recent` (`insights.py:42-48`)
dedupes per (type, project) within a cooldown (default 12h, some rules
override to 168h).

| # | `insight_type` | trigger | source metrics | message template |
|---|----------------|---------|----------------|------------------|
| 1 | `model_waste` | `model_rightsizing` returns a project with `monthly_savings > 0` | `analyzer.model_rightsizing` | "{project} uses Opus but avg response is {N} tokens — Sonnet saves ~${X}/mo" |
| 2 | `cache_spike` | `project_cache_24h > 3 × (project_cache_7d / 7)` on `cache_creation_tokens` | `sessions` last 7d / 24h | "{project} cache creation spiked {ratio}x — possible CLAUDE.md reload bug" |
| 3 | `compaction_gap` | `compaction_metrics.sessions_needing_compact > 0` (peak ctx > 70% window, zero compactions) | `analyzer.compaction_metrics` | "{N} sessions this week hit 80% context with no /compact — risk of context rot" |
| 4 | `cost_target` | `project.avg_cost_per_session <= COST_TARGETS[project]` | `analyzer.project_metrics` + `config.COST_TARGETS` | "{project} hit ${target}/file target — avg ${actual}/session" |
| 5 | `window_risk` | `window_metrics.minutes_to_limit < 60` | `analyzer.window_metrics` | "{label} window at {pct}% — exhaust predicted at {HH:MM UTC}" |
| 6 | `roi_milestone` | `subscription_roi >= 10x / 5x / 2x` (highest first, 168h cooldown) | `account_metrics` | "{label} ROI crossed {N}x this month — ${api_equiv} API equiv on ${plan} plan" |
| 7 | `heavy_day` | heaviest weekday > 1.5× avg day (168h cooldown) | `sessions` last 30d per account | "{Weekday}s are your heaviest Claude day — {top_project} pattern" |
| 8 | `best_window` | 5h block with minimum token sum over 7d (168h cooldown) | `sessions` last 7d | "Your quietest window is {H}:00-{H+5}:00 UTC — ideal for autonomous runs" |
| 9 | `window_combined_risk` | `code_pct + browser_pct > 80` | `window_metrics` + `claude_ai_snapshots.pct_used` | "Combined window (Code + browser) at {pct}% for {label} — slow down" |
| 10 | `session_expiry` | browser account status `expired` AND last_polled > 30 min stale | `claude_ai_accounts` | "{label} claude.ai session expired — update key in Accounts" |
| 11 | `pro_messages_low` | Pro plan, `messages_used / limit > 0.7` | `claude_ai_snapshots` | "{label} at {used}/{limit} messages — consider spacing out conversations" |
| 12 | `subagent_cost_spike` | `subagent_pct_of_total > 30%` in a project | `analyzer.subagent_metrics` | "{project} sub-agents consumed {pct}% of project cost (${cost}) — check orchestration" |
| 13 | `floundering_detected` | `COUNT(*) FROM waste_events WHERE pattern_type='floundering'` in last 7d | `waste_events` | "{project} has N floundering session(s) — Claude stuck retrying (${wasted} at risk)" |
| 14 | `budget_exceeded` / `budget_warning` | `today_cost > budget` / `budget_pct > 80` (6h cooldown) | `analyzer.daily_budget_metrics` | "{label} exceeded daily budget — ${cost} vs ${limit} (${over} over)" / "..." |

Every rule writes via `insert_insight` (`db.py:903-908`) — account, project,
type, message, JSON detail blob. The UI reads via `get_insights` with
dismiss filtering (`db.py:911-919`).

---

## 7. Efficiency score

Defined in `analyzer.compute_efficiency_score` (`analyzer.py:682-807`).
Five dimensions, weighted:

| dim | weight | formula |
|-----|-------:|---------|
| 1. Cache efficiency | 25% | `cache_reads / (cache_reads + input_tokens) × 100` |
| 2. Model rightsizing | 25% | `(1 - opus_short/total_opus) × 100` where `opus_short` = Opus sessions with `output_tokens < 300` |
| 3. Window discipline | 20% | piecewise: `<60% → linear 0..70`; `60–80% → linear 70..100`; `>80% → 100 - (pct-80)×2` |
| 4. Floundering rate | 20% | `max(0, 100 - flounder_pct × 10)` — 1% flounder sessions = 90, 10% = 0 |
| 5. Compaction discipline | 10% | `min(100, compact_rate / 0.05 × 100)` — 5% of sessions compacting = 100 |

Total = `round(sum(score × weight))`, clamped `[0, 100]`. Grade:
`A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, else F` (`analyzer.py:787-797`).

Why F is common: dimension 1 punishes mixed short-call and long-call usage
(your `input_tokens` grows with every uncached user message); dimension 2
penalises *any* Opus session whose output happens to be under 300 tokens —
fine-grained Claude Code prompts routinely fall below that. Getting into
B territory typically requires: persistent CLAUDE.md caching, Sonnet as
the default for iteration, and early `/compact` on long sessions.

`top_improvement` is the dimension with the lowest **weighted** score —
i.e. the one where gains move the total most (`analyzer.py:799`).

---

## 8. Browser tracking

### 8.1 Two windows, two APIs

- **Claude Code** burns the rolling 5h window via the API Claude Code
  calls when you run `claude`. Claudash reconstructs this from the local
  JSONL logs (§4.4).
- **claude.ai web chat** burns the *same* 5h window from the other side
  (browser messages). That burn is visible only via
  `https://claude.ai/api/organizations/{org_id}/usage`. Claudash surfaces
  both and optionally combines them in the `window_combined_risk` insight.

`claude_ai_tracker.fetch_usage` (`claude_ai_tracker.py:114-196`) hits the
endpoint with a `sessionKey` cookie and normalizes the response to
`{tokens_used, tokens_limit, messages_used, messages_limit, pct_used,
window_start, window_end, plan, raw}`. For Max it keys on tokens; for Pro
it keys on message counts.

### 8.2 Two collectors

**`tools/oauth_sync.py`** — the recommended path for Claude Code users.
Reads Claude Code's own OAuth access token from
`~/.claude/.credentials.json` (plus `~/.claude-personal/...` and
`~/.claude-work/...`, `tools/oauth_sync.py:45-49`), or on macOS falls back
to the keychain entry
`security find-generic-password -s "Claude Code-credentials" -a "Claude Code"`
(`tools/oauth_sync.py:75-98`). Calls claude.ai as
`Authorization: Bearer <token>`. No cookie scraping, no per-browser
decryption. Pure stdlib, cross-platform.

**`tools/mac-sync.py`** — for browser-only users (no Claude Code
install). macOS only. Copies the Chrome/Vivaldi `Cookies` SQLite DB to
a tempfile, reads the `encrypted_value` for `sessionKey` at
`host_key=.claude.ai` (`tools/mac-sync.py:117-152`), then decrypts with
PBKDF2(sha1, keychain-password, "saltysalt", 1003, 16) → AES-128-CBC via
the `openssl` CLI (`tools/mac-sync.py:155-200`). Output is the raw
`sk-ant-...` session key. Keychain password comes from
`security find-generic-password -s "Chrome Safe Storage"` (or `Vivaldi
Safe Storage`).

Both collectors hit `POST http://<vps>:<port>/api/claude-ai/sync` with
`X-Sync-Token: <sync_token>` and a JSON body `{session_key, org_id,
browser, account_hint, plan, usage}`.

### 8.3 Server handler

`server._handle_sync` (`server.py:666-750`). Flow:

1. Constant-time compare of `X-Sync-Token` against
   `settings.sync_token` via `hmac.compare_digest` (`server.py:673`). 403
   on mismatch.
2. Match incoming `org_id` against an existing `claude_ai_accounts` row.
   Fallback: fuzzy match `account_hint` against account labels. Fallback:
   first `unconfigured` account. Fallback: first account (prints a loud
   WARNING to stderr — `server.py:715-716`).
3. `upsert_claude_ai_account` writes the session_key/org_id/plan/status,
   then marks `mac_sync_mode = 1` (`server.py:727-731`). This flag tells
   the server-side poller to skip this account
   (`claude_ai_tracker.poll_single`, `claude_ai_tracker.py:217-222`) —
   the Mac pushes, the VPS never polls directly.
4. If `usage` is in the body, `insert_claude_ai_snapshot` persists a
   point-in-time snapshot (`db.py:984-1014`, auto-purged to last 200
   per account).
5. Returns `{success, account_label, matched_account, pct_used, browser}`.

### 8.4 Dashboard consumption

The dashboard polls `/api/claude-ai` which reads
`get_latest_claude_ai_snapshot` (`db.py:1017-1026`) and
`get_claude_ai_snapshot_history` (`db.py:1029-1039`). Combined-window risk
and session-expiry insights are generated by `insights.py:212-254`.

---

## 9. MCP server (`mcp_server.py`)

### 9.1 Transport

JSON-RPC 2.0 over stdio. Each message is one line of JSON on stdin; each
response is one line on stdout. `run_stdio` (`mcp_server.py:355-373`) reads
forever, dispatching through `handle_request`.

Claude Code (or Claude Desktop) launches the server as a subprocess,
configured via `~/.claude/settings.json` / `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claudash": {
      "command": "python3",
      "args": ["/absolute/path/to/claudash/mcp_server.py"]
    }
  }
}
```

`PROTOCOL_VERSION = "2024-11-05"` (`mcp_server.py:55`). Handshake is
`initialize` → server returns `{protocolVersion, capabilities: {tools:
{}}, serverInfo}` (`mcp_server.py:318-323`). The `notifications/initialized`
notification returns `None` (no response body — it's a notification).

Supported methods: `initialize`, `notifications/initialized`, `tools/list`,
`tools/call` (`mcp_server.py:318-352`). Anything else → JSON-RPC error
`-32601 Method not found`. Tool exceptions are wrapped as
`-32000 Tool execution failed`.

Reads SQLite directly (`mcp_server.py:29-30`) — no dependency on the web
server, works offline and in cron.

### 9.2 The 5 tools

Registered in `TOOLS` (`mcp_server.py:256-297`). Each has a handler
returning a JSON-serializable dict, wrapped in the MCP
`{"content": [{"type": "text", "text": <json>}]}` envelope
(`mcp_server.py:343-346`).

| tool | returns | handler |
|------|---------|---------|
| `claudash_summary` | per-account: window_pct, ROI, cache hit rate, sessions_today, 30-day cost, top project | `_tool_claudash_summary` `mcp_server.py:62-85` |
| `claudash_project` | detailed project metrics (requires `project_name` arg) | `mcp_server.py:88-127` |
| `claudash_window` | per-account: window pct, burn rate, predicted exhaust ISO, best start hour | `mcp_server.py:130-157` |
| `claudash_insights` | active insights list with priority mapping (red/window_risk/etc. → "critical") | `mcp_server.py:160-187` |
| `claudash_action_center` | top 3 ranked actions: budget-exceeded, floundering projects, Opus overuse, compaction gap | `mcp_server.py:190-251` |

### 9.3 Example flow

User in a Claude Code session asks "how much did Tidify cost this month?":

1. Claude Code sees `claudash_project` in its tool list (populated at
   startup via `tools/list`).
2. Claude invokes `tools/call` with
   `{name: "claudash_project", arguments: {project_name: "Tidify"}}`.
3. `mcp_server.handle_request` routes to `_tool_claudash_project`
   (`mcp_server.py:88-127`).
4. Handler opens SQLite, calls `project_metrics(conn, "all")`, finds the
   matching project (case-insensitive), runs two follow-up SQL queries for
   compaction count and avg turns, returns a dict.
5. Server JSON-serializes the dict inside the MCP `content` envelope and
   writes it to stdout.
6. Claude reads `cost_30d_usd`, surfaces a natural-language answer.

`run_test` (`mcp_server.py:376-403`) invokes every tool once with a
plausible arg — used in CI / smoke tests.

---

## 10. Fix tracker (`fix_tracker.py`)

### 10.1 What makes it different

Most observability tools stop at "here's what's broken". Fix tracker
closes the loop: detect → fix → **prove the fix worked**, with a verdict
that isn't just "cost went down" (which is noisy) but a plan-aware delta
honest about what matters on each pricing tier.

### 10.2 Baseline snapshot

`capture_baseline(conn, project, days_window=7)` (`fix_tracker.py:109-243`)
freezes these fields at fix-creation time:

| field | computation |
|-------|-------------|
| `sessions_count` | `COUNT(DISTINCT session_id)` in window |
| `cost_usd` | `SUM(cost_usd)` |
| `avg_cost_per_session` | total / sessions |
| `cache_hit_rate` | `cache_read / (cache_read + cache_create) × 100` |
| `avg_turns_per_session` | `total_rows / sessions` |
| `compaction_events` | count where `compaction_detected=1` |
| `compaction_rate` | compactions / sessions |
| `waste_events` | `{floundering, repeated_reads, deep_no_compact, cost_outliers, total}` |
| `subagent_cost_pct` | subagent cost / total |
| `window_hit_rate` | avg of `hit_limit` in `window_burns` for the account |
| `tokens_wasted_on_floundering` | `floundering × avg_tokens_per_turn` |
| `tokens_wasted_on_repeated_reads` | `repeated_reads × 2 × avg_cache_read_per_turn` |
| `effective_window_pct` | `max(0, (total_tokens - wasted) / total_tokens × 100)` |
| `files_per_window` | `_estimate_files_per_window` — bucket distinct session first-seen timestamps into 5-hour buckets, average (`fix_tracker.py:246-267`) |
| `plan_type`, `plan_cost_usd` | for later verdict branching |

The attribution at `fix_tracker.py:186-194` is deliberately per-turn, not
per-session, with a comment explaining that per-session scaling "wildly
over-counts under prompt caching" — cache_read dwarfs everything else.

### 10.3 Measure — before/after delta

`measure_fix(conn, fix_id)` → `compute_delta` (`fix_tracker.py:279-383`):

1. Re-run `capture_baseline` for the same project and `days_window`.
2. Count sessions with `timestamp > fix.created_at` for the project.
3. Diff every field, compute signed % change via `_pct_change`.
4. `api_equivalent_savings_monthly = max((before_cost - after_cost) × 30 / days, 0)`.
5. `improvement_multiplier = files_per_window_after / files_per_window_before`.
6. `primary_metric = "window_efficiency"` for max/pro, `"cost_usd"` for api.

Result persists via `insert_fix_measurement` (`db.py:752-761`).

### 10.4 Verdict logic

`determine_verdict` (`fix_tracker.py:386-415`):

```
if sessions_since_fix < 3:                        return "insufficient_data"
if waste_events.pct_change <= -20:                return "improving"
if waste_events.pct_change >= +10:                return "worsened"
if plan in (max, pro):
    if effective_window_pct.pct_change >= +15:    return "improving"
    if effective_window_pct.pct_change <= -10:    return "worsened"
else (api):
    if cost_usd.pct_change <= -10:                return "improving"
    if cost_usd.pct_change >= +10:                return "worsened"
return "neutral"
```

Thresholds at `fix_tracker.py:76-83`. After 7 days of sustained
`improving`, `measure_fix` promotes `fixes.status` to `confirmed`
(`fix_tracker.py:437-438`). A regression reverts to `applied`
(`fix_tracker.py:439-440`).

### 10.5 Why plan-aware matters

Per the module docstring (`fix_tracker.py:15-27`): for Max/Pro, you are on
a flat subscription. Saving dollars is nonsensical — you already paid.
The right metric is "same $100/mo plan, 2.5× more output". For API, it's
real dollars. The verdict, delta JSON, and share card all branch on this
via `plan_type`. Using the same cost_usd delta everywhere would mislead
Max/Pro users into thinking a fix didn't work when in fact they reclaimed
budget they then spent on more useful work.

### 10.6 Share card

`build_share_card` (`fix_tracker.py:448-502`) produces a plain-text
before/after receipt with plan-aware framing:

- Max/Pro: shows effective window %, files per window, multiplier, and
  "API-equivalent waste eliminated: ~$X/mo" (explicitly labelled
  API-equivalent, never "you saved $X").
- API: shows cost per session, monthly savings in actual dollars.

### 10.7 Known rough edges

- `_estimate_files_per_window` uses `first_seen // 18000` buckets — this
  is UTC-modulo same as the analyzer, not real rolling windows. Fine for
  relative deltas, wrong for absolute claims.
- `capture_baseline` looks up the project's account via the *first*
  session row (`fix_tracker.py:95-98`). If a project spans accounts, the
  plan_type lookup is whichever one showed up first.
- Waste-event attribution (`REPEATED_READ_EXTRA_TURNS = 2` at
  `fix_tracker.py:190`) is a hand-tuned constant, not empirically
  derived.

---

## Appendix: data flow summary

```
Claude Code     → ~/.claude/projects/<slug>/<sid>.jsonl   (local JSONL)
scanner         → sessions, scan_state                    (incremental)
waste_patterns  → waste_events                            (tool_use pass)
analyzer        → in-memory rollups, daily_snapshots, window_burns
insights        → insights                                (14 rules)
fix_tracker     → fixes, fix_measurements                 (baseline/measure)

claude.ai (web) → oauth_sync.py / mac-sync.py
                → POST /api/claude-ai/sync (X-Sync-Token)
                → claude_ai_accounts, claude_ai_snapshots

mcp_server.py   — JSON-RPC over stdio, reads SQLite directly (5 tools)
server.py       — HTTP dashboard, reads SQLite via analyzer.full_analysis
cli.py          — operator commands (scan, keys, fix add/measure, etc.)
```

Every mutation is idempotent or UPSERT: `INSERT OR IGNORE` on sessions,
`ON CONFLICT DO UPDATE` on scan_state / waste_events / daily_snapshots /
claude_ai_snapshots / settings / account_projects. The DB is safe to
re-process from scratch at any time; the only state lost on reset is
`scan_state.last_offset`, which just forces a full re-read.
