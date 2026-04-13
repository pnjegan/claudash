#!/usr/bin/env python3
"""Claudash MCP server — exposes dashboard data to Claude Code via the
Model Context Protocol (JSON-RPC 2.0 over stdio).

Claude Code loads MCP servers from ~/.claude/settings.json:

    {
      "mcpServers": {
        "claudash": {
          "command": "python3",
          "args": ["/absolute/path/to/claudash/mcp_server.py"]
        }
      }
    }

Supported methods:
  initialize                     — handshake
  notifications/initialized      — post-handshake ack (no response)
  tools/list                     — return the 5 tool schemas
  tools/call                     — invoke one of the tools

Tools:
  claudash_summary        — per-account usage rollup
  claudash_project        — detailed project metrics
  claudash_window         — current 5-hour window status
  claudash_insights       — active actionable insights
  claudash_action_center  — top 3 recommended actions

The server reads SQLite directly (no HTTP) so it does NOT need the web
server to be running. Works offline and in cron jobs.

Run `python3 mcp_server.py test` to sanity-check without launching the
JSON-RPC loop.
"""

import json
import os
import sys
import time

# Ensure we can import the rest of the Claudash package regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from db import (  # noqa: E402
    init_db, get_conn, get_session_count, get_accounts_config, get_insights,
)
from analyzer import (  # noqa: E402
    account_metrics, project_metrics, window_intelligence,
    compaction_metrics, subagent_metrics, daily_budget_metrics,
)


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "claudash"
SERVER_VERSION = "1.0.0"


# ─── Tool implementations ────────────────────────────────────────

def _tool_claudash_summary(args):
    conn = get_conn()
    try:
        accounts_cfg = get_accounts_config(conn)
        out = []
        for acct_id, info in accounts_cfg.items():
            am = account_metrics(conn, acct_id)
            wi = window_intelligence(conn, acct_id)
            projects = project_metrics(conn, acct_id)
            top = projects[0]["name"] if projects else None
            out.append({
                "account_id": acct_id,
                "label": info["label"],
                "plan": info.get("plan", "max"),
                "window_pct": wi.get("window_pct", 0),
                "subscription_roi": am.get("subscription_roi", 0),
                "cache_hit_rate": am.get("cache_hit_rate", 0),
                "sessions_today": am.get("sessions_today", 0),
                "total_cost_30d_usd": am.get("total_cost_30d", 0),
                "top_project": top,
            })
        return {"accounts": out, "generated_at": int(time.time())}
    finally:
        conn.close()


def _tool_claudash_project(args):
    project_name = (args or {}).get("project_name") or ""
    if not project_name:
        return {"error": "project_name is required"}
    conn = get_conn()
    try:
        projects = project_metrics(conn, "all")
        match = next((p for p in projects if p["name"].lower() == project_name.lower()), None)
        if not match:
            return {"error": f"project '{project_name}' not found",
                    "available": [p["name"] for p in projects]}
        # Compaction metric for just this project
        comp_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE project=? AND compaction_detected=1",
            (match["name"],),
        ).fetchone()
        comp_count = comp_rows["n"] if comp_rows else 0
        # Average turns per session for this project
        turn_row = conn.execute(
            "SELECT AVG(turns) AS avg_turns FROM "
            "(SELECT session_id, COUNT(*) AS turns FROM sessions "
            " WHERE project=? GROUP BY session_id)",
            (match["name"],),
        ).fetchone()
        avg_turns = round(turn_row["avg_turns"] or 0, 1) if turn_row else 0
        return {
            "project": match["name"],
            "account": match.get("account_label") or match.get("account"),
            "cost_30d_usd": match.get("cost_usd_30d", 0),
            "session_count": match.get("session_count", 0),
            "total_tokens": match.get("total_tokens", 0),
            "cache_hit_rate": match.get("cache_hit_rate", 0),
            "dominant_model": match.get("dominant_model", ""),
            "avg_turns_per_session": avg_turns,
            "compaction_events_30d": comp_count,
            "wow_change_pct": match.get("wow_change_pct", 0),
            "rightsizing_savings_usd": match.get("rightsizing_savings", 0),
        }
    finally:
        conn.close()


