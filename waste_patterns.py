"""Waste pattern detection — Claudash intelligence layer.

Detects four patterns of wasteful Claude Code usage:

  1. FLOUNDERING           — same tool name called >=4 times in a row
                             without any other tool, suggesting Claude
                             is stuck retrying.
  2. REPEATED_READS        — the same file is read via `Read` >=3 times
                             in one session (cache churn, re-fetching).
  3. COST_OUTLIER          — a single session's cost is >3x the 30-day
                             per-project average.
  4. DEEP_CONTEXT_NO_COMPACT — session has >100 turns and zero compaction
                             events (`/compact` never fired).

Each detection is UPSERTed into `waste_events` keyed on
(session_id, pattern_type).

This module reads JSONL files directly via the scan_state table — it
does NOT require new columns on the sessions table for tool_use data.
That keeps the waste detection independent of the main ingestion path.
"""

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import defaultdict

from db import get_conn, insert_waste_event, clear_waste_events, get_setting, set_setting


# ─── Parameters ──────────────────────────────────────────────────

FLOUNDER_THRESHOLD = 4           # same (tool, input_hash) repeats within the window
FLOUNDER_WINDOW = 50             # repeats must sit within N consecutive tool calls to count
REPEATED_READ_THRESHOLD = 3      # same file read N times in one session
COST_OUTLIER_MULTIPLIER = 3.0    # session cost > Nx project avg
DEEP_TURN_THRESHOLD = 100        # turns in a session


# ─── JSONL tool-use extraction ───────────────────────────────────

def _iter_assistant_tool_calls(filepath):
    """Yield (turn_index, tool_name, tool_input_dict) for every tool_use
    block in the assistant messages of a Claude Code JSONL file.

    Claude Code writes one JSON object per line. Assistant messages with
    tool use have shape:

      {"type": "assistant",
       "message": {"role": "assistant",
                   "content": [{"type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "..."}}]}}
    """
    turn = 0
    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                turn += 1
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name") or ""
                    inp = block.get("input") or {}
                    if isinstance(inp, dict):
                        yield turn, name, inp
    except OSError:
        return


def _file_session_id(filepath):
    """Return the first sessionId/session_id/uuid in the file, or None."""
    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = obj.get("sessionId") or obj.get("session_id") or obj.get("uuid")
                if sid:
                    return sid
    except OSError:
        return None
    return None


# ─── Pattern detectors ───────────────────────────────────────────

def _input_hash(inp):
    """Short hash of tool input for deduplication. Identical (tool, input)
    pairs are intentional retries, not floundering."""
    if not inp:
        return ""
    return hashlib.md5(str(inp)[:200].encode()).hexdigest()[:8]


def _detect_floundering(tool_calls):
    """Return (count, detail) for FLOUNDERING — (tool, input_hash) keys that
    repeat >=FLOUNDER_THRESHOLD times within any FLOUNDER_WINDOW-wide slice
    of consecutive tool calls.

    Density-based, not consecutive: real Claude Code sessions interleave
    Reads/Greps/Edits between retries, so the legacy "4 in a row" rule
    never fired (see CLAUDASH_AUDIT.md §7 flag 1 — top Tidify session had
    7 repeats of one Bash invocation but longest consecutive run was 1).
    Intentional re-runs stay excluded because identical-input calls that
    are spread widely (>FLOUNDER_WINDOW apart) are not flagged."""
    calls = list(tool_calls)
    positions = defaultdict(list)
    for idx, (turn, name, inp) in enumerate(calls):
        positions[(name, _input_hash(inp))].append((idx, turn, name))

    runs = []
    for _key, occs in positions.items():
        if len(occs) < FLOUNDER_THRESHOLD:
            continue
        for i in range(len(occs) - FLOUNDER_THRESHOLD + 1):
            span = occs[i + FLOUNDER_THRESHOLD - 1][0] - occs[i][0]
            if span < FLOUNDER_WINDOW:
                runs.append({
                    "tool": occs[i][2],
                    "length": len(occs),
                    "start_turn": occs[i][1],
                })
                break
    return len(runs), {"runs": runs, "total_flounder_calls": sum(r["length"] for r in runs)}


