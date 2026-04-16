import json
import os
import sys
import time
import threading
from datetime import datetime, timezone

from config import UNKNOWN_PROJECT, MODEL_PRICING
from db import (
    get_conn, insert_session, get_accounts_config, get_project_map_config,
    insert_lifecycle_event, insert_mcp_warning,
)
from insights import generate_insights

_last_scan_time = 0
_scan_lock = threading.Lock()  # serializes scan_all() across threads


def get_last_scan_time():
    return _last_scan_time


def is_scan_running():
    """Non-blocking check — True if a scan is currently holding the lock."""
    acquired = _scan_lock.acquire(blocking=False)
    if acquired:
        _scan_lock.release()
        return False
    return True


BATCH_FLUSH_SIZE = 10_000


def normalize_model(model_str):
    if not model_str:
        return "claude-sonnet"
    m = model_str.lower()
    if "opus" in m:
        return "claude-opus"
    if "haiku" in m:
        return "claude-haiku"
    return "claude-sonnet"


def resolve_project(folder_path, project_map=None):
    if project_map is None:
        project_map = get_project_map_config()
    path_lower = folder_path.lower()
    for project_name, info in project_map.items():
        for kw in info["keywords"]:
            if kw in path_lower:
                return project_name, info["account"]
    return UNKNOWN_PROJECT, "personal_max"


def compute_cost(model, input_tokens, output_tokens, cache_read, cache_create):
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet"])
    cost = 0.0
    cost += (input_tokens / 1_000_000) * pricing["input"]
    cost += (output_tokens / 1_000_000) * pricing["output"]
    cost += (cache_read / 1_000_000) * pricing["cache_read"]
    cost += (cache_create / 1_000_000) * pricing["cache_write"]
    return round(cost, 8)


def parse_timestamp(ts_str):
    if not ts_str:
        return None
    try:
        clean = ts_str.replace("Z", "").replace("+00:00", "")
        if "." in clean:
            clean = clean.split(".")[0]
        if "T" in clean:
            dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        pass
    return None


def _detect_compaction(session_rows):
    """Detect compaction events: a >30% drop in total inbound context
    (input_tokens + cache_read_tokens) between consecutive turns in a session.
    We use total context size because under Claude Code's prompt caching the
    bulk of the prompt lives in cache_read_tokens while input_tokens stays near
    zero — watching input_tokens alone misses every real compaction."""
    events = []
    for i in range(1, len(session_rows)):
        prev = session_rows[i - 1]
        curr = session_rows[i]
        prev_ctx = prev.get("input_tokens", 0) + prev.get("cache_read_tokens", 0)
        curr_ctx = curr.get("input_tokens", 0) + curr.get("cache_read_tokens", 0)
        if prev_ctx > 1000 and curr_ctx < prev_ctx * 0.7:
            events.append((i, prev_ctx, curr_ctx))
    return events