def _tool_claudash_window(args):
    conn = get_conn()
    try:
        accounts_cfg = get_accounts_config(conn)
        out = []
        for acct_id, info in accounts_cfg.items():
            wi = window_intelligence(conn, acct_id)
            pct = wi.get("window_pct", 0)
            exhaust_epoch = wi.get("predicted_limit_time")
            exhaust_iso = None
            if exhaust_epoch:
                exhaust_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime(exhaust_epoch))
            out.append({
                "account_id": acct_id,
                "label": info["label"],
                "pct_used": pct,
                "tokens_used": wi.get("total_tokens", 0),
                "tokens_limit": wi.get("tokens_limit", 0),
                "burn_rate_per_min": wi.get("burn_per_minute", 0),
                "minutes_to_limit": wi.get("minutes_to_limit"),
                "predicted_exhaust_utc": exhaust_iso,
                "safe_to_start_heavy": wi.get("safe_for_heavy_session", pct < 50),
                "best_start_hour_utc": wi.get("best_start_hour"),
            })
        return {"accounts": out, "generated_at": int(time.time())}
    finally:
        conn.close()


def _tool_claudash_insights(args):
    conn = get_conn()
    try:
        rows = get_insights(conn, account=None, dismissed=0, limit=50)
        priority_map = {
            "red": "critical", "window_risk": "critical", "cache_spike": "critical",
            "budget_exceeded": "critical", "floundering_detected": "critical",
            "window_combined_risk": "critical", "session_expiry": "high",
            "amber": "warning", "model_waste": "warning",
            "compaction_gap": "warning", "budget_warning": "warning",
            "subagent_cost_spike": "warning", "pro_messages_low": "warning",
            "green": "info", "roi_milestone": "info", "cost_target": "info",
            "blue": "info", "heavy_day": "info", "best_window": "info",
        }
        out = []
        for r in rows:
            itype = r["insight_type"]
            out.append({
                "id": r["id"],
                "type": itype,
                "priority": priority_map.get(itype, "info"),
                "project": r["project"],
                "message": r["message"],
                "created_at": r["created_at"],
            })
        return {"insights": out, "total": len(out)}
    finally:
        conn.close()


def _tool_claudash_action_center(args):
    """Return up to 3 ranked, actionable recommendations."""
    conn = get_conn()
    try:
        actions = []

        # Rank 1: budget exceeded
        dbm = daily_budget_metrics(conn, "all")
        for acct_id, b in dbm.items():
            if b.get("has_budget") and b["today_cost"] > b["budget_usd"]:
                actions.append({
                    "priority": 1,
                    "title": f"{acct_id} over daily budget",
                    "why": f"${b['today_cost']:.2f} spent vs ${b['budget_usd']:.2f} limit",
                    "action": "Pause heavy runs or switch to Sonnet until midnight UTC",
                    "impact": f"${b['today_cost'] - b['budget_usd']:.2f} over budget",
                })

        # Rank 2: floundering sessions
        flounder_rows = conn.execute(
            "SELECT project, COUNT(*) AS n, SUM(token_cost) AS cost "
            "FROM waste_events WHERE pattern_type='floundering' "
            "  AND detected_at >= strftime('%s','now') - 7*86400 "
            "GROUP BY project ORDER BY cost DESC LIMIT 3"
        ).fetchall()
        for r in flounder_rows:
            actions.append({
                "priority": 2,
                "title": f"{r['project']} floundering sessions",
                "why": f"Claude stuck in retry loops on {r['n']} session(s)",
                "action": "Check session logs for permission/path errors; add explicit bash error handling",
                "impact": f"~${(r['cost'] or 0):.2f} at risk in retry loops",
            })

        # Rank 3: Opus overuse
        from analyzer import model_rightsizing
        rs = model_rightsizing(conn, "all")
        for s in rs[:2]:
            if s["monthly_savings"] > 5:
                actions.append({
                    "priority": 3,
                    "title": f"Opus overuse in {s['project']}",
                    "why": f"Avg output is {s['avg_output_tokens']} tokens — Sonnet is sufficient",
                    "action": f"Switch {s['project']} default model to claude-sonnet",
                    "impact": f"~${s['monthly_savings']:.2f}/mo savings",
                })

        # Rank 4 (fallback): compaction gap
        comp = compaction_metrics(conn, "all")
        if comp.get("sessions_needing_compact", 0) > 0 and len(actions) < 3:
            actions.append({
                "priority": 4,
                "title": "Context rot risk",
                "why": f"{comp['sessions_needing_compact']} sessions hit 80% context without /compact",
                "action": "Run /compact earlier in long sessions to preserve quality",
                "impact": "Prevents quality degradation + saves tokens on later turns",
            })

        actions.sort(key=lambda a: a["priority"])
        return {"actions": actions[:3], "generated_at": int(time.time())}
    finally:
        conn.close()