def _detect_repeated_reads(tool_calls):
    """Return (count, detail) for REPEATED_READS — files `Read` >=3 times."""
    read_counts = defaultdict(int)
    for _turn, name, inp in tool_calls:
        if name != "Read":
            continue
        file_path = inp.get("file_path") or inp.get("path") or inp.get("filename")
        if not file_path:
            continue
        # Strip to basename — avoid persisting absolute paths that leak FS layout
        # and project names into waste_events.detail_json.
        read_counts[os.path.basename(file_path)] += 1
    repeats = {p: c for p, c in read_counts.items() if c >= REPEATED_READ_THRESHOLD}
    return len(repeats), {"files": [{"path": p, "reads": c} for p, c in repeats.items()]}


# ─── BAD_COMPACT detection (v2-F3) ───────────────────────────────
#
# A "bad compact" is a compact event where the next 1–3 user messages
# reference context that was almost certainly summarised away. We proxy
# this by regex-matching the user text for referential pronouns,
# temporal references, and callbacks to conversation history.

_BAD_COMPACT_SIGNALS = (
    (r"\bthat file\b|\bthe file\b|\bthe one\b", "file_reference"),
    (r"\bwe were\b|\bwe just\b|\bbefore\b|\bearlier\b", "temporal_reference"),
    (r"\bthe error\b|\bit returned\b|\bthe output\b", "output_reference"),
    (r"\blike we discussed\b|\bas you said\b|\byou mentioned\b", "conversation_reference"),
    (r"\bremember\b|\bwe decided\b|\bwe agreed\b", "memory_reference"),
)

_BAD_COMPACT_MIN_CONTEXT_PCT = 60
_BAD_COMPACT_MAX_CANDIDATES = 50
_BAD_COMPACT_LOOKAHEAD = 3
_BAD_COMPACT_MIN_SIGNALS = 2


