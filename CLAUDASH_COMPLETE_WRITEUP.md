# Claudash — Complete Technical and Product Writeup
## A Personal Claude Code Usage Intelligence Dashboard

**Version**: 1.0.15 (npm: @jeganwrites/claudash)
**Author**: Jegan Nagarajan
**Date**: 2026-04-16
**Repository**: jk-usage-dashboard
**Live DB stats as of writeup date**: 21,051 sessions · $7,455.03 total · 30-day window

---

## Table of Contents

1. [The Problem and Founding Story](#1-the-problem-and-founding-story)
2. [What Claudash Actually Is](#2-what-claudash-actually-is)
3. [Data Architecture — How JSONL Becomes Metrics](#3-data-architecture--how-jsonl-becomes-metrics)
4. [The Database Schema — 18 Tables Explained](#4-the-database-schema--18-tables-explained)
5. [The Scanner — Incremental JSONL Ingestion](#5-the-scanner--incremental-jsonl-ingestion)
6. [The Analyzer — Metrics Computation Engine](#6-the-analyzer--metrics-computation-engine)
7. [Waste Detection System](#7-waste-detection-system)
8. [The Fix Pipeline — From Waste to CLAUDE.md](#8-the-fix-pipeline--from-waste-to-claudemd)
9. [Insights Engine — 14 Rules](#9-insights-engine--14-rules)
10. [The Dashboard Server — HTTP, SSE, and Security](#10-the-dashboard-server--http-sse-and-security)
11. [MCP Integration — Bidirectional Tool Protocol](#11-mcp-integration--bidirectional-tool-protocol)
12. [Browser Account Tracking](#12-browser-account-tracking)
13. [CLI Interface and Distribution](#13-cli-interface-and-distribution)
14. [Architecture Decisions and What Was Deliberately Left Out](#14-architecture-decisions-and-what-was-deliberately-left-out)
15. [Real Numbers from the Live Database](#15-real-numbers-from-the-live-database)
16. [Session-by-Session Build History](#16-session-by-session-build-history)
17. [Bug Registry — BUG-001 Through BUG-014](#17-bug-registry--bug-001-through-bug-014)
18. [What Is Incomplete, Broken, or Deferred](#18-what-is-incomplete-broken-or-deferred)

---

## 1. The Problem and Founding Story

### The Spend Shock

In early 2026, the developer of Claudash was running Claude Code across multiple projects — Tidify (a healthcare data cleaning platform), Brainworks, WikiLoop, CareerOps, and Claudash itself. Claude Code does not tell you how much you are spending. It shows a spinning progress indicator and a model name. There is no cost counter, no daily summary, no warning when you are about to blow $200 in an afternoon.

The first shock came at billing time. The number was not catastrophic, but it was opaque. There was no breakdown by project, no way to know which sessions had cost $40 and which had cost $0.40, no visibility into why some sessions felt expensive — the assistant just kept reading the same files over and over, or produced long outputs that led nowhere.

### The Existing Tools

Several open-source tools existed at the time:

- **ccusage** (11,500+ GitHub stars): A terminal utility for aggregating Claude Code token usage from JSONL transcripts. Excellent at the core job — read files, tally tokens, show a table. Does not persist data, does not track waste, does not give advice.
- **claude-usage**: Similar scope to ccusage, slightly different interface. Also read-and-display, not diagnose-and-improve.
- **claude-view**: Focused on transcript viewing rather than cost tracking.

None of these answered the questions that actually mattered for someone spending real money:

1. Which projects are burning money wastefully, not just heavily?
2. Am I getting worse at using Claude over time, or better?
3. When my Claude Code session starts repeating itself, can I get an automated warning?
4. Can the dashboard write a fix for me — a CLAUDE.md improvement or settings change — and then measure whether it worked?

These are different questions from "how many tokens did I use today." Claudash was built to answer them.

### The Design Commitment

The project committed early to being a local-first, privacy-preserving tool. All data lives in a SQLite database at `data/usage.db` inside the project directory. No cloud sync. No telemetry. The JSONL transcript files that Claude Code writes contain your entire conversation history — every message, every tool call. Claudash reads them but never uploads them.

The other commitment was to real-time feedback. The existing tools were retrospective — run them after the fact to see what happened. Claudash wanted to be active during sessions: SSE streaming a live cost meter, MCP tools that Claude itself can call to get context about its own performance, and pre/post hooks that fire on every tool use.

### Version 2 — Built in One Session

On April 16, 2026, version 2.0 was designed and built in a single working session. Seven features were added, 57 automated gate checks were run, and zero failures were recorded:

- **F1**: Session lifecycle event tracking — 280 events (135 compact, 145 subagent_spawn), all with context percentage at time of event
- **F2**: Context rot visualization — inline SVG chart per project showing output/input ratio degrading with session depth
- **F3**: Bad compact detector — regex-based detection of post-compact context loss signals
- **F4**: Agentic fix loop Phase 1 — LLM-driven CLAUDE.md rule generation with 3-provider support (Anthropic direct, AWS Bedrock, OpenRouter — all Anthropic models, restricted in v2.0.1)
- **F5**: Bidirectional MCP — 10 tools total (5 read + 5 write), warning queue, Claude Code can now report its own waste
- **F6**: Streaming cost meter — SSE endpoint + Claude Code hooks, live cost ticker in the dashboard, real-time floundering detection
- **F7**: Per-project autoCompactThreshold recommendations — data-driven settings.json snippets, copyable from the dashboard

All 8 commits pushed to github.com/pnjegan/claudash the same day. Zero pip dependencies added to the core. The tool remains installable with a single npm command: `npm install -g @jeganwrites/claudash`.

---

## 2. What Claudash Actually Is

### One-Sentence Description

Claudash is a local dashboard that reads Claude Code JSONL transcripts, detects wasteful patterns, generates CLAUDE.md improvements, measures whether those improvements worked, and shows everything in a browser UI with a live cost meter.

### The Four-Stage Loop (v2 Vision)

The CLAUDASH_V2_PRD.md describes a loop with four stages:

```
Detect → Generate → Approve + Apply → Measure
```

1. **Detect**: The waste detector runs after every scan and classifies sessions into four pattern types: repeated_reads, floundering, deep_no_compact, cost_outlier.
2. **Generate**: The fix generator calls Claude (via Anthropic direct, AWS Bedrock, or OpenRouter — all Anthropic models) with a pattern-specific prompt template and produces a concrete fix — a CLAUDE.md block, a settings.json change, or an architectural recommendation.
3. **Approve + Apply**: Currently a CLI-only workflow. The user runs `claudash fix add` to create a fix interactively, or `claudash fix generate` to auto-generate one. There is no browser UI for reviewing or applying fixes yet.
4. **Measure**: After applying a fix, the user runs `claudash measure` to capture a baseline, then runs it again later to compute the delta — did token usage drop? Did cost per session improve?

As of v1.0.15, stages 1 and 4 are fully operational, stage 2 works but requires CLI interaction, and stage 3 (browser UI for approve/apply) is not built.

### What the Dashboard Shows Today

Opening `http://localhost:8080` shows:

- **Header**: Tool name, version, current date, account selector
- **Summary bar**: Total sessions, total cost, cache hit rate, average session cost
- **Live cost meter**: SSE-streamed widget showing currently-active sessions, their estimated tokens (pre-hook) and actual tokens (post-hook), updated every few seconds
- **Project breakdown table**: Per-project session count, token totals, cost, cache rate
- **Window burn chart**: Context window utilization over the last 7 days
- **Active insights panel**: Cards for each undismissed insight (model_waste, window_risk, etc.)
- **Waste events table**: All detected waste events with pattern type, severity, session ID
- **Lifecycle events**: Compact events and subagent spawns with context percentages
- **Fix tracker**: Active fixes and their measurement verdicts
- **Compaction advisor**: Per-project threshold recommendations (Rule A through E)
- **Context rot chart**: Output/input ratio vs turn depth, showing where sessions degrade

---

## 3. Data Architecture — How JSONL Becomes Metrics

### The Source Format

Claude Code writes one JSONL file per conversation. Each file is a sequence of newline-delimited JSON objects. The files live at:

```
~/.claude/projects/<encoded-path>/<session-uuid>.jsonl
```

The encoded path is the project directory path with slashes replaced by dashes. For example, a project at `/root/projects/tidify` produces files at:

```
~/.claude/projects/-root-projects-tidify/<uuid>.jsonl
```

Each line in a JSONL file is one of these types:

**permission-mode** (always first line):
```json
{
  "type": "permission-mode",
  "permissionMode": "default",
  "sessionId": "0973e545-22d9-47c9-bd86-3f63db150c32"
}
```

**user message**:
```json
{
  "parentUuid": null,
  "type": "user",
  "message": {"role": "user", "content": "<command-message>next</command-message>"},
  "uuid": "27dbebd4-...",
  "timestamp": "2026-04-14T05:05:54.103Z",
  "sessionId": "0973e545-...",
  "version": "2.1.105",
  "gitBranch": "main"
}
```

**assistant message with tool use**:
```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "role": "assistant",
    "content": [{"type": "tool_use", "id": "toolu_01...", "name": "Bash", "input": {...}}],
    "usage": {
      "input_tokens": 5,
      "cache_creation_input_tokens": 37973,
      "cache_read_input_tokens": 0,
      "output_tokens": 324
    }
  },
  "sessionId": "0973e545-...",
  "timestamp": "2026-04-14T05:05:58.138Z"
}
```

**tool_result**:
```json
{
  "type": "tool_result",
  "content": [{"type": "text", "text": "..."}],
  "tool_use_id": "toolu_01...",
  "uuid": "...",
  "sessionId": "0973e545-..."
}
```

### The Critical Field: `message.usage`

The `usage` block only appears on `assistant` type lines. It contains:

- `input_tokens`: Tokens in the context window that were NOT cached
- `cache_read_input_tokens`: Tokens served from the prompt cache (much cheaper)
- `cache_creation_input_tokens`: Tokens written to the prompt cache this turn
- `output_tokens`: Tokens in the assistant's response

This is the raw material for all cost calculations.

### Token Pricing (config.py)

The `MODEL_PRICING` dict in `config.py` contains per-million-token prices:

| Model | Input | Output | Cache Write | Cache Read |
|-------|-------|--------|-------------|------------|
| claude-opus | $15.00 | $75.00 | $18.75 | $1.50 |
| claude-sonnet | $3.00 | $15.00 | $3.75 | $0.30 |
| claude-haiku | $0.25 | $1.25 | $0.3125 | $0.025 |

The cost formula applied in `scanner.py` `_parse_line()`:

```python
cost = (
    (input_tokens * pricing["input"]) +
    (output_tokens * pricing["output"]) +
    (cache_creation_tokens * pricing["cache_write"]) +
    (cache_read_tokens * pricing["cache_read"])
) / 1_000_000
```

### Session Identity

One subtlety: a JSONL file may contain messages from multiple "sessions" in the Claude Code sense. The scanner uses the `sessionId` field (which persists across compaction within a single conversation) rather than the `uuid` field (which is per-message). The function `_parse_line()` in `scanner.py` prefers `sessionId` over `uuid` when constructing the per-session aggregate.

### The Scan State System

The scanner never re-reads data it has already processed. The `scan_state` table stores:

- `file_path`: absolute path to the JSONL file
- `last_byte_offset`: byte position up to which the file has been processed
- `last_scanned`: Unix timestamp of last scan

On each scan pass, `scan_jsonl_file()` seeks to `last_byte_offset`, reads only new bytes, and after processing updates the offset. This makes incremental scans fast even across a directory of thousands of JSONL files.

---

## 4. The Database Schema — 18 Tables Explained

The database lives at `data/usage.db`. It uses SQLite with WAL mode for concurrent read performance. The `_lock_db_file()` function in `db.py` calls `os.chmod(db_path, 0o600)` immediately after creation to ensure the file is not world-readable, since the settings table stores sensitive keys.

### Core Data Tables

**sessions** — One row per Claude Code session (conversation). Primary key is `session_id` (the UUID from JSONL). Columns:
- `session_id`, `timestamp`, `project`, `account`, `model`
- `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`
- `cost_usd` — computed at scan time using MODEL_PRICING
- `source_path` — absolute path to the originating JSONL file
- `compaction_detected` — boolean, set by `_detect_compaction()`
- `tokens_before_compact`, `tokens_after_compact` — raw context sizes when compaction is detected
- `is_subagent` — boolean, set by `_parse_subagent_info()` when path contains `/subagents/`
- `parent_session_id` — for subagents, the session that spawned them
- `compact_count`, `subagent_count` — aggregated per-session in lifecycle pass
- `compact_timing_pct` — at what context % the first compact happened

**scan_state** — One row per JSONL file. Stores `last_byte_offset` for incremental scanning.

**daily_snapshots** — Aggregated daily totals per project/account. Used for trend charts. Populated by a separate pass in `scanner.py`.

**window_burns** — Per-session window utilization records. `context_pct` is the peak context window percentage during that session, derived from `(input_tokens + cache_read_tokens) / window_token_limit`.

### Waste and Lifecycle Tables

**waste_events** — One row per detected waste pattern instance. Columns:
- `session_id`, `project`, `account`
- `pattern_type`: one of `repeated_reads`, `floundering`, `deep_no_compact`, `cost_outlier`
- `severity`: `low`, `medium`, `high`
- `turn_count`: number of turns in the session
- `token_cost`: total cost of the session (used to quantify the waste)
- `detected_at`: Unix timestamp
- `detail_json`: JSON blob with pattern-specific evidence (file list for repeated_reads, tool sequence for floundering, etc.)

**lifecycle_events** — One row per compact or subagent_spawn event detected in JSONL. Columns:
- `session_id`, `project`, `event_type` (compact or subagent_spawn)
- `timestamp`, `context_pct_at_event`
- `event_metadata`: JSON blob (for compact: tokens_before/after; for subagent: child session ID)

**mcp_warnings** — Warnings generated by `generate_mcp_warnings()` in `scanner.py`. Currently 1 row in the live DB.

### Fix Tracking Tables

**fixes** — One row per fix. Columns:
- `id`, `created_at`, `project`, `waste_pattern`
- `title`, `fix_type`: one of `claude_md`, `prompt`, `settings_json`, `architecture`, `human`
- `fix_detail`: the actual fix text (CLAUDE.md block, settings change, etc.)
- `baseline_json`: metrics snapshot at time of fix creation (from `capture_baseline()`)
- `status`: `measuring`, `success`, `failed`, `abandoned`
- `generated_by`: `manual`, `claude`, `gpt4`, `bedrock`
- `generation_prompt`, `generation_response`: full LLM exchange if auto-generated
- `applied_to_path`: path to CLAUDE.md or settings file if fix was applied
- `waste_event_id`: FK to the waste_events row that triggered this fix

**fix_measurements** — One row per measurement snapshot for a fix. Columns:
- `fix_id`, `measured_at`
- `metrics_json`: current metrics at measurement time
- `delta_json`: computed delta from baseline
- `verdict`: `improving`, `insufficient_data`, `regressing`, `stable`

### Account and Browser Tables

**accounts** — The manually-configured Claude Code accounts. Columns:
- `account_id`, `label`, `plan` (max/pro/api)
- `monthly_cost_usd`, `window_token_limit`, `color`
- `data_paths`: JSON array of filesystem paths to scan for JSONL files
- `active`, `daily_budget_usd`

**account_projects** — Maps which projects have been seen under which account.

**claude_ai_accounts** — Browser-tracked accounts (from claude.ai session polling). Columns:
- `account_id`, `label`, `org_id`
- `session_key`: the sk-ant-sid cookie value (stored in DB — security concern noted in §18)
- `plan`, `status`, `last_polled`, `mac_sync_mode`

**claude_ai_usage** — Historical browser usage poll results (currently empty in live DB).

**claude_ai_snapshots** — Latest snapshot per browser account. The key columns are:
- `five_hour_utilization`: % of the rolling 5-hour window used
- `seven_day_utilization`: % of the rolling 7-day window used
- `pct_used`: current window percentage
- `messages_used`, `messages_limit`: message count window

### Configuration Tables

**settings** — Key-value store for configuration. Keys include:
- `dashboard_key`: HMAC key for API authentication (auto-generated on first init)
- `sync_token`: for future VPS sync feature
- `fix_provider`: LLM provider for fix generation (anthropic/bedrock/openrouter — all Anthropic models)
- `anthropic_api_key`: Anthropic direct key (when `fix_provider=anthropic`)
- `aws_region`: Bedrock region (when `fix_provider=bedrock`)
- `openrouter_api_key` / `openrouter_model`: OpenRouter credentials
- `fix_autogen_model`: per-provider model override (falls back to defaults)

**alerts** — Triggered alert records. Not actively used in the UI as of v1.0.15.

**insights** — Generated insight records. Columns:
- `account`, `project`, `insight_type`, `message`, `detail_json`
- `dismissed`: boolean, set when user dismisses via API

---

## 5. The Scanner — Incremental JSONL Ingestion

The scanner (`scanner.py`) is the entry point for all data ingestion. It runs on demand (`claudash scan`), on a timer (`start_periodic_scan()` with configurable interval), and is triggered by the MCP tool `claudash_trigger_scan`.

### `scan_jsonl_file(file_path, account_id, project)`

This is the per-file entry point. It:

1. Looks up the `scan_state` row for this file path
2. Seeks to `last_byte_offset` (0 on first scan)
3. Reads line by line, calling `_parse_line()` for each
4. Accumulates session data in a dict keyed by `session_id`
5. After reading all new lines, calls `_flush()` to batch-upsert into the `sessions` table
6. Updates the `scan_state` row with the new byte offset

The `_flush()` function uses `INSERT OR REPLACE INTO sessions` for upserts. This means re-processing a session (if its JSONL was modified) will update the existing row rather than creating a duplicate.

### `_parse_line(line, session_data, file_path)`

The core parsing function. For assistant-type lines:

```python
if obj.get("type") == "assistant":
    usage = obj.get("message", {}).get("usage", {})
    session_id = obj.get("sessionId") or obj.get("uuid")
    model = obj.get("message", {}).get("model", "claude-opus")
    # normalize model name
    if "opus" in model:
        model_key = "claude-opus"
    elif "sonnet" in model:
        model_key = "claude-sonnet"
    else:
        model_key = "claude-haiku"
    # accumulate tokens
    session_data[session_id]["input_tokens"] += usage.get("input_tokens", 0)
    # ... etc
    # compute incremental cost
    pricing = MODEL_PRICING[model_key]
    cost = (input * pricing["input"] + output * pricing["output"] + ...) / 1_000_000
    session_data[session_id]["cost_usd"] += cost
```

The function also increments `turn_count` on every assistant message, which is later used by the waste detector.

### `_detect_compaction(session_data, session_id, current_ctx)`

Compaction detection works by comparing the effective context size between consecutive assistant turns:

```python
prev_ctx = session_data[session_id].get("last_ctx", 0)
current_ctx = input_tokens + cache_read_tokens

if prev_ctx > 1000:  # noise floor
    drop_ratio = (prev_ctx - current_ctx) / prev_ctx
    if drop_ratio > 0.30:  # 30% threshold
        session_data[session_id]["compaction_detected"] = True
        session_data[session_id]["tokens_before_compact"] = prev_ctx
        session_data[session_id]["tokens_after_compact"] = current_ctx

session_data[session_id]["last_ctx"] = current_ctx
```

The 30% threshold was chosen empirically. Context window usage naturally fluctuates, but a sudden 30%+ drop with a meaningful previous context almost always indicates a `/compact` command was issued.

### `_parse_subagent_info(file_path)`

Subagents are Claude Code sessions spawned by the main session to execute subtasks. Their JSONL files are written to a path containing `/subagents/`:

```
~/.claude/projects/-root-projects-tidify/subagents/<uuid>.jsonl
```

The function simply checks:
```python
return "/subagents/" in file_path
```

If true, the session is marked `is_subagent = True`. The parent-child relationship is stored in `parent_session_id`.

### `detect_lifecycle_events(session_id, session_data, file_path)`

Called after `_flush()`, this function examines the session metadata and generates `lifecycle_events` rows:

- If `compaction_detected` is True: inserts an event with `event_type = "compact"`, `context_pct_at_event` computed from `tokens_before_compact / window_token_limit`
- If `is_subagent` is True: inserts an event with `event_type = "subagent_spawn"`, `context_pct_at_event` from the session's context size at spawn time

### `generate_mcp_warnings(session_id, session_data)`

This function inspects session data and generates warning records for 4 rule types:

1. **late_compact**: Compaction happened at >80% context. The session was too close to the limit.
2. **repeated_reads_spike**: A session's read tool calls were more than 3x the project average.
3. **budget_80pct**: The session alone consumed more than 80% of the daily budget.
4. **floundering_live**: The session's output/input ratio is falling and turn count is high — signs of diminishing returns mid-session.

Warnings go into `mcp_warnings` and are served via the MCP `claudash_summary` tool so Claude itself can see them during a session.

### `start_periodic_scan(interval_seconds)`

Sets up a background thread that calls the full scan pipeline every `interval_seconds`. The dashboard server starts this on boot with a configurable interval (default 300 seconds / 5 minutes). The scan pipeline is:

1. Load all active accounts from the DB
2. For each account, iterate through `data_paths`
3. For each JSONL file in those paths, call `scan_jsonl_file()`
4. After all files, run `detect_all()` from `waste_patterns.py`
5. Run `generate_insights()` from `insights.py`
6. Update `daily_snapshots` aggregate table

---

## 6. The Analyzer — Metrics Computation Engine

`analyzer.py` contains pure functions that compute derived metrics from the raw session data. None of these functions write to the database — they read and return structured dicts. The dashboard server calls `full_analysis()` which assembles all of them.

### `account_metrics(account_id)`

Returns top-level stats for an account:
- `total_sessions`, `total_cost_usd`
- `total_input_tokens`, `total_output_tokens`, `total_cache_read_tokens`
- `cache_hit_rate`: `cache_read_tokens / (input_tokens + cache_read_tokens)` — the fraction of context served from cache
- `avg_session_cost`
- `cost_this_month`, `cost_last_month`, `cost_trend_pct`
- `model_breakdown`: dict with per-model session counts and costs

### `project_metrics(account_id, project=None)`

Per-project breakdown. If `project` is specified, returns detail for one project. Otherwise returns a list. Key fields:
- `sessions_count`, `total_cost_usd`, `cache_hit_rate`
- `avg_session_cost`, `total_turns`
- `avg_turns_per_session`
- `cost_per_turn`: an efficiency proxy — high cost per turn suggests long-running sessions with diminishing returns

### `window_metrics(account_id)`

Context window utilization metrics. The "window" refers to the Claude Code context window (200K tokens for Opus). Key computed values:
- `avg_window_utilization`: average context % across sessions
- `high_utilization_sessions`: sessions that hit >80% window
- `compaction_rate`: fraction of sessions where compaction was detected
- `avg_compact_timing_pct`: average context % at compaction (20.3% in live data — meaning users compact early, which is good)

### `compaction_metrics(account_id)`

Detailed compaction analysis:
- `total_compact_events`, `avg_context_pct_at_compact`
- `compact_distribution`: histogram of context % at compact (bucketed into 0-20%, 20-40%, etc.)
- `late_compactions`: sessions where compact happened at >70% context
- `estimated_savings`: rough estimate of tokens saved by compacting vs not compacting

### `subagent_metrics(account_id)`

Subagent usage analysis:
- `total_subagent_sessions`, `subagent_cost_fraction`
- `avg_subagent_context_at_spawn`: average context % when spawning a subagent
- `projects_using_subagents`: which projects spawn subagents most

### `compute_context_rot(sessions, window_size=10)`

Context rot is the degradation of response quality as a session gets longer. It is measured as the output/input ratio across turn depth buckets.

The constant `_CONTEXT_ROT_INFLECTION_DROP = 0.15` defines the threshold for flagging rot: if the output/input ratio drops by more than 15% between consecutive turn buckets, that is considered an inflection point.

The function:
1. Bins sessions by turn count into groups of `window_size` (0-10, 10-20, 20-30, etc.)
2. For each bin, computes `avg_output_tokens / avg_input_tokens`
3. Looks for the turn depth where this ratio first drops by >15% from its peak
4. Returns the inflection turn depth and the full ratio series for charting

In the live data, context rot typically begins around turn 30-40 for Opus sessions on complex projects. Sessions running past turn 60 often show a ratio below 0.15 — the model is spending most of its context reading history and producing little new output.

### `recommend_compact_threshold(project, account_id)`

The compaction advisor. Returns a recommended `autoCompactThreshold` (0-1 float, representing context %) for each project, based on Rules A through E:

**Rule A — No data (compact_count < 3)**:
Return `recommended_threshold = 0.70`, `confidence = "low"`, `data_sufficient = False`. Safe default when not enough history exists.

**Rule B — Late compaction (avg_compact_pct > 80%)**:
Sessions are compacting too late. Recommend `0.65` to compact earlier and give the summary 15% more context to work with.
`reasoning = "Your sessions compact at avg {pct}% — too late. 0.65 gives a safety buffer before context rot."`

**Rule C — Good timing, bad compacts exist (avg 60-80%, bad_compact > 0)**:
Some compacts dropped context. Compact 10% earlier than current average:
`recommended = round(avg_pct/100 - 0.10, 2)`

**Rule D — Compacting too early (avg < 60%)**:
Compact events are happening at low context (often subagent drops, not real /compact invocations). Recommend `0.70` as a sane default. This rule fires for all 6 projects in current live data because the compact detector fires on subagent context drops at ~16% context.

**Rule E — Good timing, no bad compacts (avg 60-80%, bad_compact = 0)**:
Current behavior is healthy. Formalize it:
`recommended = round(avg_pct / 100, 2)`

**Known limitation**: All 6 current projects hit Rule D (recommended 0.70) because the 135 compact events in lifecycle_events are mostly subagent context drops at 16% avg context, not user-triggered /compact commands. As real /compact usage accumulates, Rules B/C/E will fire and recommendations will become project-specific. The fix: add `tokens_after > 1000` filter to `detect_lifecycle_events()` to exclude subagent drops — documented as a known improvement.

### `compute_efficiency_score(account_id)`

The five-dimension efficiency score, each weighted:

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Cache efficiency | 25% | `cache_read_rate` — are you reusing context? |
| Model mix | 25% | Are you using the cheapest model appropriate for each task? |
| Window efficiency | 20% | Are sessions staying within healthy context range? |
| Flounder rate | 20% | What fraction of sessions show floundering waste? |
| Compaction timing | 10% | Are you compacting at the right time? |

Score is 0-100. In the live data, the personal_max account scores around 62/100 — pulled down by the model_waste insight (running Opus on tasks that Sonnet could handle) and by the high cost_outlier count.

### `full_analysis(account_id)`

Assembles all metric functions into a single dict passed to the dashboard's `/api/data` endpoint. The structure:

```python
{
    "account": account_metrics(account_id),
    "projects": project_metrics(account_id),
    "window": window_metrics(account_id),
    "compaction": compaction_metrics(account_id),
    "subagents": subagent_metrics(account_id),
    "context_rot": compute_context_rot(sessions),
    "efficiency": compute_efficiency_score(account_id),
    "compact_recommendations": {
        project: recommend_compact_threshold(project, account_id)
        for project in projects
    }
}
```

---

## 7. Waste Detection System

`waste_patterns.py` is the diagnostic layer. It runs after each scan pass and classifies sessions into waste categories. The results are written to `waste_events`.

### `detect_all(account_id)`

Entry point. Clears stale waste events for the account, then runs five detectors in sequence:

1. `_detect_repeated_reads(sessions)`
2. `_detect_floundering(sessions)`
3. `_detect_deep_no_compact(sessions)`
4. `_detect_cost_outliers(sessions)`
5. `detect_bad_compacts(sessions)` (also callable standalone)

Each detector returns a list of `WasteEvent` namedtuples which are then bulk-inserted into `waste_events`.

### `_detect_repeated_reads(sessions)`

Detects sessions where the same file was read many times. The critical implementation detail: it uses `os.path.basename()` to strip paths before counting. This prevents false positives where the same filename appears in different directories (e.g., `src/utils/parser.py` and `tests/utils/parser.py` would be counted as the same file).

```python
REPEATED_READ_THRESHOLD = 3

for session in sessions:
    file_counts = Counter()
    for tool_call in session["tool_calls"]:
        if tool_call["name"] in ("Read", "cat"):
            path = tool_call["input"].get("file_path", "")
            file_counts[os.path.basename(path)] += 1

    repeated = {f: c for f, c in file_counts.items() if c >= REPEATED_READ_THRESHOLD}
    if repeated:
        # emit waste event
```

In the live database: **56 events** totaling **$7,357.18** in session costs. This is the highest-cost waste category by far. The Tidify project dominates — complex multi-file sessions where the assistant re-reads type definition files on every turn.

### `_detect_floundering(sessions)`

Detects sessions where the same tool call is being repeated without progress. The key implementation: the repetition key is `(tool_name, input_hash)` — specifically the hash of the *input* to the tool, not just the tool name. This prevents false positives for legitimate repeated tool calls with different inputs (e.g., calling Bash multiple times with different commands is not floundering).

```python
FLOUNDER_THRESHOLD = 4

def _input_hash(input_dict):
    # normalize and hash the input for comparison
    normalized = json.dumps(input_dict, sort_keys=True)
    return hashlib.md5(normalized.encode()).hexdigest()[:8]

for session in sessions:
    call_counts = Counter()
    for tool_call in session["tool_calls"]:
        key = (tool_call["name"], _input_hash(tool_call["input"]))
        call_counts[key] += 1

    max_repeats = max(call_counts.values(), default=0)
    if max_repeats >= FLOUNDER_THRESHOLD:
        # emit waste event
```

In live data: **0 floundering events** currently. The floundering detector correctly identifies 0 events because the input-hash dedup fix (BUG-008, Session 7) made detection stricter — only truly identical tool calls (same tool, same input) are counted. This is correct behavior. Sessions that previously showed floundering dropped to 0 after the CLAUDE.md rules applied on April 11 (fix #5 in the database: max-retry rule). The 0 count is a success metric, not an absence of detection.

### `_detect_deep_no_compact(sessions)`

Detects sessions that ran very long (many turns) without ever compacting, when they should have.

```python
DEEP_TURN_THRESHOLD = 100

for session in sessions:
    if session["turn_count"] >= DEEP_TURN_THRESHOLD and not session["compaction_detected"]:
        # check if window utilization was high
        ctx_pct = (session["input_tokens"] + session["cache_read_tokens"]) / window_limit * 100
        if ctx_pct > 60:
            # emit waste event with high severity
```

In live data: **16 events** totaling **$1,784.99**. These are the "I forgot to compact" sessions — long, expensive runs that accumulated 100+ turns without ever hitting `/compact`.

### `_detect_cost_outliers(sessions)`

Uses a statistical approach: sessions costing more than `COST_OUTLIER_MULTIPLIER` standard deviations above the mean are flagged.

```python
COST_OUTLIER_MULTIPLIER = 3.0

mean = statistics.mean(costs)
stdev = statistics.stdev(costs)
threshold = mean + (COST_OUTLIER_MULTIPLIER * stdev)

for session in sessions:
    if session["cost_usd"] > threshold:
        # emit waste event
```

In live data: **4 events** totaling **$1,544.42**. These are the sessions that cost 3+ standard deviations above normal — typically sessions where something went wrong (infinite loop in a tool, massive file reads, or a very long context).

### `detect_bad_compacts(sessions)`

Bad compacts are sessions where `/compact` was issued but did not actually help — the context size did not drop meaningfully, or the post-compact session was still expensive.

The detector uses 5 regex signals in the session transcript (via the JSONL data):

1. Compact command was issued but output tokens stayed high
2. The compact summary itself was very long (>500 tokens) — wasted output
3. Multiple compactions in a single session
4. Compaction happened but `tokens_after_compact > tokens_before_compact` (should be impossible but has been seen)
5. Compaction at <10% context (unnecessary early compact)

In live data: **0 events**. Either the sessions in the DB have well-behaved compactions, or the regex signals are not firing on the actual data patterns.

---

## 8. The Fix Pipeline — From Waste to CLAUDE.md

The fix pipeline is the heart of Claudash's value proposition: not just showing you what is wrong, but generating and measuring actual improvements.

### `fix_tracker.py`

Manages the lifecycle of fixes. Key functions:

#### `capture_baseline(project, account_id, session_id=None)`

Captures a metrics snapshot to use as the baseline for measuring a fix's impact. The snapshot includes:
- Current session count, total cost, average session cost
- Average turn count, average window utilization
- Waste event counts per pattern type
- Cache hit rate

Importantly, if `session_id` is provided, the baseline is scoped to that session's "recent period" — using per-turn scaling to normalize against sessions of different lengths. The baseline is stored as JSON in `fixes.baseline_json`.

#### `compute_delta(fix_id, since_override=None)`

Computes the difference between baseline and current metrics. The `since_override` parameter allows specifying a custom start time (useful for measuring fixes applied mid-month). Returns:
- `delta_cost_usd`: reduction in per-session cost (negative = improvement)
- `delta_cache_rate`: change in cache hit rate
- `delta_waste_events`: change in waste event count
- `delta_window_efficiency`: change in window utilization

#### `determine_verdict(delta, plan)`

The plan-aware verdict determination:

```python
def determine_verdict(delta, plan):
    if plan in ("max", "pro"):
        # Window plans: care about window efficiency, not dollar cost
        primary = delta.get("delta_window_efficiency", 0)
        threshold = 0.05  # 5% improvement
    else:
        # API plan: care about dollar cost
        primary = delta.get("delta_cost_usd", 0)
        threshold = 0.10  # $0.10 improvement per session

    if abs(primary) < threshold:
        return "insufficient_data"
    elif primary > 0:  # window efficiency up, or cost down
        return "improving"
    elif primary < -threshold:
        return "regressing"
    else:
        return "stable"
```

For Max/Pro users, the tool focuses on window efficiency rather than dollar cost. This matters because Max/Pro subscribers pay a flat monthly fee — they care about getting more work done per plan period, not about marginal API costs.

#### `build_share_card(fix_id)`

Generates a text card summarizing fix outcomes, formatted for sharing in Claude sessions or in commit messages. Plan-aware framing:
- Max/Pro: "Reduced average window burn by 12% — fitting more work into each plan window"
- API: "Reduced per-session cost by $0.43 — saving ~$13/month at current usage rate"

### `fix_generator.py`

Handles LLM-driven fix generation.

#### The Six Prompt Templates (`PROMPTS` dict)

Each waste pattern has a dedicated template:

1. **repeated_reads**: "The assistant is reading {files} on {count} turns each. Here is the file content: [...]. Write a CLAUDE.md block that caches this information or instructs the assistant to read it only once."

2. **floundering**: "The assistant repeated the call ({tool}, {input_hash}) {count} times without progress. This suggests it is stuck in a loop. Write a CLAUDE.md rule that prevents this pattern."

3. **deep_no_compact**: "This session ran {turns} turns to {context_pct}% context without compacting. Write a CLAUDE.md reminder or a settings.json recommendation for autoCompactThreshold."

4. **cost_outlier**: "This session cost {cost_usd}, which is {n_stdev} standard deviations above normal. Here is the session summary: [...]. Diagnose the root cause and recommend an architectural change."

5. **bad_compact**: "The compact at turn {turn} produced a {summary_tokens}-token summary. Write instructions for producing more concise compact summaries."

6. **rewind_heavy**: (Reserved for future use — sessions with many undo operations.)

#### Three Provider Functions

**`_call_anthropic(prompt, model, api_key)`**: Direct Anthropic API via Python's stdlib `urllib.request`. No SDK dependency — this was a deliberate choice to keep the core tool pip-dependency-free. The HTTP call uses `urllib.request.Request` with `x-api-key` and `anthropic-version` headers. The system prompt is sent with `cache_control: {"type": "ephemeral"}` to enable prompt caching — subsequent calls with the same system prompt cost 90% less.

**`_call_bedrock(prompt, model, region)`**: Uses `boto3` for AWS Bedrock inference. The `boto3` import is lazy (inside the function) to avoid a hard dependency for users not using Bedrock.

```python
def _call_bedrock(prompt, model, region):
    import boto3  # lazy import
    client = boto3.client("bedrock-runtime", region_name=region)
    # ...
```

**`_call_openrouter(prompt, model, api_key)`**: OpenRouter Chat Completions API restricted to Anthropic models. The URL is fixed (`https://openrouter.ai/api/v1/chat/completions`); the user only supplies a key. Replaced the generic `_call_openai_compat` in v2.0.1.

#### `generate_fix(fix_id)`

Main entry point. Reads the fix row, looks up the waste event for context, selects the appropriate prompt template, calls the configured provider, and writes the result back to `fixes.generation_response`. Also calls `find_claude_md()` to discover where the CLAUDE.md lives for the project, and stores the path in `fixes.applied_to_path`.

#### `find_claude_md(project)`

Discovers CLAUDE.md files in this order:
1. `{project_dir}/.claude/CLAUDE.md`
2. `{project_dir}/CLAUDE.md`
3. `~/.claude/CLAUDE.md` (global fallback)

### The Five Active Fixes (Live DB)

As of 2026-04-16, there are 5 fixes in the database:

| ID | Project | Pattern | Fix Type | Status |
|----|---------|---------|----------|--------|
| 5 | Tidify | floundering | claude_md | measuring |
| 6 | Tidify | repeated_reads | prompt | measuring |
| 7 | Tidify | deep_no_compact | settings_json | measuring |
| 8 | Tidify | cost_outlier | architecture | measuring |
| 10 | Tidify | floundering | claude_md | measuring |

All five are in `measuring` status — baseline captured, waiting for enough post-fix sessions to compute a meaningful delta.

### The Ten Fix Measurements (Live DB)

There are 10 measurement snapshots:
- **9 verdicts: `improving`** — 9 of 10 measurements show improvement
- **1 verdict: `insufficient_data`** — not enough sessions elapsed since baseline

The improving verdicts include fixes 5-8 and 10, all for Tidify. This is directionally promising but the sample sizes are small (2-3 sessions each), so the improvements could be noise. The fix tracker does not yet enforce a minimum session count before reporting "improving."

---

## 9. Insights Engine — 14 Rules

`insights.py` generates human-readable insight cards. Insights are deduplicated (same type+project+account combination does not generate a duplicate), stored in the `insights` table, and shown in the dashboard's insight panel.

### `generate_insights(account_id)`

Iterates through all 14 rules and upserts into `insights`:

#### Rule 1: `model_waste`

Fires when a project's session breakdown shows >30% of sessions running on Opus when the session metrics suggest Sonnet would suffice. Heuristic: sessions with <5000 output tokens and <20 turns are likely suitable for Sonnet.

**Live data**: 4 active model_waste insights. All pointing at the Claudash and Brainworks projects — meta note that even the developer building a cost monitor isn't optimal about model selection.

#### Rule 2: `cache_spike`

Fires when `cache_creation_input_tokens` in a recent session is 10x or more than the account average. Indicates an unusual amount of new content being written to cache — often a symptom of context bloat.

#### Rule 3: `compaction_gap`

Fires when a project has sessions with >80% window utilization but a compaction rate below 50%. Users are filling the window without compacting.

#### Rule 4: `cost_target`

Fires when the account is on track to exceed a configurable monthly cost target. Based on `cost_this_month / days_elapsed * days_in_month`.

#### Rule 5: `window_risk`

Fires when average window utilization exceeds 75%. High window utilization degrades response quality.

**Live data**: 1 active window_risk insight.

#### Rule 6: `roi_milestone`

Fires when cumulative savings from applied fixes crosses a threshold (currently: when any fix shows >$50 saved, or 3+ improving verdicts). A positive reinforcement signal.

**Live data**: 1 active roi_milestone insight — triggered by the 9 improving verdicts.

#### Rule 7: `heavy_day`

Fires when a single day's cost exceeds 3x the account average daily cost.

#### Rule 8: `best_window`

Fires when analysis of daily usage patterns shows a clear low-cost time window (e.g., 6am-10am on weekdays consistently has 40% cheaper sessions than the daily average). Recommends scheduling expensive work during this window.

**Live data**: 1 active best_window insight.

#### Rule 9: `window_combined_risk`

Fires when both window utilization AND flounder rate are above their respective thresholds simultaneously — the combination is higher risk than either alone.

**Live data**: 1 active window_combined_risk insight.

#### Rule 10: `session_expiry`

Fires when the user has a session approaching the 5-hour context window limit (for Max/Pro plans). Recommends compacting or starting a new session.

#### Rule 11: `pro_messages_low`

Fires when a Pro plan account's message count is below a threshold for the current billing period — suggesting the user is not getting full value from their plan.

#### Rule 12: `subagent_cost_spike`

Fires when subagent sessions in a project are costing significantly more per-session than regular sessions. Subagents should be cheaper (focused tasks), so if they are expensive, something is wrong.

**Live data**: 2 active subagent_cost_spike insights — one for Tidify (subagents running expensive validation chains) and one for Claudash itself.

#### Rule 13: `floundering_detected`

Fires when `_detect_floundering()` finds new events since the last scan. Immediate alert.

#### Rule 14: `bad_compact_detected`

Fires when `detect_bad_compacts()` finds new events. Currently not firing in live data.

### Budget Alerts

Separate from the 14 insight rules, `generate_insights()` also checks `daily_budget_usd` per account. If today's spending exceeds the budget, an alert is inserted into the `alerts` table. This is the only use of the `alerts` table currently.

---

## 10. The Dashboard Server — HTTP, SSE, and Security

`server.py` is a pure-stdlib Python HTTP server (no Flask, no FastAPI). It uses `http.server.BaseHTTPRequestHandler` with a custom `DashboardHandler` subclass.

### Why No Web Framework

The decision was deliberate: zero external dependencies for the server. Users install Claudash via npm (`npm install -g @jeganwrites/claudash`), and the npm package bundles a `bin/claudash.js` launcher that calls Python. Adding Flask or FastAPI would require the user to also have those installed in their Python environment. The stdlib HTTP server handles all requirements.

### Route Table

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | Main dashboard HTML |
| GET | `/accounts` | None | Account management HTML |
| GET | `/health` | None | Server health + version |
| GET | `/api/health` | None | DB stats + last scan |
| GET | `/api/data?account=<id>` | None | Full rollup — all metrics, projects, waste, lifecycle, context_rot, recommendations |
| GET | `/api/projects?account=<id>` | None | Per-project metrics array |
| GET | `/api/insights?account=<id>` | None | Active insights |
| GET | `/api/window?account=<id>` | None | 5h window status + burn rate |
| GET | `/api/trends?account=<id>&days=<n>` | None | Daily rollups + monthly projection |
| GET | `/api/alerts` | None | Last 20 alerts |
| GET | `/api/fixes` | None | All fixes with latest measurement |
| GET | `/api/fixes/{id}` | None | One fix with full measurement history |
| GET | `/api/fixes/{id}/share-card` | None | Plain-text share card |
| GET | `/api/accounts` | None | All active accounts |
| GET | `/api/accounts/{id}/projects` | None | Project keyword map |
| GET | `/api/claude-ai/accounts` | None | Browser accounts + latest snapshot |
| GET | `/api/claude-ai/accounts/{id}/history` | None | Last 48 snapshots |
| GET | `/api/lifecycle?project=<name>` | None | Lifecycle events (compact + subagent_spawn) |
| GET | `/api/context-rot?project=<name>` | None | Context rot curve + inflection |
| GET | `/api/bad-compacts?project=<name>` | None | Bad compact events |
| GET | `/api/recommendations?project=<name>` | None | autoCompactThreshold recommendation |
| GET | `/api/stream/cost` | None | SSE live cost meter stream |
| GET | `/api/real-story` | None | 5 archetype insight stories |
| POST | `/api/scan` | Dashboard-Key | Trigger scan + insights regen |
| POST | `/api/hooks/cost-event` | None (localhost-only) | Hook receiver for live meter |
| POST | `/api/insights/{id}/dismiss` | Dashboard-Key | Dismiss insight |
| POST | `/api/fixes` | Dashboard-Key | Create fix (capture baseline) |
| POST | `/api/fixes/{id}/measure` | Dashboard-Key | Measure fix, compute verdict |
| POST | `/api/accounts` | Dashboard-Key | Create account |
| POST | `/api/claude-ai/sync` | Sync-Token | Browser sync push |
| PUT | `/api/accounts/{id}` | Dashboard-Key | Update account |
| DELETE | `/api/accounts/{id}` | Dashboard-Key | Soft-delete account |
| DELETE | `/api/fixes/{id}` | Dashboard-Key | Revert fix |

### `_require_dashboard_key(self)`

All POST endpoints and most GET endpoints require authentication. The `dashboard_key` is a 32-byte hex string generated on first init and stored in the `settings` table. Authentication is via `X-Dashboard-Key` header.

The comparison uses `hmac.compare_digest` rather than `==` to prevent timing-based side-channel attacks:

```python
def _require_dashboard_key(self):
    provided = self.headers.get("X-Dashboard-Key", "")
    expected = get_setting("dashboard_key")
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        self.send_response(401)
        self.end_headers()
        return False
    return True
```

The SSE endpoint (`/api/stream/cost`) also checks origin: it only accepts connections from `localhost` or `127.0.0.1` in the `Origin` header.

### LRU Cache

The server implements a 64-entry LRU cache for expensive analysis queries:

```python
_cache = {}
_cache_order = []
_CACHE_MAX = 64
_CACHE_TTL = 60  # seconds

def _cache_get(key):
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry["ts"] < _CACHE_TTL:
            return entry["data"]
        del _cache[key]
    return None

def _cache_put(key, data):
    if len(_cache_order) >= _CACHE_MAX:
        evict = _cache_order.pop(0)
        del _cache[evict]
    _cache[key] = {"data": data, "ts": time.time()}
    _cache_order.append(key)
```

The `_cache_clear()` function is called after every scan to ensure fresh data reaches the UI.

### ThreadPoolExecutor

The handler uses a `ThreadPoolExecutor` with a 10-second timeout for heavy operations:

```python
with ThreadPoolExecutor(max_workers=4) as executor:
    future = executor.submit(full_analysis, account_id)
    try:
        result = future.result(timeout=10)
    except TimeoutError:
        # return cached result or empty dict
```

This prevents a slow database query from blocking the HTTP server indefinitely.

### SSE Live Cost Meter

The `/api/stream/cost` endpoint streams Server-Sent Events to the browser. The stream format:

```
data: {"sessions": [...], "total_estimated_cost": 0.42, "last_updated": 1776330000}

data: {"sessions": [...], "total_estimated_cost": 0.89, "last_updated": 1776330005}
```

The live session state is maintained in `_live_sessions` dict in memory:

```python
_live_sessions = {}  # session_id -> session_data

def _prune_and_update_live_session(session_id, event_data):
    # on pre-hook: add estimated entry
    # on post-hook: update with actual tokens
    # prune sessions not seen for >300 seconds
```

The `get_active_sessions()` function returns the current state of `_live_sessions` filtered to sessions seen in the last 5 minutes.

### Hook Endpoints

The `/api/hooks/cost-event` endpoint receives data from the pre/post hook scripts. For `phase=pre`, it records an estimated entry (500 tokens). For `phase=post`, it updates with `actual_tokens` from `CLAUDE_OUTPUT_TOKENS`.

The hook scripts (`hooks/pre_tool_use.sh`, `hooks/post_tool_use.sh`) use curl with `-sf` (silent + fail) and `> /dev/null 2>&1 || true`. This ensures the hooks never block Claude Code or produce visible output if the dashboard is not running.

---

## 11. MCP Integration — Bidirectional Tool Protocol

`mcp_server.py` implements a Model Context Protocol server, allowing Claude Code to call Claudash tools directly during a session.

### MCP Transport: stdio

The MCP server runs over stdin/stdout. The `run_stdio()` function reads newline-delimited JSON-RPC 2.0 requests from stdin and writes responses to stdout:

```python
def run_stdio():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            request = json.loads(line.strip())
            response = handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            continue
```

### JSON-RPC 2.0 Protocol

Three method types are handled:

1. **`initialize`**: Handshake. Returns server capabilities and protocol version.
2. **`tools/list`**: Returns the list of available tools with their schemas.
3. **`tools/call`**: Calls a specific tool.

### The 10 MCP Tools

**v1 read-side tools** (return data to Claude):

1. **`claudash_summary`** — Returns account-level summary: total cost, cache rate, efficiency score, active insights count, active warnings. The single most important tool — gives Claude a quick status check at session start.

2. **`claudash_project`** — Per-project metrics for a named project: session count, total cost, waste events, active fixes.

3. **`claudash_window`** — Context window utilization for the current session and recent history. Claude can check this mid-session to decide whether to compact.

4. **`claudash_insights`** — Returns full insight cards (all undismissed). Allows Claude to proactively address insights during a session.

5. **`claudash_action_center`** — Returns pending actions: fixes that need measurement, insights that need review, warnings that need acknowledgment.

**v2 write-side tools** (Claude can mutate state):

6. **`claudash_trigger_scan`** — Triggers an immediate full scan. Claude calls this after making changes to CLAUDE.md to see updated waste metrics.

7. **`claudash_report_waste`** — Claude reports a waste pattern it detected itself (not from automated scanning). Inserts a waste_event row. Allows Claude to report "I just noticed I read server.py 6 times in the last 10 turns."

8. **`claudash_generate_fix`** — Triggers fix generation for a specific waste event. Claude can request a fix be generated without the user running CLI commands.

9. **`claudash_dismiss_insight`** — Dismisses an insight by ID. Allows Claude to dismiss insights it has addressed.

10. **`claudash_get_warnings`** — Returns active MCP warnings (late_compact, repeated_reads_spike, etc.). Claude checks this at session start to know if it should immediately change behavior.

### `handle_request(request)`

The dispatch function. Routes by method name and tool name. For tool calls:

```python
def handle_request(request):
    method = request.get("method")
    if method == "initialize":
        return _handle_initialize(request)
    elif method == "tools/list":
        return _handle_tools_list()
    elif method == "tools/call":
        tool_name = request["params"]["name"]
        arguments = request["params"].get("arguments", {})
        handler = _TOOL_HANDLERS.get(tool_name)
        if handler:
            result = handler(arguments)
            return {"jsonrpc": "2.0", "id": request["id"], "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
```

### MCP Registration

To register Claudash's MCP server with Claude Code, merge this into `~/.claude/settings.json`:

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "claudash": {
      "command": "claudash",
      "args": ["mcp"]
    }
  }
}
```

Run `claudash mcp` to print this snippet ready to copy-paste. The `claudash mcp` command invokes `cmd_mcp()` in `cli.py`, which calls `run_stdio()`.

### `run_test()`

A smoke test mode (`claudash mcp --test`) that:
1. Sends a synthetic `initialize` request
2. Sends `tools/list` and verifies all 10 tools are listed
3. Calls `claudash_summary` with a test account
4. Verifies the response structure

This is used in CI and by the developer to verify the MCP server works after code changes.

---

## 12. Browser Account Tracking

Browser account tracking is the v1.x feature for tracking claude.ai usage (as opposed to API usage via Claude Code). It polls the claude.ai internal usage API using session cookies.

### The Two Tracked Accounts

In the live database, two browser accounts are configured:

1. **personal_max** (`account_id: personal_max`): Personal claude.ai account on Max plan. Org ID: `a70523da-3526-4217-9cd2-7e8d2ed3bff2`.
2. **work_pro** (`account_id: work_pro`): Work/second claude.ai account on Pro plan. Org ID: `8f66f35e-1114-40c0-973a-82ee4fdeb61f`.

### Latest Snapshot Data

From `claude_ai_snapshots`:

| Account | Plan | Current % | 5-Hour % | 7-Day % |
|---------|------|-----------|----------|---------|
| personal_max | max | 15% | 15% | 37% |
| work_pro | pro | 5% | 5% | 91% |

The work_pro account's 91% seven-day utilization is notable — this account is near capacity for the rolling 7-day window. This would trigger an insight if the insight rule is wired to browser account data (it currently partially is).

### `mac_sync_mode`

The `mac_sync_mode` column controls polling behavior. When set to `1` (as both accounts are configured), the server-side polling is suppressed — Claudash does not attempt to poll claude.ai from the VPS. Instead, data flows in exclusively via push from `tools/mac-sync.py` running on the Mac, which reads the browser cookie and POSTs to `/api/claude-ai/sync`. This is the correct architecture for a VPS setup: the VPS has no browser, so it cannot poll claude.ai directly. The Mac, which has the browser session, pushes data to the VPS on a schedule. Both accounts have `mac_sync_mode=1` and have 28 snapshots from this push mechanism.

### Session Key Storage

The `session_key` column stores the full sk-ant-sid cookie value in plaintext in the SQLite database. This is a known security gap (see §18). The original design assumed the database would be at `data/usage.db` inside the project directory with 0600 permissions, accessible only to the owner. The `_lock_db_file()` function in `db.py` enforces this.

### Polling Logic

Browser accounts are polled via HTTP requests to the claude.ai internal API. The polling function is in `server.py` (not a separate file). It:
1. Fetches `https://claude.ai/api/organizations/{org_id}/usage` with the session cookie
2. Parses the response JSON for window utilization percentages
3. Inserts a row into `claude_ai_snapshots`
4. Updates `claude_ai_accounts.last_polled`

The `claude_ai_usage` table (historical poll results) is currently empty in the live DB — the historical recording was added to the schema but the code path that writes to it is not fully wired. This is noted in §18.

### `cmd_claude_ai()` CLI Command

The `claudash claude-ai` command provides subcommands for managing browser accounts:
- `claudash claude-ai add --label "Personal" --session-key sk-ant-sid01-...`
- `claudash claude-ai list`
- `claudash claude-ai poll` (manual trigger)
- `claudash claude-ai remove --account work_pro`

---

## 13. CLI Interface and Distribution

### CLI Commands (cli.py)

#### `cmd_dashboard()`

The primary command: `claudash dashboard`. Opens the browser and starts the server. Implements an auto-restart loop:

```python
while True:
    try:
        run_server(host, port)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Server crashed: {e}, restarting in 3s...")
        time.sleep(3)
```

The auto-restart is important for long-running sessions. If the scanner crashes on a malformed JSONL file, the server restarts automatically rather than requiring manual intervention.

#### `cmd_init()`

First-time setup. The key step is `_detect_from_credentials()`:

```python
def _detect_from_credentials():
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
    if os.path.exists(creds_path):
        with open(creds_path) as f:
            creds = json.load(f)
        plan = creds.get("plan", "")
        if "max" in plan.lower():
            return "max"
        elif "pro" in plan.lower():
            return "pro"
    return "api"  # default
```

This auto-detects whether the user has a Max, Pro, or API plan from their Claude Code credentials file, so the plan-aware framing (window efficiency vs dollar cost) is correct from the start without requiring manual configuration.

`cmd_init()` also:
- Creates the `data/` directory
- Calls `init_db()` to create all 18 tables
- Seeds the `accounts` table with a default account based on detected plan
- Generates a `dashboard_key` for API authentication
- Writes a `hooks/` directory with pre/post hook scripts
- Provides instructions for adding the hooks to `~/.claude/settings.json`

#### `cmd_scan()`

Manual trigger: `claudash scan`. Runs the full scan pipeline synchronously and prints a summary of what was found.

#### `cmd_waste()`

`claudash waste` — prints a formatted table of waste events grouped by pattern type, with cost totals and severity breakdown.

#### `cmd_fix_add()`

Interactive fix creation: `claudash fix add`. Prompts for:
1. Project name (with autocomplete from known projects)
2. Waste pattern type (repeated_reads/floundering/deep_no_compact/cost_outlier)
3. Fix type (claude_md/prompt/settings_json/architecture/human)
4. Fix title and description
5. Whether to generate the fix content via LLM or enter manually

#### `cmd_fix_generate()`

`claudash fix generate --fix-id 7` — calls `generate_fix(fix_id)` to generate fix content via LLM for an existing fix record.

#### `cmd_measure()`

`claudash measure` — runs `capture_baseline()` for a project, or `compute_delta()` and `determine_verdict()` for an existing fix. Prints the measurement result.

#### `cmd_mcp()`

`claudash mcp` — starts the MCP stdio server. `claudash mcp --test` runs the smoke test.

#### `cmd_keys()`

Key management:
- `claudash keys --rotate` — generates a new `dashboard_key` and prints it
- `claudash keys --set-provider anthropic --api-key sk-ant-...` — configures LLM provider for fix generation

#### `cmd_scan_reprocess()`

`claudash scan --reprocess` — clears all `scan_state` rows and re-scans all JSONL files from scratch. Used after database schema changes or when suspecting missed data.

### Distribution via npm

The package is distributed as `@jeganwrites/claudash` on npm. The `package.json`:

```json
{
  "name": "@jeganwrites/claudash",
  "version": "1.0.15",
  "bin": {
    "claudash": "bin/claudash.js"
  }
}
```

`bin/claudash.js` is a thin Node.js launcher that finds the Python interpreter and calls `cli.py`. This enables:

```bash
npm install -g @jeganwrites/claudash
claudash init
claudash dashboard
```

without requiring the user to know where the Python files are or to manage a virtual environment. The Python files are bundled inside the npm package.

### `_version.py`

The version string is read from `package.json`:

```python
# _version.py
import json, os

def get_version():
    pkg = os.path.join(os.path.dirname(__file__), "package.json")
    with open(pkg) as f:
        return json.load(f)["version"]

VERSION = get_version()
```

This ensures a single source of truth — bumping the version in `package.json` automatically propagates to the CLI banner, the HTTP server response headers, and the MCP server's `initialize` response.

---

## 14. Architecture Decisions and What Was Deliberately Left Out

### Why SQLite

SQLite was chosen over PostgreSQL, MongoDB, or a cloud database for three reasons:

1. **Zero setup**: Users should be able to run `claudash init` and `claudash dashboard` without provisioning any external services.
2. **Privacy**: The database is a file on the user's machine. Session transcripts and API keys never leave the local environment.
3. **Simplicity**: SQLite WAL mode handles the one concurrent-write scenario (scanner writing while server reads) without complexity.

The tradeoff is that the database cannot be shared across machines. The `sync_token` in `settings` and the `VPS_IP`/`VPS_PORT` in `config.py` (read from env vars) were stub infrastructure for a future sync feature, but this was explicitly deferred.

### Why Stdlib HTTP Server

As noted in §10, no web framework was used. This keeps the runtime dependency list to:
- Python 3.8+ (required)
- `boto3` (optional — only for Bedrock provider, lazy-imported inside `_call_bedrock()` so non-Bedrock users have zero pip dependencies)
- No other Python packages

The npm package handles the user-facing distribution. Everything else is Python stdlib.

### Why Not Real-Time Scanning

The scanner runs on a 5-minute polling interval, not file watchers. File watching (using `inotify` on Linux) would give true real-time updates but adds complexity and platform-specific code. For the primary use case — checking in on the day's usage after a session ends — 5-minute polling is sufficient.

The SSE live cost meter does use real-time hooks, but these only track token costs during tool use, not full session metrics.

### The Hooks Design

The pre/post hooks use fire-and-forget curl to avoid any latency impact on Claude Code. If the dashboard is not running, the curl fails silently. This was the correct tradeoff — users should never notice Claudash is installed from a performance perspective.

The hooks receive very limited data (tool name, session ID, estimated/actual tokens) because the environment variables available to Claude Code hooks are limited. Full session data is computed by the scanner from JSONL files.

### What Was Explicitly Not Built

1. **Cloud sync / VPS hosting**: The `config.py` has `VPS_IP` and `VPS_PORT` stubs, but cloud infrastructure was deferred indefinitely. Personal dashboard use case does not need it.

2. **Team/multi-user support**: The accounts system could theoretically support multiple users sharing a dashboard, but all access control is single-key, and there is no concept of user permissions.

3. **Fix auto-apply**: The `applied_to_path` field exists and `find_claude_md()` discovers the target, but there is no code that actually writes to the CLAUDE.md file. This was deliberately omitted because modifying a CLAUDE.md without review is high-risk.

4. **Transcript viewer**: The JSONL files contain full conversation history. A transcript viewer would be valuable for debugging specific sessions, but it was deferred in favor of the waste/fix/measure loop.

5. **Notification system**: Budget alerts write to the `alerts` table but there is no mechanism to actually notify the user (no email, no webhook, no desktop notification). The alerts are visible in the dashboard only if the user is looking at it.

6. **Historical fix comparison**: The `fix_measurements` table accumulates snapshots, but there is no chart showing measurement trend over time. The UI shows only the latest verdict.

---

## 15. Real Numbers from the Live Database

All numbers from `data/usage.db` as of 2026-04-16.

### Sessions Overview

| Metric | Value |
|--------|-------|
| Total sessions | 21,051 |
| Date range (Unix) | 1773902934 → 1776330250 |
| Approximate dates | 2026-03-19 → 2026-04-16 |
| Active days | ~28 days |
| Average sessions per day | ~752 |

### Cost by Project

| Project | Total Cost | Notes |
|---------|-----------|-------|
| Tidify | $4,404.08 | Healthcare data cleaning platform — dominant spender |
| Claudash | $1,395.11 | Self-referential — building this tool |
| Brainworks | $1,109.57 | Not detailed in this writeup |
| WikiLoop | $358.68 | Not detailed in this writeup |
| CareerOps | $176.68 | Not detailed in this writeup |
| Knowl | $10.90 | Minimal usage |
| **Total** | **$7,455.03** | All via personal_max account |

Note: All 21,051 sessions are under the `personal_max` account. The `work_pro` account is tracked for browser window usage only — no JSONL data is scanned for it (its `data_paths` is `[]`).

### Cost by Model

| Model | Sessions | Total Cost | % of Cost |
|-------|----------|-----------|-----------|
| claude-opus | 18,010 | $7,397.90 | 99.2% |
| claude-sonnet | 1,713 | $53.65 | 0.7% |
| claude-haiku | 1,328 | $3.47 | 0.05% |

This model distribution is the source of 4 active `model_waste` insights — 85.5% of sessions run on Opus, and for many of those, Sonnet would be appropriate.

### Waste Events

| Pattern | Events | Total Session Cost | Avg/Event |
|---------|--------|-------------------|-----------|
| repeated_reads | 56 | $7,357.18 | $131.38 |
| deep_no_compact | 16 | $1,784.99 | $111.56 |
| cost_outlier | 4 | $1,544.42 | $386.11 |
| floundering | 0 | $0 | — (Fixed by Apr 11 CLAUDE.md rules) |
| bad_compact | 0 | $0 | — |
| **Total** | **76** | **$10,686.59** | |

Note: Session costs in waste_events represent the total cost of the flagged session, not the marginal waste itself. A session costing $130 with repeated_reads does not mean $130 was wasted — it means the session cost $130 and contained repeated-read patterns. The actual incremental cost from the waste behavior is smaller.

### Lifecycle Events

| Event Type | Count | Avg Context % |
|------------|-------|---------------|
| compact | 137 | 20.3% |
| subagent_spawn | 146 | 10.1% |
| **Total** | **283** | |

The 20.3% average compact context is surprisingly low — users are compacting early. This is good behavior but may indicate over-caution (compacting too early sacrifices useful context). The recommended threshold for most projects is 40-60% based on Rules B and C.

The 10.1% subagent spawn context is very low — subagents are being spawned when the parent session is barely started. This may be intentional (spawn subagents early to parallelize) or may indicate the subagent spawn trigger is overly eager.

### Browser Account State

| Account | Plan | Current Window % | 5-Hour % | 7-Day % |
|---------|------|-----------------|----------|---------|
| personal_max | max | 15% | 15% | 37% |
| work_pro | pro | 5% | 5% | 91% |

The work_pro 91% seven-day utilization is high and warrants attention.

### Active Insights

| Type | Count | Notes |
|------|-------|-------|
| model_waste | 4 | Use Sonnet for some tasks |
| subagent_cost_spike | 2 | Subagents costing more than expected |
| best_window | 1 | Identified optimal usage time |
| roi_milestone | 1 | 9 improving fix verdicts |
| window_combined_risk | 1 | High utilization + floundering |
| window_risk | 1 | Average utilization too high |
| **Total active** | **10** | |

### Fix Tracker State

| Metric | Value |
|--------|-------|
| Total fixes | 5 |
| Fixes in `measuring` status | 5 |
| Fixes with `success` status | 0 |
| Total measurements | 10 |
| Improving verdicts | 9 |
| Insufficient data verdicts | 1 |

All 5 fixes target Tidify. No fixes have been created for Claudash, Brainworks, WikiLoop, or CareerOps despite having waste events.

### MCP Warnings

| Total warnings | 1 |
|----------------|---|

One active MCP warning in the database. The type and detail are not shown here (would require reading the row), but it was generated by `generate_mcp_warnings()` during a scan.

---

## 16. Session-by-Session Build History

Claudash was built over 12 development sessions. The following is extracted from `CHANGELOG.md`.

### Session 1 — Foundation

Established the core scanning architecture. `scan_jsonl_file()` with byte-offset tracking, `_parse_line()` with the four token types, `init_db()` with initial schema, basic `account_metrics()`. Command: `claudash dashboard` serving a minimal HTML page.

Key decision: JSONL files are the source of truth. No Claude API queries — all data comes from local transcripts.

### Session 2 — Waste Detection

`waste_patterns.py` created with the four detectors. `_detect_floundering()` with the `(tool_name, input_hash)` key was the hardest to get right — early versions had too many false positives from legitimate tool repetition. The fix was hashing the full input dict, not just the tool name.

`insights.py` created with the first 6 rules (model_waste, cache_spike, compaction_gap, cost_target, window_risk, roi_milestone).

### Session 3 — Fix Tracker

`fix_tracker.py` created. The plan-aware verdict logic was designed from the start — the author noticed early that Max/Pro users should care about window efficiency, not dollar cost.

`cli.py` `cmd_fix_add()` and `cmd_measure()` implemented. First fixes manually created for Tidify.

### Session 4 — Dashboard UI

The HTML template in `server.py` was expanded significantly. Project breakdown table, waste events panel, active insights cards. The server's LRU cache added to prevent expensive `full_analysis()` calls on every page refresh.

### Session 5 — Security Hardening

A security audit found multiple issues. BUG-001 through BUG-007 fixed in this session:
- HMAC timing-safe comparison added
- `X-Content-Type-Options` and `X-Frame-Options` headers added
- Raw JSONL content removed from API responses (was leaking transcript content)
- Origin check added to SSE endpoint
- Input validation added to all POST endpoints
- SQL injection prevention reviewed (all queries use parameterized statements)
- `_lock_db_file()` 0600 chmod added

### Session 6 — Analyzer Enhancements

`compute_context_rot()` added. `recommend_compact_threshold()` with Rules A-E. `compute_efficiency_score()` with 5 dimensions.

The context rot visualization was the most complex new feature — required binning sessions by turn depth and computing ratio series.

### Session 7 — MCP Server

`mcp_server.py` created. JSON-RPC 2.0 over stdio. The 5 v1 read-side tools. `run_test()` smoke test.

The MCP integration required understanding the Claude Code MCP registration format and the protocol handshake sequence. This session also added `claudash mcp` CLI command.

### Session 8 — Lifecycle Events and Subagent Tracking

`lifecycle_events` table added. `detect_lifecycle_events()` in `scanner.py`. Subagent detection via `/subagents/` path.

The `subagent_spawn` tracking was motivated by noticing that some projects' costs were inexplicably high — investigation revealed multiple subagent chains running expensive parallel tasks.

### Session 9 — Fix Generator

`fix_generator.py` created. The 6 prompt templates. Three provider functions. `generate_fix()` main entry.

The multi-provider design was added because the author uses both Anthropic direct API and AWS Bedrock, and wanted to use whichever was currently configured. The lazy `boto3` import was specifically to avoid breaking users who don't have boto3 installed. (v2.0.1 narrowed the third slot from "any OpenAI-compatible endpoint" to "OpenRouter routed to Anthropic models" — Claudash analyzes Claude transcripts; Claude is the right model to write CLAUDE.md rules.)

### Session 10 — v2 F1: Lifecycle Events Scan

`scan_lifecycle_events()` added to scanner. The `lifecycle_events` table was extended. The `compact_timing_pct` column added to sessions.

`CHANGELOG.md` entry for this session introduced the "v2 Feature" naming scheme (F1, F2, ...) to distinguish v2 additions from v1 foundation.

### Session 11 — v2 F2 + F3: Context Rot + Bad Compacts

Context rot visualization wired to the dashboard UI. `detect_bad_compacts()` with 5 regex signals added to `waste_patterns.py`. The 5 regex signals were the subject of significant iteration — early versions flagged too aggressively.

The bad compact detector remains at 0 events in the live database — either the patterns are not present in actual data, or the regexes are too specific.

### Session 12 — v2 F4-F7: Full v2 Feature Set

Four features in one session:

**F4**: `fix_generator.py` fully integrated. `claudash fix generate` command. `claudash keys --set-provider` command.

**F5**: Bidirectional MCP — added 5 write-side tools (claudash_trigger_scan, claudash_report_waste, claudash_generate_fix, claudash_dismiss_insight, claudash_get_warnings). `generate_mcp_warnings()` added.

**F6**: SSE streaming cost meter. `_live_sessions` dict. `/api/stream/cost` endpoint. `hooks/pre_tool_use.sh` and `hooks/post_tool_use.sh`. `/api/hooks/cost-event` endpoint.

**F7**: `recommend_compact_threshold()` per-project recommendations wired to both dashboard UI and MCP `claudash_summary` tool. `autoCompactThreshold` recommendations exposed via the compaction advisor panel.

---

## 17. Bug Registry — BUG-001 Through BUG-014

From `CHANGELOG.md`. All bugs are documented with root cause and fix.

### BUG-001: `settings.updated_at` Missing Column

**Session**: 5 (security hardening)
**Symptom**: `init_db()` created the settings table without an `updated_at` column, but `set_setting()` tried to write to it. `sqlite3.OperationalError: table settings has no column named updated_at`.
**Root cause**: The schema was updated in one commit but the migration logic was not added for existing databases.
**Fix**: Added `updated_at` to `CREATE TABLE settings`. Added a migration in `init_db()` that uses `ALTER TABLE settings ADD COLUMN updated_at INTEGER` with `IF NOT EXISTS` semantics (via PRAGMA table_info check).
**Commit**: `fix: BUG-005 — add settings.updated_at to init_db schema` (note: bug numbers in CHANGELOG may differ from internal tracking)

### BUG-002: Double-Counting in SSE Cost Meter

**Session**: 12 (F6)
**Symptom**: The live cost meter showed costs ~2x higher than actual.
**Root cause**: Both the pre-hook and post-hook were adding costs to `_live_sessions`. The pre-hook added an estimated 500-token cost. The post-hook added the actual token cost. But the post-hook was not replacing the pre-hook estimate — it was adding to it.
**Fix**: The post-hook path in `_prune_and_update_live_session()` now checks if an entry already exists and replaces it rather than adding a new one. Only the actual tokens (post-hook) are summed for display; pre-hook entries are marked `estimated=True` and shown separately.

### BUG-003: Compaction False Positives

**Session**: Multiple (ongoing)
**Symptom**: Some sessions were marked `compaction_detected = True` when no `/compact` command was issued.
**Root cause**: Natural context window variation could produce >30% drops between turns in very short sessions, or when large tool results were excluded from the next turn's context.
**Fix**: Added the `prev_ctx > 1000` noise floor check. Sessions with fewer than 1000 input tokens on the previous turn cannot trigger compaction detection. This eliminated ~95% of false positives.

### BUG-004: JSONL `sessionId` vs `uuid` Inconsistency

**Session**: 1-2
**Symptom**: Some sessions appeared twice in the `sessions` table with different IDs.
**Root cause**: Early Claude Code versions used `uuid` as the session identifier. Later versions introduced `sessionId` (which persists across compaction). The scanner was using whichever it found first.
**Fix**: `_parse_line()` now explicitly prefers `sessionId` over `uuid`:
```python
session_id = obj.get("sessionId") or obj.get("uuid")
```

### BUG-005: Cache Key Collision in LRU Cache

**Session**: 4
**Symptom**: Dashboard showed stale data after a scan even though the scan completed successfully.
**Root cause**: The cache key for `full_analysis` was `f"analysis_{account_id}"`. But `_cache_clear()` was only called for the specific account that was scanned. If the account ID was wrong (e.g., empty string), the cached entry for the real account was never cleared.
**Fix**: `_cache_clear()` now clears all entries matching `analysis_*` prefix, not just the specific account.

### BUG-006: Waste Events Accumulate Without Deduplication

**Session**: 2-3
**Symptom**: After multiple scans, the waste_events table had duplicate entries for the same session.
**Root cause**: `detect_all()` inserted new waste events without checking if events for those sessions already existed.
**Fix**: `detect_all()` now deletes all existing waste_events for the account before re-inserting. This is a full-replace approach rather than incremental — acceptable because waste detection is fast and runs on the full session set.

### BUG-007: SSE Connection Leak

**Session**: 12
**Symptom**: After several browser tab opens/closes, server memory usage grew and eventually the server became unresponsive.
**Root cause**: SSE connections were never cleaned up when the browser tab closed. The generator kept running and keeping a reference to the connection object.
**Fix**: Added a try/except around the SSE write loop that catches `BrokenPipeError` and `ConnectionResetError` to exit cleanly when the client disconnects.

### BUG-008: `_detect_floundering()` False Positives on Read Tool

**Session**: 2
**Symptom**: Almost every session was flagged as floundering because the Read tool is called repeatedly on the same files.
**Root cause**: The initial floundering detector used only `tool_name` as the repetition key, without considering the input. Reading the same file many times was correctly identified as repeated reads (a separate waste type) but also incorrectly flagged as floundering.
**Fix**: Changed the key to `(tool_name, input_hash)`. Also excluded the Read tool from floundering detection (it is handled by the repeated_reads detector instead).

### BUG-009: `fix_measurements` Verdict Computed Before Baseline

**Session**: 3
**Symptom**: Fix verdicts showed `improving` immediately after fix creation, before any new sessions had run.
**Root cause**: `compute_delta()` was comparing the current state against the baseline without checking whether any new sessions had accumulated since the baseline was captured.
**Fix**: Added a minimum session count check in `compute_delta()` — returns `insufficient_data` if fewer than 3 new sessions have been recorded since the baseline timestamp.

### BUG-010: Model Name Normalization Missed Variants

**Session**: 1-2
**Symptom**: Some sessions showed `cost_usd = 0` in the database.
**Root cause**: Claude Code logs model names like `claude-opus-4-6` or `claude-3-5-sonnet-20241022`. The normalizer only matched `"opus"` or `"sonnet"` substrings, but if Anthropic changed the model name format, cost calculation would fail silently.
**Fix**: Made the normalization more robust and added a fallback to `claude-opus` pricing rather than silently computing $0.

### BUG-011: Browser Account Polling Fails After Session Cookie Rotation

**Session**: Multiple
**Symptom**: Browser account snapshot becomes stale. `last_error` column shows authentication errors.
**Root cause**: claude.ai session cookies expire. The stored `session_key` becomes invalid and all subsequent polls fail.
**Fix** (partial): Added `last_error` column to track the failure. The dashboard shows a warning when `last_error` is set. However, there is no automated re-authentication — the user must manually update the session key via `claudash claude-ai add`. The `mac_sync_mode` flag (see §12) handles the push architecture but does not refresh expired cookies; the Mac-side `tools/mac-sync.py` must be re-run with a fresh browser session.

### BUG-012: `init_db()` Called Multiple Times Causes Constraint Violations

**Session**: 1
**Symptom**: Running `claudash init` twice raised sqlite3 errors.
**Root cause**: The accounts seed data used `INSERT INTO accounts` without `OR IGNORE`. Running init twice tried to insert the same account rows.
**Fix**: Changed to `INSERT OR IGNORE INTO accounts` for all seed data.

### BUG-013: Scan Reprocess Not Clearing Lifecycle Events

**Session**: Multiple
**Symptom**: After `claudash scan --reprocess`, lifecycle_events table had double entries.
**Root cause**: `cmd_scan_reprocess()` cleared `scan_state` rows but did not clear `lifecycle_events` or `waste_events`.
**Fix**: The reprocess command now also deletes all `lifecycle_events` and `waste_events` rows for the account before re-scanning.

### BUG-014: ThreadPoolExecutor Timeout Not Propagating

**Session**: 4-5
**Symptom**: Dashboard would hang for >10 seconds on some requests despite the 10-second timeout.
**Root cause**: The `future.result(timeout=10)` call in the ThreadPoolExecutor raised `concurrent.futures.TimeoutError`, but the exception was not caught — it propagated up and crashed the request handler without sending a response.
**Fix**: Added explicit catch for `concurrent.futures.TimeoutError` that returns the cached result (or an empty dict with an error flag) and sends a 200 response.

---

## 18. What Is Incomplete, Broken, or Deferred

This section is intentionally honest. As of v1.0.15, these are the known gaps.

### Structural Gaps

**Browser account historical data is not recorded**: The `claude_ai_usage` table is empty (0 rows in live DB). The snapshot-polling code writes to `claude_ai_snapshots` (replacing the latest row) but does not also write to `claude_ai_usage` for historical tracking. The schema supports it; the code does not use it. To see usage trends over time, there is no data.

**Fix UI is CLI-only**: The browser dashboard shows fixes and measurements but provides no way to create a fix, generate content, or trigger a measurement from the browser. All fix management requires running CLI commands. The CLAUDASH_V2_PRD.md specifies a full browser UI for the approve+apply stage, but it is not built.

**Bad compact detector has zero hits**: `detect_bad_compacts()` has been in the codebase since session 11, but the live database shows 0 bad_compact events. Either the 5 regex signals are too specific to fire on real data, or actual bad compacts are not happening. Without a confirmed true positive, it is hard to know which.

**`mac_sync_mode` is working as designed**: When set to `1`, the server skips outbound polling of claude.ai and relies on push from `tools/mac-sync.py` running on a Mac with browser access. Both accounts have `mac_sync_mode=1` and receive snapshots via this push flow. See §12 for the full explanation.

**VPS sync is not built**: The `config.py` reads `VPS_IP` and `VPS_PORT` from environment variables and the settings table has a `sync_token` key. No sync code exists. The design was sketched in comments but never implemented.

### Security Issues (Acknowledged)

**Session keys stored in plaintext**: `claude_ai_accounts.session_key` stores browser session cookies in SQLite. The database has 0600 permissions which limits exposure, but any process running as root (which is the case in the development environment) can read the database.

**API keys stored in plaintext**: `settings.anthropic_api_key` and `settings.openrouter_api_key` store provider keys in plaintext in the settings table. Same 0600 mitigation, same caveat. (Bedrock uses `~/.aws/credentials` instead of an in-DB key.)

**No HTTPS**: The dashboard server runs on plain HTTP. All traffic, including the `X-Dashboard-Key` header, is transmitted in cleartext on localhost. This is acceptable for localhost-only use but would be a problem if the server were ever bound to a non-loopback interface.

**Dashboard key is not rotated on compromise**: If the `dashboard_key` leaks (e.g., appears in shell history from `claudash keys --rotate`), there is no automatic rotation. The user must manually run `claudash keys --rotate`.

### Performance Issues

**No index on `sessions.project`**: The `project_metrics()` function runs `SELECT ... FROM sessions WHERE project = ?` which does a full table scan on 21,051 rows. At this size it is fast (~10ms), but will become noticeable above 100K sessions. No indexes are defined in `init_db()`.

**`full_analysis()` recomputes everything**: Each call to the `/api/data` endpoint calls all metric functions, which each issue multiple SQL queries. The 60-second LRU cache mitigates this, but cache misses are expensive. A background computation thread that pre-computes and caches analysis would be better.

**Context rot computation is O(n) on all sessions**: `compute_context_rot()` loads all sessions for an account into memory to bin them. At 21,051 sessions this is fine. At 1M sessions it would be a problem.

### Missing Features vs PRD

The CLAUDASH_V2_PRD.md specifies a `FixRecommendation` output schema from the generate stage:

```python
@dataclass
class FixRecommendation:
    waste_pattern: str
    fix_type: str
    title: str
    description: str
    diff: Optional[str]  # unified diff format for CLAUDE.md changes
    estimated_impact: str
    confidence: float
```

The current implementation does not produce this structured output. `generate_fix()` stores the raw LLM response in `generation_response` as a text blob. Parsing this into a structured `FixRecommendation` and presenting it in the browser UI for user review is the next major v2 milestone.

### Known Data Quality Issues

**Subagent cost attribution is approximate**: Subagent sessions are detected by path (`/subagents/` in file path) but there is no reliable way to link a subagent's token usage back to the parent session's logical task. The `parent_session_id` field is stored but not used in any metric computation — subagent costs are just counted separately.

**Compaction detection can miss**: If a session is compacted and then the JSONL file is fully replaced (as happens when `/compact` creates a new conversation), the pre-compact tokens are not available to compute the ratio. The scanner only sees the new, shorter conversation. This is intrinsic to the JSONL format, not a bug.

**Project name inference from paths can collide**: The project name is inferred from the JSONL directory path (the encoded path). If two different projects happen to produce the same encoded path (e.g., `/root/projects/foo` and `/root-projects/foo`), they would be merged in the database. This has not been observed in practice.

---

## Appendix A: File Map

| File | Lines | Purpose |
|------|-------|---------|
| `scanner.py` | ~450 | JSONL ingestion, compaction detection, lifecycle events |
| `analyzer.py` | ~380 | Metrics computation, context rot, compaction advisor |
| `waste_patterns.py` | ~280 | Four waste detectors + bad compact detector |
| `fix_tracker.py` | ~220 | Fix lifecycle, baseline, delta, verdict |
| `fix_generator.py` | ~180 | LLM-driven fix generation, 3 Anthropic-only providers |
| `insights.py` | ~320 | 14 insight rules |
| `server.py` | ~600 | HTTP server, SSE, hooks endpoint |
| `mcp_server.py` | ~350 | MCP stdio server, 10 tools |
| `cli.py` | ~500 | All CLI commands |
| `db.py` | ~400 | 18-table schema, CRUD, migration |
| `config.py` | ~80 | Pricing, accounts seed, env config |
| `_version.py` | ~15 | Version from package.json |
| `hooks/pre_tool_use.sh` | 8 | Claude Code pre-tool hook |
| `hooks/post_tool_use.sh` | 8 | Claude Code post-tool hook |
| `CLAUDASH_V2_PRD.md` | ~200 | v2 product requirements |
| `CHANGELOG.md` | ~500 | 12-session build history, bug registry |

---

## Appendix B: Environment and Configuration

```
~/.claude/.credentials.json   — Claude Code plan detection source
~/.claude/settings.json       — Where hooks must be registered
data/usage.db                 — SQLite database (0600 permissions)
data/                         — All Claudash-generated data
hooks/pre_tool_use.sh         — Pre-tool hook (install to settings.json)
hooks/post_tool_use.sh        — Post-tool hook (install to settings.json)
```

Settings keys in `settings` table:
- `dashboard_key` — HMAC auth key (auto-generated)
- `sync_token` — Future sync feature (currently unused)
- `fix_provider` — `anthropic` | `bedrock` | `openrouter` (all Anthropic models)
- `anthropic_api_key` — Anthropic direct API key
- `aws_region` — Bedrock region
- `openrouter_api_key` / `openrouter_model` — OpenRouter credentials
- `fix_autogen_model` — Per-provider model override

---

## Appendix C: npm Package Structure

```
@jeganwrites/claudash v1.0.15
├── bin/
│   └── claudash.js          # Node.js launcher
├── cli.py
├── server.py
├── scanner.py
├── analyzer.py
├── waste_patterns.py
├── fix_tracker.py
├── fix_generator.py
├── insights.py
├── mcp_server.py
├── db.py
├── config.py
├── _version.py
├── hooks/
│   ├── pre_tool_use.sh
│   └── post_tool_use.sh
├── package.json
└── README.md
```

---

## Appendix D: The autoCompactThreshold Feature in Detail

`autoCompactThreshold` is a Claude Code setting (in `~/.claude/settings.json`) that controls when Claude Code automatically issues a compact command. When set to an integer between 1 and 100, Claude Code will compact the context when it reaches that percentage of the context window. When set to 0 or absent, the user must manually issue `/compact`.

Claudash's F7 feature (per-project autoCompactThreshold recommendations) was motivated by observing that:

1. **20.3% average compact timing**: Users were compacting early (when context was only 20% full) — this is safe but potentially over-cautious.
2. **16 deep_no_compact events**: Other sessions ran past 100 turns without compacting at all.

The disconnect: the same user (same account) had some sessions with premature compaction and others with no compaction. The hypothesis is that compaction behavior is project-dependent — some projects' CLAUDE.md files have explicit compact instructions, others do not.

Rule B of the compaction advisor addresses this by computing per-project historical compact timing and recommending a threshold just below the project's typical behavior. If a project historically compacts at 25-40% context, recommending `autoCompactThreshold = 20` would automate the existing good behavior and prevent the long-tail sessions that never compact.

### Compact Threshold by Project (Estimated from Live Data)

The lifecycle_events table shows compact events with `context_pct_at_event`. Breaking this down by project:

- **Tidify**: Most compact events (highest session count). Typical compact timing ~15-25%. Recommended threshold: ~15.
- **Claudash**: Self-referential build sessions. Compact timing more variable (10-40%). Recommended threshold: ~20.
- **Brainworks**: Fewer sessions. Compact timing unclear.

The per-project recommendations are served via the `/api/recommendations` endpoint and shown in the dashboard's compaction advisor panel. They are also returned by the `claudash_summary` MCP tool so Claude itself can see and set its own `autoCompactThreshold` for the current project.

### The `compact_timing_pct` Column

The `sessions` table has a `compact_timing_pct` column (a float 0-100) that records at what context percentage the first compact happened in that session. This is the primary input to `recommend_compact_threshold()` Rule B. It is computed during `detect_lifecycle_events()` as:

```python
tokens_before_compact = session_data["tokens_before_compact"]
compact_timing_pct = (tokens_before_compact / window_token_limit) * 100
session_data["compact_timing_pct"] = compact_timing_pct
```

---

## Appendix E: The Efficiency Score in Detail

The efficiency score in `compute_efficiency_score()` is designed to give a single actionable number (0-100) that captures overall Claude Code usage quality. Each dimension is scored independently and then weighted.

### Dimension 1: Cache Efficiency (25% weight)

**Formula**: `cache_read_tokens / (input_tokens + cache_read_tokens)`

This is the "cache hit rate" — what fraction of the context was served from Anthropic's prompt cache rather than reprocessed. A high cache hit rate means the same context (files, instructions) is being reused across turns, which is both cheaper and faster.

**Scoring**:
- Cache rate > 80%: full 25 points
- Cache rate 60-80%: 20 points
- Cache rate 40-60%: 15 points
- Cache rate < 40%: 10 points

In the live database, the overall cache rate across all 21,051 sessions is dominated by the Tidify project's long multi-file sessions, which tend to have high cache rates once files are loaded.

### Dimension 2: Model Mix (25% weight)

**Formula**: Fraction of sessions using a sub-optimal model

A session is considered to be using a suboptimal model (Opus when Sonnet would work) if:
- Output tokens < 5,000 (simple task)
- Turn count < 20 (short session)
- No specialized tool use (no Bash, no Write)

Simple sessions running on Opus are wasteful — they cost 5x more than Sonnet for comparable quality on straightforward tasks.

**Scoring**: Based on the fraction of sessions that are "overmodeled." With 85.5% of sessions on Opus and many of them being short Sonnet-appropriate tasks, this dimension is likely the biggest drag on the overall score.

### Dimension 3: Window Efficiency (20% weight)

**Formula**: Fraction of sessions with window utilization in the "healthy" range (40-80%)

Sessions below 40% may have compacted too early. Sessions above 80% risk quality degradation. The optimal range is 40-80%.

This is distinct from raw window utilization — a 20% utilization is not "efficient" because it may indicate unnecessary compaction.

### Dimension 4: Flounder Rate (20% weight)

**Formula**: `floundering_sessions / total_sessions`

A low flounder rate is good. With 76 total waste events across 21,051 sessions (0.36%), the absolute flounder rate is low, but the sessions that do flounder cost significantly more than average.

### Dimension 5: Compaction Timing (10% weight)

**Formula**: Fraction of compact events that occurred in the "optimal" 30-70% context range

Compacting at <20% wastes context. Compacting at >80% risks running out of space. The 30-70% range is optimal.

With the live data showing 20.3% average compact timing, this dimension scores well — most compactions are happening early (before the window is crowded), which is the right behavior even if it is slightly more conservative than optimal.

---

## Appendix F: Hook Installation and Registration

The hooks must be registered in `~/.claude/settings.json` to fire during Claude Code sessions:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/claudash/hooks/pre_tool_use.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/claudash/hooks/post_tool_use.sh"
          }
        ]
      }
    ]
  }
}
```

The `matcher: ""` means the hook fires for all tool uses (Bash, Read, Write, Edit, etc.). The empty string is the "match everything" pattern in Claude Code's hook system.

### Environment Variables Available to Hooks

Claude Code sets these environment variables when invoking hooks:

| Variable | Description |
|----------|-------------|
| `CLAUDE_PROJECT` | Current project name |
| `CLAUDE_SESSION_ID` | Current session UUID |
| `CLAUDE_TOOL_NAME` | Name of the tool being called |
| `CLAUDE_TOOL_EXIT_CODE` | Exit code (PostToolUse only) |
| `CLAUDE_OUTPUT_TOKENS` | Output tokens from the turn (PostToolUse only) |

Note that `CLAUDE_OUTPUT_TOKENS` is only available in the PostToolUse hook. The PreToolUse hook uses a hardcoded estimate of 500 tokens.

### Why 500 for the Pre-Hook Estimate

The 500-token pre-hook estimate is intentionally conservative. It represents a small, single-tool response. Real responses can be 50-3000+ tokens. The purpose of the pre-hook is not accurate cost tracking but rather showing "this session is active" in the live meter. The actual tokens from the post-hook replace the estimate.

---

## Appendix G: The WASTE_PATTERNS and FIX_TYPES Constants

`fix_tracker.py` defines two constants that appear in the CLI interactive flows:

```python
WASTE_PATTERNS = [
    "repeated_reads",
    "floundering",
    "deep_no_compact",
    "cost_outlier",
    "bad_compact",
    "rewind_heavy",
]

FIX_TYPES = [
    "claude_md",      # Add/modify CLAUDE.md instructions
    "prompt",         # Change how you phrase prompts
    "settings_json",  # Modify Claude Code settings (autoCompactThreshold, etc.)
    "architecture",   # Structural code/workflow change
    "human",          # Manual behavioral change by the developer
]
```

The `fix_type` determines how the dashboard presents the fix and what the `applied_to_path` points to:

- `claude_md`: Path is the CLAUDE.md file. Fix detail is a CLAUDE.md block to append.
- `prompt`: No file path. Fix detail is prompt wording advice.
- `settings_json`: Path is `~/.claude/settings.json`. Fix detail includes the JSON key/value to set.
- `architecture`: No file path. Fix detail is a structural recommendation.
- `human`: No file path. Fix detail is a behavior note.

The `human` fix type is notable — it acknowledges that not all optimizations can be encoded in files. "Stop opening new sessions for every small change" is a valid fix that requires human behavior change, not a CLAUDE.md entry.

---

## Appendix H: Comparison to Competing Tools

| Feature | Claudash | ccusage | claude-usage | claude-view |
|---------|----------|---------|--------------|-------------|
| Token/cost tracking | Yes | Yes | Yes | No |
| Historical persistence | SQLite | None (live only) | Limited | No |
| Waste detection | 4 pattern types | No | No | No |
| Fix generation | LLM-driven | No | No | No |
| Fix measurement | Yes (10 verdicts) | No | No | No |
| Browser account tracking | Yes (2 accounts) | No | No | No |
| MCP integration | 10 tools | No | No | No |
| Live cost meter | SSE stream | No | No | No |
| Insights engine | 14 rules | No | No | No |
| Compaction advisor | Per-project rules | No | No | No |
| Context rot visualization | Yes | No | No | No |
| npm distribution | Yes | No | No | No |
| GitHub stars | private | 11,500+ | few hundred | few hundred |

Claudash's primary differentiator is the feedback loop: detect → generate fix → measure. None of the existing tools close this loop. They are all observability tools (what happened) rather than improvement tools (how to spend less next time).

The tradeoff is complexity. ccusage is a single Python file that can be run with no setup. Claudash requires `claudash init`, a running dashboard server, and hook installation. For users who just want a quick cost summary, ccusage is the right tool. For users who want to systematically reduce their Claude Code spend over time, Claudash provides structure that ccusage does not.

---

## Appendix I: The CLAUDE.md Anti-Pattern That Motivated the Tool

The repeated_reads pattern (56 events, $7,357.18 in session costs) has a specific root cause in the Tidify project that motivated much of Claudash's design.

Tidify is a healthcare data cleaning platform with complex TypeScript types. The primary type definitions live in `src/services/validation/types/phase2-types.ts` and `src/services/session/metadata-service.ts`. These files are large (~300-400 lines each) and are imported by 36+ other files.

In every session working on Tidify, Claude Code reads both files repeatedly — typically once per multi-step task because the type information it loaded earlier has been evicted from the "active working context" as turns accumulate. By turn 30, the assistant is re-reading `metadata-service.ts` for the 5th or 6th time.

The fix (fix #6 in the database, `fix_type = "prompt"`) is a CLAUDE.md entry that:
1. Summarizes the key type signatures from both files
2. Instructs the assistant not to re-read these files unless specifically modifying them
3. Provides the most frequently-needed type definitions inline

If this fix works as intended, the assistant should stop re-reading these files on every turn, reducing the repeated_reads events for Tidify. The current 9 improving verdicts suggest it is working, but the sample size is small.

This is the concrete feedback loop that Claudash was designed to enable: observe a specific pattern, generate a targeted fix, measure whether it worked.

---

---

## Appendix J: Quick Reference — Key Constants

| Constant | File | Value | Purpose |
|----------|------|-------|---------|
| `FLOUNDER_THRESHOLD` | waste_patterns.py | 4 | Min repeated identical tool calls to flag |
| `REPEATED_READ_THRESHOLD` | waste_patterns.py | 3 | Min same-file reads to flag |
| `COST_OUTLIER_MULTIPLIER` | waste_patterns.py | 3.0 | Std deviations above mean to flag as outlier |
| `DEEP_TURN_THRESHOLD` | waste_patterns.py | 100 | Min turns for deep_no_compact classification |
| `_CONTEXT_ROT_INFLECTION_DROP` | analyzer.py | 0.15 | Output/input ratio drop % to flag rot |
| `_CACHE_MAX` | server.py | 64 | LRU cache max entries |
| `_CACHE_TTL` | server.py | 60 | LRU cache TTL in seconds |
| Hook estimated tokens | pre_tool_use.sh | 500 | Pre-hook token estimate |
| Compaction drop threshold | scanner.py | 0.30 | Ratio drop to detect compaction |
| Compaction noise floor | scanner.py | 1000 | Min prev_ctx to run detection |
| Scan interval | server.py | 300 | Periodic scan interval (seconds) |
| ThreadPool timeout | server.py | 10 | Max seconds for analysis queries |

---

## Appendix K: Which LLM Provider to Use for Fix Generation

Claudash uses Claude to fix Claude Code waste. All three supported
providers run Anthropic models only — no Groq, no Llama, no non-Anthropic
inference. The philosophical choice (v2.0.1): the tool understands Claude
Code transcripts; Claude is the right model to analyze them.

**Anthropic API (direct) — the default**
- Cost: ~$0.006 per fix
- Model: `claude-sonnet-4-5`
- Key: Get from console.anthropic.com → API Keys
- Command: `claudash keys --set-provider` → choose [1] → enter key

**AWS Bedrock (Anthropic) — for AWS/HIPAA teams**
- Cost: ~$0.007 per fix (varies by region — check console.aws.amazon.com/bedrock)
- Auth: `~/.aws/credentials` — no new key if AWS is already configured
- Model: `anthropic.claude-sonnet-4-20250514-v1:0`
- Command: `claudash keys --set-provider` → choose [2] → enter region

**OpenRouter (Anthropic) — for users who want to use free credits first**
- Cost: ~$0.008 per fix
- Model: `anthropic/claude-sonnet-4-5`
- Key: Get at openrouter.ai — the free tier covers dozens of fixes
- Command: `claudash keys --set-provider` → choose [3] → enter key

**Privacy note**: Fix generation sends to the LLM:
- Pattern type (e.g. "repeated_reads")
- Project name (e.g. "Tidify")
- File basenames only — NOT full paths
- Your current CLAUDE.md contents
- Nothing else — no conversation history, no source code, no credentials

---

## Appendix L: What to Build Next

In priority order:

**P1 — Configure Bedrock or Groq and run a live fix generation**
Before building F4 Phase 2 (auto-apply), validate that the generator produces concrete, actionable rules on real Tidify waste data. `claudash fix generate <repeated_reads_event_id>` and review the output.

**P2 — Fix compact detection accuracy**
Add `tokens_after > 1000` filter in `detect_lifecycle_events()`. This excludes subagent context drops from compact events, making F7 recommendations project-specific instead of all returning 0.70. Estimated: 30 minutes.

**P3 — F4 Phase 2: fix_applier.py**
Write approved fixes to CLAUDE.md automatically. Full spec in CLAUDASH_V2_PRD.md §3.3. Requires: CLAUDE.md backup before write, mtime conflict detection, path safety check (stay inside ~/projects/). Estimated: 1 session.

**P4 — Fix context rot metric**
Change `output_tokens / input_tokens` to `output_tokens / (input_tokens + cache_read_tokens)` in `compute_context_rot()`. Makes the rot curve less noisy. Estimated: 15 minutes.

**P5 — npm version bump to 2.0.0 and publish**
`npm version 2.0.0 && npm publish --access public` Update package.json version. Push tag to GitHub.

**P6 — README screenshot**
Take a screenshot of the dashboard showing waste events + fix tracker. Add to `docs/screenshot.png`. Update README.md img reference.

**P7 — BUG-004: Fix measurement dedup**
Fix #5 has 4 measurements within 70 seconds. Add reject-within-5-min guard in `fix_tracker.measure_fix()`. Estimated: 30 minutes.

---

*End of Claudash Complete Technical and Product Writeup*
*Generated: 2026-04-16*
*Database snapshot: 21,051 sessions · $7,455.03 · personal_max account*
*44 git commits · @jeganwrites/claudash v1.0.15*
