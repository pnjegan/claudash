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

import json
import os
import sqlite3
from collections import defaultdict

from db import get_conn, insert_waste_event, clear_waste_events


# ─── Parameters ──────────────────────────────────────────────────

FLOUNDER_THRESHOLD = 4           # consecutive same-tool calls
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

def _detect_floundering(tool_calls):
    """Return (count, detail) for FLOUNDERING — runs of >=4 consecutive
    identical tool names. Detail lists the runs. `tool_calls` is an
    iterable of (turn, name, input) tuples."""
    runs = []
    current_name = None
    current_len = 0
    current_start = 0
    for turn, name, _inp in tool_calls:
        if name == current_name:
            current_len += 1
        else:
            if current_name and current_len >= FLOUNDER_THRESHOLD:
                runs.append({"tool": current_name, "length": current_len, "start_turn": current_start})
            current_name = name
            current_len = 1
            current_start = turn
    if current_name and current_len >= FLOUNDER_THRESHOLD:
        runs.append({"tool": current_name, "length": current_len, "start_turn": current_start})
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
        read_counts[file_path] += 1
    repeats = {p: c for p, c in read_counts.items() if c >= REPEATED_READ_THRESHOLD}
    return len(repeats), {"files": [{"path": p, "reads": c} for p, c in repeats.items()]}


# ─── Main detection pass ─────────────────────────────────────────

def detect_all(conn=None):
    """Run every detector against the latest scan and refresh waste_events.

    Returns a dict with per-pattern counts for logging.
    """
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True

    # Wipe the table — we recompute from scratch so stale events never linger.
    clear_waste_events(conn)

    # ── 1 & 2: per-file detectors (FLOUNDERING, REPEATED_READS) ──
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

    conn.commit()

    summary = {
        "floundering": flounder_count,
        "repeated_reads": repeated_count,
        "cost_outliers": outlier_count,
        "deep_no_compact": deep_count,
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
        "total_waste_cost_est": 0.0,
    })
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
    return {p: dict(v) for p, v in result.items()}
