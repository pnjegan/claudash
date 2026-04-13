import json
import os
import sys
import time
import threading
from datetime import datetime, timezone

from config import UNKNOWN_PROJECT, MODEL_PRICING
from db import get_conn, insert_session, get_accounts_config, get_project_map_config

_last_scan_time = 0


def get_last_scan_time():
    return _last_scan_time


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

    raw_rows = []
    new_lines = 0
    try:
        with open(filepath, "r", errors="replace") as f:
            if last_offset > 0:
                f.seek(last_offset)
            for line in f:
                new_lines += 1
                parsed = _parse_line(line)
                if parsed:
                    parsed["project"] = project
                    parsed["account"] = account
                    # Store the actual JSONL file path, not the data_path root.
                    # Without the full path we can't re-resolve the project from
                    # a session row, and every session from one data_path looks
                    # identical. scan_state tracks the same key.
                    parsed["source_path"] = filepath
                    parsed["is_subagent"] = is_subagent
                    parsed["parent_session_id"] = parent_sid
                    raw_rows.append(parsed)
            end_offset = f.tell()
    except Exception as e:
        print(f"[scanner] Error reading {filepath}: {e}", file=sys.stderr)
        return 0

    # Compaction detection within this batch
    sessions = {}
    for i, row in enumerate(raw_rows):
        sid = row["session_id"]
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(i)

    for sid, indices in sessions.items():
        indices.sort(key=lambda idx: raw_rows[idx]["timestamp"])
        session_data = [raw_rows[idx] for idx in indices]
        compaction_events = _detect_compaction(session_data)
        for evt_idx, before, after in compaction_events:
            real_idx = indices[evt_idx]
            raw_rows[real_idx]["compaction_detected"] = 1
            raw_rows[real_idx]["tokens_before_compact"] = before
            raw_rows[real_idx]["tokens_after_compact"] = after

    added = 0
    for row in raw_rows:
        before = conn.total_changes
        insert_session(conn, row)
        if conn.total_changes > before:
            added += 1

    _set_scan_state(conn, filepath, end_offset, prev_lines + new_lines)
    return added


def scan_all(account_filter=None):
    """Walk all configured data_paths and scan JSONL files incrementally."""
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
    home = os.path.expanduser("~")
    patterns = [
        os.path.join(home, ".claude", "projects"),
        os.path.join(home, ".claude-*", "projects"),
    ]
    found = set()
    for pattern in patterns:
        for match in glob.glob(pattern):
            if os.path.isdir(match):
                found.add(match + "/")

    for entry in os.listdir(home):
        if "claude" in entry.lower() and entry.startswith("."):
            candidate = os.path.join(home, entry, "projects")
            if os.path.isdir(candidate):
                found.add(candidate + "/")

    result = []
    for p in sorted(found):
        count = 0
        for root, dirs, files in os.walk(p):
            for fname in files:
                if fname.endswith(".jsonl"):
                    count += 1
        result.append({"path": p, "exists": True, "estimated_records": count})
    return result


def start_periodic_scan(interval_seconds=300):
    def _run():
        while True:
            try:
                scan_all()
            except Exception as e:
                print(f"[scanner] Periodic scan error: {e}", file=sys.stderr)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