def _parse_ts(raw):
    """Minimal ISO/epoch timestamp parser (mirrors scanner.parse_timestamp).
    Local copy to avoid importing scanner (would create a circular import)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        clean = raw.replace("Z", "").replace("+00:00", "")
        if "." in clean:
            clean = clean.split(".")[0]
        if "T" in clean:
            from datetime import datetime, timezone
            dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        pass
    return None


def _extract_user_text(obj):
    """Plain-text contents of a user message (empty string if not a user
    message or if content is non-text like a tool_result)."""
    if obj.get("type") != "user":
        return ""
    msg = obj.get("message") or {}
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            # Text blocks: direct user prose
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            # tool_result blocks are NOT the user's words — skip
        return "\n".join(parts)
    return ""


def _iter_jsonl(filepath):
    """Yield parsed JSONL objects. Ignores bad lines / I/O errors."""
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


def detect_bad_compacts(conn, project=None, days=30):
    """Return a list of bad-compact event dicts for the given project (or all
    projects if None). Never raises; returns [] on empty/error."""
    try:
        since = int(time.time()) - (days * 86400)
        sql = ("SELECT session_id, project, timestamp, context_pct_at_event, event_metadata "
               "FROM lifecycle_events "
               "WHERE event_type = 'compact' "
               "  AND context_pct_at_event > ? "
               "  AND timestamp >= ?")
        params = [_BAD_COMPACT_MIN_CONTEXT_PCT, since]
        if project:
            sql += " AND project = ?"
            params.append(project)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(_BAD_COMPACT_MAX_CANDIDATES)
        compacts = conn.execute(sql, params).fetchall()
    except Exception:
        return []

    if not compacts:
        return []

    compiled = [(re.compile(pat, re.IGNORECASE), label)
                for pat, label in _BAD_COMPACT_SIGNALS]
    results = []

    for c in compacts:
        sid = c["session_id"]
        proj = c["project"]
        compact_ts = c["timestamp"]
        compact_pct = c["context_pct_at_event"]

        # Resolve the JSONL file for this session. sessions.source_path is
        # populated by scanner for every row of the session.
        try:
            fp_row = conn.execute(
                "SELECT source_path FROM sessions "
                "WHERE session_id = ? AND source_path IS NOT NULL AND source_path != '' "
                "LIMIT 1",
                (sid,),
            ).fetchone()
        except Exception:
            continue
        if not fp_row or not fp_row[0] or not os.path.isfile(fp_row[0]):
            continue
        filepath = fp_row[0]

        user_msgs = []
        for obj in _iter_jsonl(filepath):
            if obj.get("type") != "user":
                continue
            ts = _parse_ts(obj.get("timestamp") or obj.get("ts"))
            if ts is None or ts <= compact_ts:
                continue
            text = _extract_user_text(obj)
            if not text or not text.strip():
                continue
            user_msgs.append((ts, text))
            if len(user_msgs) >= _BAD_COMPACT_LOOKAHEAD:
                break

        if not user_msgs:
            continue

        combined = "\n".join(m[1] for m in user_msgs)
        signals_found = [label for rx, label in compiled if rx.search(combined)]
        if len(signals_found) < _BAD_COMPACT_MIN_SIGNALS:
            continue

        severity = "high" if len(signals_found) >= 3 else "medium"
        results.append({
            "session_id": sid,
            "project": proj,
            "compact_timestamp": compact_ts,
            "context_pct_at_compact": compact_pct,
            "signals_found": signals_found,
            "sample_message": user_msgs[0][1][:200],
            "severity": severity,
        })

    return results


# ─── Main detection pass ─────────────────────────────────────────

def detect_all(conn=None):
    """Run every detector against the latest scan and refresh waste_events.

    Returns a dict with per-pattern counts for logging.
    """
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True

    # Incremental: only reprocess sessions newer than last waste scan
    last_waste_scan = get_setting(conn, "last_waste_scan")
    last_waste_ts = int(last_waste_scan) if last_waste_scan else 0

    # Only clear waste events on full re-scan (first run or reset)
    if last_waste_ts == 0:
        clear_waste_events(conn)

    # ── 1 & 2: per-file detectors (FLOUNDERING, REPEATED_READS) ──
    if last_waste_ts > 0:
        file_rows = conn.execute(
            "SELECT file_path FROM scan_state WHERE last_scanned >= ? ORDER BY file_path",
            (last_waste_ts,),
        ).fetchall()
    else:
        file_rows = conn.execute("SELECT file_path FROM scan_state ORDER BY file_path").fetchall()
    flounder_count = 0
    repeated_count = 0

    for r in file_rows:
        filepath = r[0]
        if not os.path.isfile(filepath):
            continue
        sid = _file_session_id(filepath)
        if not sid:
            continue

        # Look up project/account/cost from sessions table
        info = conn.execute(
            "SELECT project, account, COALESCE(SUM(cost_usd), 0) AS cost, COUNT(*) AS turns "
            "FROM sessions WHERE session_id = ?",
            (sid,),
        ).fetchone()
        if not info or not info["project"]:
            continue
        project, account = info["project"], info["account"]
        session_cost = info["cost"] or 0
        turn_count = info["turns"] or 0

        tool_calls = list(_iter_assistant_tool_calls(filepath))
        if not tool_calls:
            continue

        # FLOUNDERING
        n_flounder, flounder_detail = _detect_floundering(tool_calls)
        if n_flounder > 0:
            severity = "red" if n_flounder >= 2 else "amber"
            insert_waste_event(
                conn, sid, project, account, "floundering", severity,
                turn_count, session_cost, flounder_detail,
            )
            flounder_count += 1

        # REPEATED_READS
        n_rep, rep_detail = _detect_repeated_reads(tool_calls)
        if n_rep > 0:
            severity = "amber"
            insert_waste_event(
                conn, sid, project, account, "repeated_reads", severity,
                turn_count, session_cost, rep_detail,
            )
            repeated_count += 1

    # ── 3: COST_OUTLIER — sessions whose cost is >3x project 30d avg ──
    outlier_count = 0
    proj_avgs = {
        r[0]: (r[1] or 0) for r in conn.execute(
            "SELECT project, AVG(session_cost) FROM "
            "(SELECT project, session_id, SUM(cost_usd) AS session_cost "
            " FROM sessions "
            " WHERE timestamp >= strftime('%s','now') - 30*86400 "
            " GROUP BY project, session_id) "
            "GROUP BY project"
        ).fetchall()
    }
    session_totals = conn.execute(
        "SELECT session_id, project, account, "
        "       SUM(cost_usd) AS cost, COUNT(*) AS turns "
        "FROM sessions "
        "WHERE timestamp >= strftime('%s','now') - 30*86400 "
        "GROUP BY session_id, project, account"
    ).fetchall()
    for s in session_totals:
        avg = proj_avgs.get(s["project"], 0)
        if avg <= 0:
            continue
        if (s["cost"] or 0) > avg * COST_OUTLIER_MULTIPLIER:
            insert_waste_event(
                conn, s["session_id"], s["project"], s["account"],
                "cost_outlier", "amber", s["turns"], s["cost"],
                {"session_cost": round(s["cost"], 4),
                 "project_avg": round(avg, 4),
                 "multiplier": round(s["cost"] / avg, 1)},
            )
            outlier_count += 1

    # ── 4: DEEP_CONTEXT_NO_COMPACT — >100 turns with zero compaction ──
    deep_count = 0
    deep_sessions = conn.execute(
        "SELECT session_id, project, account, COUNT(*) AS turns, "
        "       SUM(cost_usd) AS cost, MAX(compaction_detected) AS any_compact "
        "FROM sessions "
        "GROUP BY session_id "
        "HAVING turns > ? AND any_compact = 0",
        (DEEP_TURN_THRESHOLD,),
    ).fetchall()
    for s in deep_sessions:
        insert_waste_event(
            conn, s["session_id"], s["project"], s["account"],
            "deep_no_compact", "amber", s["turns"], s["cost"] or 0,
            {"turns": s["turns"]},
        )
        deep_count += 1

    # ── 5: BAD_COMPACT — compacts followed by "dropped context" user messages ──
    bad_compact_count = 0
    try:
        bad_rows = detect_bad_compacts(conn)
        for bc in bad_rows:
            # Look up account for the session (insert_waste_event needs it)
            acct_row = conn.execute(
                "SELECT account, COUNT(*) AS turns, COALESCE(SUM(cost_usd),0) AS cost "
                "FROM sessions WHERE session_id = ?",
                (bc["session_id"],),
            ).fetchone()
            account = (acct_row["account"] if acct_row and acct_row["account"] else "all")
            turns = acct_row["turns"] if acct_row else 0
            cost = float(acct_row["cost"] or 0) if acct_row else 0.0
            insert_waste_event(
                conn, bc["session_id"], bc["project"], account,
                "bad_compact", bc["severity"], turns, cost, bc,
            )
            bad_compact_count += 1
    except Exception as e:
        print(f"[waste_patterns] bad_compact detection error: {e}", file=__import__("sys").stderr)

    # Record scan timestamp for incremental next run
    set_setting(conn, "last_waste_scan", str(int(time.time())))
    conn.commit()

    summary = {
        "floundering": flounder_count,
        "repeated_reads": repeated_count,
        "cost_outliers": outlier_count,
        "deep_no_compact": deep_count,
        "bad_compacts": bad_compact_count,
    }

    if should_close:
        conn.close()
    return summary


def waste_summary_by_project(conn, days=7):
    """Aggregate waste_events by project for the last N days. Used by
    analyzer.full_analysis → /api/data → dashboard UI."""
    since = int(__import__("time").time()) - (days * 86400)
    rows = conn.execute(
        "SELECT project, pattern_type, COUNT(*) AS n, "
        "       SUM(token_cost) AS cost "
        "FROM waste_events WHERE detected_at >= ? "
        "GROUP BY project, pattern_type",
        (since,),
    ).fetchall()
    result = defaultdict(lambda: {
        "floundering_sessions": 0,
        "repeated_read_sessions": 0,
        "cost_outliers": 0,
        "deep_no_compact": 0,
        "bad_compacts": 0,
        "bad_compact_severity": None,
        "total_waste_cost_est": 0.0,
    })
    # Severity needs a second pass — compute max severity per project
    sev_rows = conn.execute(
        "SELECT project, MAX(CASE severity WHEN 'high' THEN 3 WHEN 'red' THEN 3 "
        "                              WHEN 'medium' THEN 2 WHEN 'amber' THEN 2 ELSE 1 END) AS s "
        "FROM waste_events WHERE pattern_type='bad_compact' AND detected_at >= ? "
        "GROUP BY project",
        (since,),
    ).fetchall()
    sev_by_proj = {r["project"] or "Other": r["s"] for r in sev_rows}

    for r in rows:
        proj = r["project"] or "Other"
        pt = r["pattern_type"]
        n = r["n"] or 0
        cost = r["cost"] or 0
        if pt == "floundering":
            result[proj]["floundering_sessions"] = n
            result[proj]["total_waste_cost_est"] += cost
        elif pt == "repeated_reads":
            result[proj]["repeated_read_sessions"] = n
        elif pt == "cost_outlier":
            result[proj]["cost_outliers"] = n
        elif pt == "deep_no_compact":
            result[proj]["deep_no_compact"] = n
        elif pt == "bad_compact":
            result[proj]["bad_compacts"] = n
            s = sev_by_proj.get(proj, 1)
            result[proj]["bad_compact_severity"] = "high" if s >= 3 else ("medium" if s == 2 else "low")
    return {p: dict(v) for p, v in result.items()}
