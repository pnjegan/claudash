#!/usr/bin/env python3
"""Claudash — CLI entry point."""

import sys
import os
import csv
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import VPS_IP, VPS_PORT
from db import (
    init_db, get_conn, get_insights, get_session_count, get_db_size_mb,
    get_accounts_config, get_claude_ai_accounts_all, get_latest_claude_ai_snapshot,
    get_setting, get_project_map_config, sync_project_map_from_config,
)


HELP_TEXT = """
Claudash v1.0 — personal Claude usage dashboard

Commands:
  dashboard     Start dashboard server on :8080 (127.0.0.1 only)
  scan          Scan JSONL files for new sessions (incremental)
  scan --reprocess
                Re-tag every existing session using the current
                PROJECT_MAP. Useful after adding projects to config.py.
  show-other    List all source paths of sessions currently tagged 'Other'
  stats         Print per-account stats table
  insights      Show active insights
  window        Show 5-hour window status
  export        Export last 30 days to CSV
  keys          Print dashboard_key and sync_token (sensitive — keep private)
  claude-ai     Show claude.ai browser tracking status
  claude-ai --sync-token          Print sync token (for tools/mac-sync.py)
  claude-ai --setup <account_id>  Paste a claude.ai session key interactively

Paste the dashboard_key into the browser prompt the first time an admin
button fails — it's saved to localStorage and reused.

Local:      http://localhost:8080
SSH tunnel: ssh -L 8080:localhost:8080 user@YOUR_VPS_IP
"""
from scanner import scan_all, start_periodic_scan
from analyzer import (
    account_metrics, project_metrics, window_intelligence,
    trend_metrics, compaction_metrics, model_rightsizing,
)
from insights import generate_insights
from server import start_server

from claude_ai_tracker import (
    poll_all as poll_claude_ai, start_periodic_poll as start_claude_ai_poll,
    setup_account as tracker_setup_account,
)


def cmd_dashboard():
    init_db()
    rows = scan_all()

    conn = get_conn()
    n = generate_insights(conn)
    total = get_session_count(conn)
    db_mb = get_db_size_mb()
    accounts = get_accounts_config(conn)
    conn.close()

    n_accts = f"{len(accounts)} configured"
    db_str = f"{db_mb}MB"

    print(flush=True)
    print("  ╔══════════════════════════════╗", flush=True)
    print("  ║  Claudash v1.0               ║", flush=True)
    print("  ╠══════════════════════════════╣", flush=True)
    print(f"  ║  Records  : {total:<17,}║", flush=True)
    print(f"  ║  Accounts : {n_accts:<17s}║", flush=True)
    print(f"  ║  DB       : {db_str:<17s}║", flush=True)
    print(f"  ║  URL      : {'localhost:8080':<17s}║", flush=True)
    print("  ╚══════════════════════════════╝", flush=True)
    print(flush=True)
    if VPS_IP and VPS_IP != "localhost":
        print(f"  SSH tunnel: ssh -L 8080:localhost:8080 user@{VPS_IP}", flush=True)
    else:
        print("  SSH tunnel (if remote): ssh -L 8080:localhost:8080 user@YOUR_VPS_IP", flush=True)
    print("  Then open http://localhost:8080 in your browser.", flush=True)
    print(flush=True)

    start_periodic_scan(interval_seconds=300)
    poll_claude_ai()
    start_claude_ai_poll(interval_seconds=300)

    start_server(port=8080)


def cmd_scan():
    init_db()
    rows = scan_all()
    conn = get_conn()
    n = generate_insights(conn)
    conn.close()
    print(f"Scan complete: {rows} new rows (incremental), {n} insights generated")