def _parse_line(line):
    """Parse a single JSONL line into a raw row dict, or None if invalid."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Prefer Claude Code's per-conversation sessionId. `uuid` is per-MESSAGE
    # (unique every row) and using it as session_id silently breaks every
    # per-session metric (compaction, session_depth, sessions_today).
    session_id = obj.get("sessionId") or obj.get("session_id") or obj.get("uuid", "")
    ts_str = obj.get("timestamp") or obj.get("ts", "")
    ts = parse_timestamp(ts_str) if isinstance(ts_str, str) else (int(ts_str) if ts_str else None)
    if not ts:
        return None

    model_raw = obj.get("model", "")
    if not model_raw and "message" in obj:
        model_raw = obj["message"].get("model", "")

    usage = {}
    if "message" in obj and isinstance(obj["message"], dict):
        usage = obj["message"].get("usage", {})
    if not usage:
        usage = obj.get("usage", {})

    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_create = usage.get("cache_creation_input_tokens", 0) or 0

    if input_tokens == 0 and output_tokens == 0:
        return None

    model = normalize_model(model_raw)
    cost = compute_cost(model, input_tokens, output_tokens, cache_read, cache_create)

    return {
        "session_id": session_id,
        "timestamp": ts,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_create,
        "cost_usd": cost,
        "compaction_detected": 0,
        "tokens_before_compact": None,
        "tokens_after_compact": None,
    }


def _get_scan_state(conn, filepath):
    """Get (last_offset, lines_processed) for a file, or (0, 0) if new."""
    row = conn.execute(
        "SELECT last_offset, lines_processed FROM scan_state WHERE file_path = ?",
        (filepath,),
    ).fetchone()
    if row:
        return row[0] or 0, row[1] or 0
    return 0, 0


def _set_scan_state(conn, filepath, offset, lines_processed):
    now = int(time.time())
    conn.execute(
        """INSERT INTO scan_state (file_path, last_offset, last_scanned, lines_processed)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(file_path) DO UPDATE SET
             last_offset=excluded.last_offset,
             last_scanned=excluded.last_scanned,
             lines_processed=excluded.lines_processed""",
        (filepath, offset, now, lines_processed),
    )


def _parse_subagent_info(filepath):
    """If the file lives under a `/subagents/` directory, return
    (is_subagent=1, parent_session_id), else (0, None).

    Expected shape: .../<parent_session_uuid>/subagents/agent-*.jsonl
    The parent's session UUID is the folder immediately above `subagents`.
    """
    if "/subagents/" not in filepath:
        return 0, None
    parent_dir = filepath.split("/subagents/")[0]
    parent_uuid = os.path.basename(parent_dir)
    return 1, (parent_uuid or None)


def scan_jsonl_file(filepath, folder_path, conn, source_path="", project_map=None):
    """Parse new lines from a JSONL file using incremental offset tracking."""
    # For subagent files, resolve project from the *parent* project folder
    # (the grandparent of `subagents/`) so the subagent inherits the parent's
    # project tag even if the `subagents` directory itself has no matching
    # keyword.
    is_subagent, parent_sid = _parse_subagent_info(filepath)
    resolve_against = folder_path
    if is_subagent:
        parent_project_folder = filepath.split("/subagents/")[0]
        parent_project_folder = os.path.dirname(parent_project_folder)
        resolve_against = parent_project_folder or folder_path
    project, account = resolve_project(resolve_against, project_map)

    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        return 0

    last_offset, prev_lines = _get_scan_state(conn, filepath)

    # File was truncated/rotated — reset
    if file_size < last_offset:
        last_offset = 0
        prev_lines = 0

    # Nothing new to read
    if file_size == last_offset:
        return 0

    def _flush(rows):
        """Run compaction detection + insert in one batch. Returns rows added."""
        if not rows:
            return 0
        sessions = {}
        for i, row in enumerate(rows):
            sessions.setdefault(row["session_id"], []).append(i)
        for sid, indices in sessions.items():
            indices.sort(key=lambda idx: rows[idx]["timestamp"])
            session_data = [rows[idx] for idx in indices]
            for evt_idx, before, after in _detect_compaction(session_data):
                real_idx = indices[evt_idx]
                rows[real_idx]["compaction_detected"] = 1
                rows[real_idx]["tokens_before_compact"] = before
                rows[real_idx]["tokens_after_compact"] = after
        added_local = 0
        for row in rows:
            before = conn.total_changes
            insert_session(conn, row)
            if conn.total_changes > before:
                added_local += 1
        conn.commit()
        return added_local

    raw_rows = []
    new_lines = 0
    added = 0
    try:
        with open(filepath, "r", errors="replace") as f:
            if last_offset > 0:
                f.seek(last_offset)
            for line in f:
                if len(line) > 1_000_000:  # 1MB max line
                    print(f"WARNING: skipping oversized line ({len(line)} bytes) in {filepath}", file=sys.stderr)
                    continue
                if not line.strip():
                    continue
                new_lines += 1
                parsed = _parse_line(line)
                if parsed:
                    parsed["project"] = project
                    parsed["account"] = account
                    parsed["source_path"] = filepath
                    parsed["is_subagent"] = is_subagent
                    parsed["parent_session_id"] = parent_sid
                    raw_rows.append(parsed)
                    # Flush batch to DB to keep memory bounded on cold scans
                    if len(raw_rows) >= BATCH_FLUSH_SIZE:
                        added += _flush(raw_rows)
                        raw_rows = []
            end_offset = f.tell()
    except Exception as e:
        print(f"[scanner] Error reading {filepath}: {e}", file=sys.stderr)
        return 0

    added += _flush(raw_rows)
    _set_scan_state(conn, filepath, end_offset, prev_lines + new_lines)
    return added


_CONTEXT_LIMIT = 1_000_000  # Max plan context cap, used for context_pct calcs
_SUBAGENT_TOOL_NAMES = ("Agent", "Task")  # Claude Code subagent-spawn tool names


def _iter_messages(filepath):
    """Yield parsed JSONL objects from a file in file order. Ignores bad JSON."""
    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _message_usage(obj):
    """Extract the usage dict from a parsed JSONL object."""
    if "message" in obj and isinstance(obj["message"], dict):
        u = obj["message"].get("usage")
        if isinstance(u, dict):
            return u
    u = obj.get("usage")
    return u if isinstance(u, dict) else {}


def _iter_assistant_tool_uses(obj):
    """Yield tool_use blocks inside an assistant message."""
    if obj.get("type") != "assistant":
        return
    msg = obj.get("message") or {}
    if not isinstance(msg, dict):
        return
    content = msg.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block


def detect_lifecycle_events(messages, session_id, project, conn):
    """Scan a parsed message list for one session; emit compact + subagent_spawn
    lifecycle events. Dedup is handled by the UNIQUE (session_id, event_type,
    timestamp) constraint. Returns count of newly-inserted events.
    """
    if not session_id or not project or not messages:
        return 0

    # Build a per-turn view: timestamp + context size (input + cache_read) +
    # tool_use blocks. Only assistant messages with usage participate in the
    # compact heuristic (matches _parse_line's filter — tool_result/user/system
    # messages have no usage and would otherwise read as ctx=0 and trigger
    # false "compacts" on every turn).
    turns = []
    for idx, obj in enumerate(messages):
        ts_raw = obj.get("timestamp") or obj.get("ts")
        ts = None
        if isinstance(ts_raw, str):
            ts = parse_timestamp(ts_raw)
        elif isinstance(ts_raw, (int, float)):
            ts = int(ts_raw)
        if not ts:
            continue
        if obj.get("type") != "assistant":
            continue
        usage = _message_usage(obj)
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        cache_r = usage.get("cache_read_input_tokens", 0) or 0
        if input_t == 0 and output_t == 0:
            continue
        ctx = input_t + cache_r
        tool_uses = list(_iter_assistant_tool_uses(obj))
        turns.append({"turn_idx": idx, "timestamp": ts, "ctx": ctx, "tool_uses": tool_uses})

    emitted = 0

    # COMPACT: same heuristic as _detect_compaction — ctx drops >30% between
    # consecutive turns, previous ctx must be >1000 to avoid early-session noise.
    for i in range(1, len(turns)):
        prev_ctx = turns[i - 1]["ctx"]
        curr_ctx = turns[i]["ctx"]
        if prev_ctx > 1000 and curr_ctx < prev_ctx * 0.7:
            context_pct = round(prev_ctx / _CONTEXT_LIMIT * 100, 2)
            meta = json.dumps({
                "tokens_before": prev_ctx,
                "tokens_after": curr_ctx,
                "turn": turns[i]["turn_idx"],
            })
            if insert_lifecycle_event(
                conn, session_id, project, "compact",
                turns[i]["timestamp"], context_pct, meta,
            ):
                emitted += 1

    # SUBAGENT_SPAWN: every Task/Agent tool_use in an assistant message.
    for turn in turns:
        for tu in turn["tool_uses"]:
            name = tu.get("name") or ""
            if name not in _SUBAGENT_TOOL_NAMES:
                continue
            inp = tu.get("input") if isinstance(tu.get("input"), dict) else {}
            desc = str(inp.get("description") or inp.get("prompt") or "")[:200]
            context_pct = round(turn["ctx"] / _CONTEXT_LIMIT * 100, 2) if turn["ctx"] > 0 else None
            meta = json.dumps({
                "turn": turn["turn_idx"],
                "task_description": desc,
                "tool": name,
            })
            if insert_lifecycle_event(
                conn, session_id, project, "subagent_spawn",
                turn["timestamp"], context_pct, meta,
            ):
                emitted += 1

    return emitted


def scan_lifecycle_events(conn):
    """Iterate every file in scan_state, group messages by sessionId, run
    detect_lifecycle_events. Cheap re-reads are fine — UNIQUE constraint dedups.
    Returns (events_inserted, files_processed)."""
    rows = conn.execute("SELECT file_path FROM scan_state").fetchall()
    total_events = 0
    files_done = 0
    for r in rows:
        filepath = r[0]
        if not os.path.isfile(filepath):
            continue
        messages_by_sid = {}
        for obj in _iter_messages(filepath):
            sid = obj.get("sessionId") or obj.get("session_id") or obj.get("uuid")
            if not sid:
                continue
            messages_by_sid.setdefault(sid, []).append(obj)
        if not messages_by_sid:
            continue
        for sid, msgs in messages_by_sid.items():
            row = conn.execute(
                "SELECT project FROM sessions WHERE session_id = ? LIMIT 1", (sid,),
            ).fetchone()
            if not row or not row["project"]:
                continue
            total_events += detect_lifecycle_events(msgs, sid, row["project"], conn)
        files_done += 1
    conn.commit()
    return total_events, files_done


def scan_all(account_filter=None):
    """Walk all configured data_paths and scan JSONL files incrementally.
    Serialized via _scan_lock — concurrent callers wait for the in-flight scan."""
    global _last_scan_time
    with _scan_lock:
        return _scan_all_locked(account_filter)


def _scan_all_locked(account_filter=None):
    global _last_scan_time
    conn = get_conn()
    accounts = get_accounts_config(conn)
    project_map = get_project_map_config(conn)
    total_added = 0
    files_scanned = 0

    for account_key, acct in accounts.items():
        if account_filter and account_key != account_filter:
            continue
        for data_path in acct.get("data_paths", []):
            if not os.path.isdir(data_path):
                print(f"[scanner] {data_path} does not exist, skipping", file=sys.stderr)
                continue

            for root, dirs, files in os.walk(data_path):
                for fname in files:
                    if not fname.endswith(".jsonl"):
                        continue
                    filepath = os.path.join(root, fname)
                    added = scan_jsonl_file(filepath, root, conn, source_path=data_path, project_map=project_map)
                    total_added += added
                    if added > 0:
                        files_scanned += 1

    conn.commit()

    # Lifecycle event detection pass — reads tool_use blocks and compact events
    # from every tracked JSONL. Runs after the main scan so sessions rows exist
    # for project lookup. UNIQUE constraint makes it idempotent.
    try:
        evts, _files = scan_lifecycle_events(conn)
        if evts:
            print(f"[scanner] Lifecycle: {evts} new events", file=sys.stderr)
    except Exception as e:
        print(f"[scanner] Lifecycle detection error: {e}", file=sys.stderr)

    conn.close()
    _last_scan_time = int(time.time())
    print(f"[scanner] Scan complete: {total_added} new rows (incremental, {files_scanned} files changed)", file=sys.stderr)
    return total_added


def preview_paths(data_paths):
    result = []
    for p in data_paths:
        expanded = os.path.expanduser(p)
        exists = os.path.isdir(expanded)
        count = 0
        if exists:
            for root, dirs, files in os.walk(expanded):
                for fname in files:
                    if fname.endswith(".jsonl"):
                        count += 1
        result.append({"path": p, "expanded": expanded, "exists": exists, "jsonl_files": count})
    return result


def discover_claude_paths():
    import glob
    import platform
    home = os.path.expanduser("~")
    system = platform.system()

    # Platform-specific candidate directories
    if system == "Windows":
        candidates = [
            os.path.join(home, "AppData", "Roaming", "Claude", "projects"),
            os.path.join(home, "AppData", "Local", "Claude", "projects"),
            os.path.join(home, "AppData", "Roaming", "anthropic", "claude", "projects"),
            os.path.join(home, ".claude", "projects"),
        ]
    elif system == "Darwin":
        candidates = [
            os.path.join(home, ".claude", "projects"),
            os.path.join(home, "Library", "Application Support", "Claude", "projects"),
        ]
    else:  # Linux
        candidates = [
            os.path.join(home, ".claude", "projects"),
            os.path.join(home, ".config", "claude", "projects"),
            os.path.join(home, ".local", "share", "claude", "projects"),
        ]

    found = set()
    for c in candidates:
        if os.path.isdir(c):
            found.add(c + "/")

    # Also glob for .claude-* variants
    patterns = [
        os.path.join(home, ".claude", "projects"),
        os.path.join(home, ".claude-*", "projects"),
    ]
    for pattern in patterns:
        for match in glob.glob(pattern):
            if os.path.isdir(match):
                found.add(match + "/")

    try:
        for entry in os.listdir(home):
            if "claude" in entry.lower() and entry.startswith("."):
                candidate = os.path.join(home, entry, "projects")
                if os.path.isdir(candidate):
                    found.add(candidate + "/")
    except OSError:
        pass

    default_path = os.path.join(home, ".claude", "projects") + "/"

    result = []
    kept = set()
    for p in sorted(found):
        count = 0
        for root, dirs, files in os.walk(p):
            for fname in files:
                if fname.endswith(".jsonl"):
                    count += 1
        # Only keep paths that actually contain JSONL files, unless it's the
        # standard default (which new users will have empty until they run
        # Claude Code for the first time).
        if count > 0 or p == default_path:
            result.append({"path": p, "exists": True, "estimated_records": count})
            kept.add(p)

    # Always surface the default path as a suggestion, even if it's missing
    # on disk — new installs should see it so the user can accept it.
    if default_path not in kept:
        result.insert(0, {
            "path": default_path,
            "exists": os.path.isdir(default_path),
            "estimated_records": 0,
        })

    return sorted(result, key=lambda r: r["path"])


# ─── v2-F5: MCP warning queue generator ─────────────────────────
#
# After each scan + waste-detection pass, push actionable warnings into
# mcp_warnings. Dedup per (project, warning_type) on a 6-hour window so
# Claude Code sessions that call claudash_get_warnings don't see the
# same alert over and over.

_MCP_WARNING_DEDUP_HOURS = 6
_LATE_COMPACT_PCT_THRESHOLD = 80
_LATE_COMPACT_MIN_COUNT = 3
_REPEATED_READS_SPIKE_PCT = 20
_BUDGET_WARNING_PCT = 0.80


def _warning_exists_recent(conn, project, warning_type, hours=_MCP_WARNING_DEDUP_HOURS):
    since = int(time.time()) - hours * 3600
    row = conn.execute(
        "SELECT 1 FROM mcp_warnings "
        "WHERE project = ? AND warning_type = ? AND created_at >= ? LIMIT 1",
        (project, warning_type, since),
    ).fetchone()
    return row is not None


def generate_mcp_warnings(conn):
    """Emit MCP warnings based on recent lifecycle/waste/budget state.
    Idempotent per project+warning_type within a 6-hour window."""
    now = int(time.time())
    seven_days = now - 7 * 86400
    fourteen_days = now - 14 * 86400
    one_day = now - 86400
    emitted = 0

    # Rule 1 — LATE_COMPACT: >=3 compacts with context_pct > 80 in last 7 days
    try:
        rows = conn.execute(
            "SELECT project, COUNT(*) AS n, AVG(context_pct_at_event) AS avg_pct "
            "FROM lifecycle_events "
            "WHERE event_type = 'compact' AND context_pct_at_event > ? "
            "  AND timestamp >= ? "
            "GROUP BY project "
            "HAVING n >= ?",
            (_LATE_COMPACT_PCT_THRESHOLD, seven_days, _LATE_COMPACT_MIN_COUNT),
        ).fetchall()
        for r in rows:
            proj = r["project"] if hasattr(r, "keys") else r[0]
            if not proj or _warning_exists_recent(conn, proj, "late_compact"):
                continue
            avg_pct = r["avg_pct"] if hasattr(r, "keys") else r[2]
            msg = (
                f"{proj} compacting late (avg {avg_pct:.0f}% context) — "
                "run /compact earlier or lower autoCompactThreshold"
            )
            insert_mcp_warning(conn, proj, None, "late_compact", msg, "amber")
            emitted += 1
    except Exception as e:
        print(f"[scanner] mcp_warnings late_compact error: {e}", file=sys.stderr)

    # Rule 2 — REPEATED_READS_SPIKE: this-week count >20% above prior-week
    try:
        curr_rows = conn.execute(
            "SELECT project, COUNT(*) AS n FROM waste_events "
            "WHERE pattern_type = 'repeated_reads' "
            "  AND detected_at >= ? GROUP BY project",
            (seven_days,),
        ).fetchall()
        prev_rows = conn.execute(
            "SELECT project, COUNT(*) AS n FROM waste_events "
            "WHERE pattern_type = 'repeated_reads' "
            "  AND detected_at >= ? AND detected_at < ? GROUP BY project",
            (fourteen_days, seven_days),
        ).fetchall()
        prev_by_proj = {
            (r["project"] if hasattr(r, "keys") else r[0]): (r["n"] if hasattr(r, "keys") else r[1])
            for r in prev_rows
        }
        for r in curr_rows:
            proj = r["project"] if hasattr(r, "keys") else r[0]
            curr_n = r["n"] if hasattr(r, "keys") else r[1]
            prev_n = prev_by_proj.get(proj, 0)
            if prev_n <= 0 or not proj:
                continue  # no prior baseline — skip spike logic
            pct = (curr_n - prev_n) / prev_n * 100
            if pct <= _REPEATED_READS_SPIKE_PCT:
                continue
            if _warning_exists_recent(conn, proj, "repeated_reads_spike"):
                continue
            top = conn.execute(
                "SELECT id FROM waste_events "
                "WHERE pattern_type = 'repeated_reads' AND project = ? "
                "  AND detected_at >= ? "
                "ORDER BY token_cost DESC LIMIT 1",
                (proj, seven_days),
            ).fetchone()
            top_id = top[0] if top else None
            tail = (f" — consider running: claudash fix generate {top_id}"
                    if top_id is not None else "")
            msg = f"{proj} repeated_reads up {pct:.0f}% this week{tail}"
            insert_mcp_warning(conn, proj, None, "repeated_reads_spike", msg, "amber")
            emitted += 1
    except Exception as e:
        print(f"[scanner] mcp_warnings repeated_reads_spike error: {e}", file=sys.stderr)

    # Rule 3 — BUDGET_80PCT: any account over 80% of daily budget
    try:
        from analyzer import daily_budget_metrics as _dbm
        dbm = _dbm(conn, "all")
        for acct_id, b in (dbm or {}).items():
            if not b.get("has_budget"):
                continue
            limit = b.get("budget_usd") or 0
            cost = b.get("today_cost") or 0
            if limit <= 0:
                continue
            ratio = cost / limit
            if ratio < _BUDGET_WARNING_PCT:
                continue
            # Use account_id as the "project" slot so get_pending_warnings
            # retrieval works symmetrically when filtered by project.
            key = acct_id
            if _warning_exists_recent(conn, key, "budget_80pct"):
                continue
            pct = ratio * 100
            msg = f"{acct_id} at {pct:.0f}% of daily budget — slow down"
            insert_mcp_warning(conn, key, None, "budget_80pct", msg, "red")
            emitted += 1
    except Exception as e:
        print(f"[scanner] mcp_warnings budget_80pct error: {e}", file=sys.stderr)

    # Rule 4 — FLOUNDERING_LIVE: any floundering waste_event in last 24h
    try:
        rows = conn.execute(
            "SELECT DISTINCT project FROM waste_events "
            "WHERE pattern_type = 'floundering' AND detected_at >= ?",
            (one_day,),
        ).fetchall()
        for r in rows:
            proj = r["project"] if hasattr(r, "keys") else r[0]
            if not proj or _warning_exists_recent(conn, proj, "floundering_live"):
                continue
            msg = (
                f"{proj} floundering detected today — "
                "Claude is retrying the same tool. Check session."
            )
            insert_mcp_warning(conn, proj, None, "floundering_live", msg, "red")
            emitted += 1
    except Exception as e:
        print(f"[scanner] mcp_warnings floundering_live error: {e}", file=sys.stderr)

    if emitted:
        print(f"[scanner] MCP warnings: {emitted} new", file=sys.stderr)
    return emitted


def _auto_measure_fixes(conn):
    """v2-P2: Called from the periodic scan after waste detection. For every
    fix in status 'applied' or 'measuring' that has aged ≥1 day, has ≥3 new
    sessions since baseline, and hasn't been measured in the last 6 hours,
    run measure_fix() and record a fix_regressing insight if the verdict is
    worsened.

    6-hour measurement dedup prevents fix_measurements from accumulating
    288 rows/day per fix when the scanner fires every 5 minutes.
    """
    import json as _json
    try:
        from fix_tracker import measure_fix
    except ImportError:
        return 0

    rows = conn.execute(
        "SELECT id, project, created_at, baseline_json FROM fixes "
        "WHERE status IN ('applied', 'measuring') AND created_at IS NOT NULL"
    ).fetchall()

    measured = 0
    now = time.time()
    for fix in rows:
        fix_id = fix["id"]
        days_elapsed = (now - (fix["created_at"] or 0)) / 86400
        if days_elapsed < 1:
            continue
        try:
            baseline = _json.loads(fix["baseline_json"] or "{}")
        except _json.JSONDecodeError:
            continue
        baseline_at = baseline.get("captured_at", fix["created_at"] or 0)
        new_sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM sessions "
            "WHERE project = ? AND timestamp > ?",
            (fix["project"], baseline_at),
        ).fetchone()[0] or 0
        if new_sessions < 3:
            continue
        # 6-hour dedup window — skip if we measured this fix recently.
        last = conn.execute(
            "SELECT measured_at FROM fix_measurements "
            "WHERE fix_id = ? ORDER BY measured_at DESC LIMIT 1",
            (fix_id,),
        ).fetchone()
        if last and (now - last["measured_at"]) < 6 * 3600:
            continue
        delta, verdict, _metrics = measure_fix(conn, fix_id)
        measured += 1
        if verdict == "worsened":
            # Emit a fix_regressing insight so the dashboard surfaces it.
            # Use INSERT OR IGNORE-style dedup by checking for an existing
            # active insight for this fix_id in the last 24 hours.
            existing = conn.execute(
                "SELECT id FROM insights WHERE insight_type = 'fix_regressing' "
                "AND dismissed = 0 AND created_at > ? AND detail_json LIKE ?",
                (int(now) - 86400, f'%"fix_id": {fix_id}%'),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO insights "
                    "(created_at, account, project, insight_type, message, detail_json, dismissed) "
                    "VALUES (?, 'personal_max', ?, 'fix_regressing', ?, ?, 0)",
                    (
                        int(now),
                        fix["project"],
                        f"Fix #{fix_id} regressed — waste increased after applying this fix",
                        _json.dumps({"fix_id": fix_id, "delta": delta}),
                    ),
                )
                conn.commit()
    if measured:
        print(f"[scanner] Auto-measured {measured} fix(es)", file=sys.stderr)
    return measured


def start_periodic_scan(interval_seconds=300):
    def _run():
        while True:
            try:
                scan_all()
                generate_insights()
                # v2-F5: refresh waste detection, then emit MCP warnings so
                # claudash_get_warnings sees current state on each 5-min cycle.
                try:
                    from waste_patterns import detect_all as _detect_all
                    conn = get_conn()
                    try:
                        _detect_all(conn)
                        generate_mcp_warnings(conn)
                        # v2-P2: Auto-measure fixes that have enough post-baseline
                        # data. Runs every cycle but dedupes within 6h per fix
                        # so we don't spam fix_measurements with 288 rows/day.
                        _auto_measure_fixes(conn)
                    finally:
                        conn.close()
                except Exception as _e:
                    print(f"[scanner] periodic waste/warning error: {_e}", file=sys.stderr)
            except Exception as e:
                print(f"[scanner] Periodic scan error: {e}", file=sys.stderr)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