# ─── Tool registry ───────────────────────────────────────────────

TOOLS = [
    {
        "name": "claudash_summary",
        "description": "Get current Claude usage summary from Claudash (all accounts: window burn, ROI, cache hit rate, sessions today, top project).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_claudash_summary,
    },
    {
        "name": "claudash_project",
        "description": "Get detailed usage metrics for a specific Claude project (cost, sessions, cache hit rate, avg turns, compaction, dominant model, week-over-week change).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "The project name as shown in Claudash (e.g. 'WikiLoop', 'Tidify').",
                },
            },
            "required": ["project_name"],
            "additionalProperties": False,
        },
        "handler": _tool_claudash_project,
    },
    {
        "name": "claudash_window",
        "description": "Check the current Claude 5-hour window burn status for every account — percentage used, burn rate, predicted exhaust time, and whether it's safe to start a heavy session.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_claudash_window,
    },
    {
        "name": "claudash_insights",
        "description": "Get active actionable insights about Claude usage patterns (cache spikes, model waste, window risk, ROI milestones, waste patterns).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_claudash_insights,
    },
    {
        "name": "claudash_action_center",
        "description": "Get the top 3 recommended actions to optimize Claude usage right now, ranked by priority. Each action has why/action/impact fields.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_claudash_action_center,
    },
]


# ─── JSON-RPC dispatch ───────────────────────────────────────────

def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return _result(req_id, {
            "tools": [
                {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                for t in TOOLS
            ]
        })

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if not tool:
            return _error(req_id, -32601, f"Unknown tool: {name}")
        try:
            result = tool["handler"](args)
            return _result(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str, indent=2)}],
            })
        except Exception as e:
            return _error(req_id, -32000, f"Tool execution failed: {e}")

    if req_id is None:
        return None  # unknown notification
    return _error(req_id, -32601, f"Method not found: {method}")


def run_stdio():
    """Read JSON-RPC requests from stdin line by line, write responses to
    stdout. Each message is one JSON object on its own line."""
    init_db()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            err = _error(None, -32700, "Parse error")
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
            sys.stdout.flush()


def run_test():
    """Offline smoke test. Exercises each tool and prints a single OK line."""
    init_db()
    errors = []
    for tool in TOOLS:
        try:
            if tool["name"] == "claudash_project":
                # Needs an arg — pick the first real project
                conn = get_conn()
                row = conn.execute(
                    "SELECT project FROM sessions WHERE project IS NOT NULL "
                    "GROUP BY project ORDER BY COUNT(*) DESC LIMIT 1"
                ).fetchone()
                conn.close()
                arg = {"project_name": row[0]} if row else {"project_name": "test"}
                result = tool["handler"](arg)
            else:
                result = tool["handler"]({})
            if not isinstance(result, dict):
                errors.append(f"{tool['name']}: did not return dict")
        except Exception as e:
            errors.append(f"{tool['name']}: {e}")
    if errors:
        print("MCP server FAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print(f"MCP server OK — {len(TOOLS)} tools registered")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        run_stdio()


if __name__ == "__main__":
    main()