def cmd_stats():
    init_db()
    scan_all()
    conn = get_conn()
    ACCOUNTS = get_accounts_config(conn)

    print()
    for acct_key, acct_info in ACCOUNTS.items():
        am = account_metrics(conn, acct_key)
        projs = project_metrics(conn, acct_key)

        label = acct_info["label"]
        plan = acct_info.get("plan", "max").upper()
        cost = acct_info.get("monthly_cost_usd", 0)
        roi = am.get("subscription_roi", 0)

        print(f"  {label} ({plan} ${cost}/mo) — ROI: {roi}x")
        print(f"  {'Project':<15} {'Tokens':>12} {'Cost 30d':>10} {'Cache%':>8} {'Model':<14} {'Sessions':>8}")
        print(f"  {'-' * 73}")

        for p in projs:
            model_short = p["dominant_model"].replace("claude-", "")
            print(
                f"  {p['name']:<15} {p['total_tokens']:>12,} "
                f"${p['cost_usd_30d']:>8.2f} {p['cache_hit_rate']:>7.1f}% "
                f"{model_short:<14} {p['session_count']:>8}"
            )

        print(f"  {'-' * 73}")
        print(f"  {'TOTAL':<15} {'':>12} ${am['total_cost_30d']:>8.2f} {am['cache_hit_rate']:>7.1f}%")
        print(f"  Sessions today: {am['sessions_today']}  |  Cache ROI: ${am['cache_roi_usd']:.2f}")
        print()

    print("  Run `python3 cli.py keys` to retrieve the dashboard_key (never printed here).")
    print()

    conn.close()


def cmd_insights():
    init_db()
    conn = get_conn()
    generate_insights(conn)

    insights = get_insights(conn, dismissed=0)
    conn.close()

    if not insights:
        print("No active insights.")
        return

    print(f"\n  Active Insights ({len(insights)})")
    print(f"  {'=' * 70}")

    colors = {
        "model_waste": "AMBER", "cache_spike": "RED", "compaction_gap": "AMBER",
        "cost_target": "GREEN", "window_risk": "RED", "roi_milestone": "GREEN",
        "heavy_day": "BLUE", "best_window": "BLUE",
    }

    for i in insights:
        itype = i["insight_type"]
        color = colors.get(itype, "INFO")
        dt = datetime.fromtimestamp(i["created_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  [{color:>5}] {dt}  {i['message']}")

    print()


def cmd_window():
    init_db()
    conn = get_conn()
    ACCOUNTS = get_accounts_config(conn)

    print()
    for acct_key, acct_info in ACCOUNTS.items():
        wm = window_intelligence(conn, acct_key)
        label = acct_info["label"]
        limit = acct_info.get("window_token_limit", 1_000_000)

        ws = datetime.fromtimestamp(wm["window_start"], tz=timezone.utc).strftime("%H:%M UTC")
        we = datetime.fromtimestamp(wm["window_end"], tz=timezone.utc).strftime("%H:%M UTC")

        pct = wm["window_pct"]
        status = "OK"
        if pct > 80:
            status = "DANGER"
        elif pct > 50:
            status = "CAUTION"

        print(f"  {label}")
        print(f"  Window: {ws} - {we}")
        print(f"  Used: {wm['total_tokens']:,} / {limit:,} ({pct:.1f}%) [{status}]")

        if wm["minutes_to_limit"]:
            print(f"  Predicted exhaust: ~{wm['minutes_to_limit']} min")
        if wm.get("burn_per_minute", 0) > 0:
            print(f"  Burn rate: {int(wm['burn_per_minute']):,} tok/min")

        safe = "Yes" if wm.get("safe_for_heavy_session") else "No"
        print(f"  Safe for heavy session: {safe}")
        print(f"  Best start hour (UTC): {wm.get('best_start_hour', '?')}:00")

        history = wm.get("window_history", [])
        if history:
            avg = sum(w.get("pct_used", 0) for w in history) / len(history)
            print(f"  Last {len(history)} windows avg: {avg:.1f}%")

        print()

    conn.close()


def cmd_export():
    init_db()
    conn = get_conn()
    since = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
    rows = conn.execute(
        "SELECT * FROM sessions WHERE timestamp >= ? ORDER BY timestamp", (since,)
    ).fetchall()
    conn.close()

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_export.csv")
    with open(outpath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "session_id", "timestamp", "datetime", "project", "account", "model",
            "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
            "cost_usd", "source_path", "compaction_detected",
        ])
        for r in rows:
            dt = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([
                r["session_id"], r["timestamp"], dt, r["project"], r["account"], r["model"],
                r["input_tokens"], r["output_tokens"], r["cache_read_tokens"], r["cache_creation_tokens"],
                r["cost_usd"], r["source_path"], r["compaction_detected"],
            ])

    print(f"Exported {len(rows)} rows to {outpath}")


def cmd_keys():
    """Print dashboard_key and sync_token. Sensitive — do not paste into
    screenshots, chat transcripts, or shared terminals."""
    init_db()
    conn = get_conn()
    dk = get_setting(conn, "dashboard_key") or "(not set)"
    st = get_setting(conn, "sync_token") or "(not set)"
    conn.close()
    print()
    print("  ⚠  These values grant full write access to your dashboard.")
    print("     Keep them private. Do not share, screenshot, or commit them.")
    print()
    print(f"  dashboard_key : {dk}")
    print(f"     → paste into the browser prompt when an admin button returns 401")
    print()
    print(f"  sync_token    : {st}")
    print(f"     → paste into tools/mac-sync.py SYNC_TOKEN variable")
    print()


def cmd_claude_ai():
    """Show claude.ai browser tracking status for all accounts."""
    init_db()

    # Handle --sync-token: print ONLY the raw token, nothing else
    if len(sys.argv) >= 3 and sys.argv[2] == "--sync-token":
        conn = get_conn()
        token = get_setting(conn, "sync_token")
        conn.close()
        print(token)
        return

    conn = get_conn()
    accounts = get_claude_ai_accounts_all(conn)

    if not accounts:
        print("No claude.ai accounts configured.")
        conn.close()
        return

    print()
    for a in accounts:
        aid = a["account_id"]
        label = a.get("label", aid)
        status = a.get("status", "unconfigured")
        plan = a.get("plan", "max")
        last_polled = a.get("last_polled")

        poll_ago = ""
        if last_polled:
            diff = int(time.time()) - last_polled
            if diff < 60:
                poll_ago = f"{diff}s ago"
            elif diff < 3600:
                poll_ago = f"{diff // 60}m ago"
            else:
                poll_ago = f"{diff // 3600}h ago"
        else:
            poll_ago = "never"

        snap = get_latest_claude_ai_snapshot(conn, aid)

        if status == "unconfigured":
            print(f"  {label}: unconfigured")
        elif status == "expired":
            print(f"  {label}: SESSION EXPIRED | last polled {poll_ago}")
        elif status == "active" and snap:
            if plan == "pro" and snap.get("messages_limit", 0) > 0:
                print(f"  {label}: {snap['messages_used']}/{snap['messages_limit']} messages | last polled {poll_ago} | ACTIVE")
            else:
                print(f"  {label}: {snap.get('pct_used', 0):.1f}% window used | last polled {poll_ago} | ACTIVE")
        else:
            err = a.get("last_error", "unknown")
            print(f"  {label}: {status} | last polled {poll_ago} | {err}")

    # Handle --setup flag
    if len(sys.argv) >= 4 and sys.argv[2] == "--setup":
        target_id = sys.argv[3]
        print(f"\n  Setting up claude.ai tracking for '{target_id}'...")
        session_key = input("  Paste session key (sk-ant-sid01-...): ").strip()
        if not session_key:
            print("  Cancelled — no session key provided.")
        else:
            result = tracker_setup_account(target_id, session_key)
            if result["success"]:
                print(f"  Connected: {result['label']}, {result['pct_used']:.1f}% window used")
            else:
                print(f"  Error: {result['error']}")

    print()
    conn.close()


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print(HELP_TEXT.format(vps_ip=VPS_IP))
        sys.exit(0)

    cmd = sys.argv[1].lower()
    commands = {
        "dashboard": cmd_dashboard,
        "scan": cmd_scan,
        "stats": cmd_stats,
        "insights": cmd_insights,
        "window": cmd_window,
        "export": cmd_export,
        "keys": cmd_keys,
        "claude-ai": cmd_claude_ai,
    }

    handler = commands.get(cmd)
    if handler:
        handler()
    else:
        print(f"Unknown command: {cmd}")
        print(HELP_TEXT.format(vps_ip=VPS_IP))
        sys.exit(1)


if __name__ == "__main__":
    main()
