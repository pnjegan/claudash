#!/usr/bin/env python3
"""Claudash — CLI entry point."""

import sys
import os
import csv
import json
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _version import VERSION
from config import VPS_IP, VPS_PORT
from db import (
    init_db, get_conn, get_insights, get_session_count, get_db_size_mb,
    get_accounts_config, get_claude_ai_accounts_all, get_latest_claude_ai_snapshot,
    get_setting, set_setting, get_project_map_config, sync_project_map_from_config,
)


HELP_TEXT = f"""
Claudash v{VERSION} — personal Claude usage dashboard

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
  waste         Run waste-pattern detection and print summary
  fixes         List all recorded fixes with current status
  fix add       Interactively record a new fix (captures baseline)
  measure <id>  Capture current metrics for a fix, compute delta, print
                a plan-aware verdict and share card
  mcp           Print MCP server settings.json snippet + run a quick test
  keys          Print dashboard_key and sync_token (sensitive — keep private)
  keys --rotate Regenerate dashboard_key (invalidates existing browser sessions)
  init          First-run setup wizard (3 questions, then start)
  claude-ai     Show claude.ai browser tracking status
  sync-daemon   Auto-sync browser data every 5 minutes (background)
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
    compute_efficiency_score,
)
from insights import generate_insights
from server import start_server

from claude_ai_tracker import (
    poll_all as poll_claude_ai, start_periodic_poll as start_claude_ai_poll,
    setup_account as tracker_setup_account,
)


def cmd_dashboard():
    import argparse
    parser = argparse.ArgumentParser(prog="claudash dashboard", add_help=False)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-init", action="store_true")
    args = parser.parse_args(sys.argv[2:])

    MAX_RESTARTS = 5
    restart_count = 0
    restart_delay = 5  # seconds

    while restart_count <= MAX_RESTARTS:
        try:
            _run_dashboard(args.port, args.no_browser, args.skip_init)
            break  # clean exit
        except KeyboardInterrupt:
            print("\nClaudash stopped.")
            break
        except Exception as e:
            restart_count += 1
            if restart_count > MAX_RESTARTS:
                print(f"Claudash crashed {MAX_RESTARTS} times. Giving up.")
                print(f"Last error: {e}")
                print(f"Check logs: tail /tmp/claudash.log")
                break
            print(f"Claudash crashed (attempt {restart_count}/{MAX_RESTARTS}): {e}")
            print(f"Restarting in {restart_delay} seconds...")
            time.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 60)


def _run_dashboard(port=8080, no_browser=False, skip_init=False):
    init_db()
    rows = scan_all()

    conn = get_conn()
    n = generate_insights(conn)
    total = get_session_count(conn)
    db_mb = get_db_size_mb()
    accounts = get_accounts_config(conn)

    # First-run detection: no sessions or only default account label
    accounts_customized = any(
        v.get("label") != "Personal (Max)" for v in accounts.values()
    )
    if not skip_init and (total == 0 or (len(accounts) <= 1 and not accounts_customized)):
        conn.close()
        print("First run detected. Running setup wizard...", flush=True)
        print("(Skip with: python3 cli.py dashboard --skip-init)", flush=True)
        print(flush=True)
        cmd_init()
        return

    conn.close()

    url_str = f"localhost:{port}"
    n_accts = f"{len(accounts)} configured"
    db_str = f"{db_mb}MB"

    print(flush=True)
    print("  ╔══════════════════════════════╗", flush=True)
    print(f"  ║  Claudash v{VERSION:<17s}║", flush=True)
    print("  ╠══════════════════════════════╣", flush=True)
    print(f"  ║  Records  : {total:<17,}║", flush=True)
    print(f"  ║  Accounts : {n_accts:<17s}║", flush=True)
    print(f"  ║  DB       : {db_str:<17s}║", flush=True)
    print(f"  ║  URL      : {url_str:<17s}║", flush=True)
    print("  ╚══════════════════════════════╝", flush=True)
    print(flush=True)
    def _is_headless():
        import platform as _plat
        if _plat.system() in ("Windows", "Darwin"):
            return False
        return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")

    if not no_browser and not _is_headless():
        import threading, webbrowser
        threading.Thread(
            target=lambda: (time.sleep(1.5), webbrowser.open(f"http://localhost:{port}")),
            daemon=True,
        ).start()

    if _is_headless():
        print("  Headless server detected — no browser auto-open", flush=True)
        print(f"  To view dashboard, run on your local machine:", flush=True)
        vps_host = VPS_IP if VPS_IP and VPS_IP != "localhost" else "YOUR_VPS_IP"
        print(f"    ssh -L {port}:localhost:{port} user@{vps_host}", flush=True)
        print(f"  Then open: http://localhost:{port}", flush=True)
    elif VPS_IP and VPS_IP != "localhost":
        print(f"  SSH tunnel: ssh -L {port}:localhost:{port} user@{VPS_IP}", flush=True)
        print(f"  Then open http://localhost:{port} in your browser.", flush=True)
    else:
        print(f"  Open http://localhost:{port} in your browser.", flush=True)
    print(flush=True)

    start_periodic_scan(interval_seconds=300)
    poll_claude_ai()
    start_claude_ai_poll(interval_seconds=300)

    start_server(port=port)


def cmd_init():
    """Interactive first-run setup wizard."""
    init_db()
    conn = get_conn()

    print(flush=True)
    print("  Claudash Setup Wizard", flush=True)
    print("  " + "-" * 40, flush=True)
    print("  Answer 3 questions to configure your dashboard.", flush=True)
    print(flush=True)

    # Question 1: Plan type
    print("  1. What Claude plan are you on?", flush=True)
    print("     [1] Max  ($100/mo — 1M tokens/5hr window)", flush=True)
    print("     [2] Pro  ($20/mo  — message-based limits)", flush=True)
    print("     [3] API  (pay per token)", flush=True)
    print("     [4] Team (API with org billing)", flush=True)
    try:
        choice = input("     Enter 1-4: ").strip()
    except EOFError:
        choice = "1"
    plan_map = {
        "1": ("max", 100.0, 1_000_000),
        "2": ("pro", 20.0, 0),
        "3": ("api", 0.0, 0),
        "4": ("api", 0.0, 0),
    }
    plan, cost, tokens = plan_map.get(choice, ("max", 100.0, 1_000_000))

    # Question 1b: Monthly cost (if API)
    if plan == "api":
        try:
            cost_input = input("     Monthly API spend (approx $): ").strip()
            cost = float(cost_input)
        except (ValueError, EOFError):
            cost = 0.0

    # Question 2: Show detected projects
    print(flush=True)
    print("  2. Detected Claude Code projects:", flush=True)
    projects = conn.execute(
        "SELECT project, COUNT(*) as sessions "
        "FROM sessions GROUP BY project "
        "ORDER BY sessions DESC LIMIT 10"
    ).fetchall()

    if projects:
        for i, p in enumerate(projects, 1):
            print(f"     {i}. {p['project']} ({p['sessions']} sessions)", flush=True)
        print("     These were auto-detected from your JSONL files.", flush=True)
        print("     Add custom project names in config.py PROJECT_MAP", flush=True)
    else:
        print("     No sessions found yet.", flush=True)
        print("     Run 'python3 cli.py scan' after using Claude Code.", flush=True)

    # Question 3: Account name
    print(flush=True)
    print("  3. What should we call this account?", flush=True)
    print("     (e.g. 'Personal', 'Work', 'My Mac')", flush=True)
    try:
        name = input("     Account name: ").strip() or "Personal"
    except EOFError:
        name = "Personal"

    # Save to DB
    acct_row = conn.execute("SELECT account_id FROM accounts LIMIT 1").fetchone()
    if acct_row:
        conn.execute(
            "UPDATE accounts SET label=?, plan=?, monthly_cost_usd=?, "
            "window_token_limit=? WHERE account_id=?",
            (f"{name} ({plan.title()})", plan, cost, tokens, acct_row["account_id"]),
        )
        conn.commit()

    print(flush=True)
    print("  Dashboard configured!", flush=True)
    print(f"    Account: {name} ({plan.title()})", flush=True)
    print(f"    Plan cost: ${cost}/mo", flush=True)
    if tokens:
        print(f"    Window: {tokens:,} tokens per 5 hours", flush=True)
    print(flush=True)
    print("  Starting dashboard...", flush=True)
    print(flush=True)
    conn.close()

    # Auto-start dashboard after init
    cmd_dashboard()


def cmd_scan():
    # `scan --reprocess` re-tags every existing session row from source JSONL
    # without re-reading file offsets. It's the fix for "I added a new project
    # to config.py but my old sessions still say Other".
    if "--reprocess" in sys.argv:
        cmd_scan_reprocess()
        return
    init_db()
    rows = scan_all()
    conn = get_conn()
    n = generate_insights(conn)
    # Waste-pattern detection after every scan
    try:
        from waste_patterns import detect_all as _detect_waste
        waste_summary = _detect_waste(conn)
    except Exception as e:
        waste_summary = {"error": str(e)}
    conn.close()
    print(f"Scan complete: {rows} new rows (incremental), {n} insights generated")
    if isinstance(waste_summary, dict) and "error" not in waste_summary:
        parts = [f"{k}={v}" for k, v in waste_summary.items() if v]
        if parts:
            print(f"Waste patterns: {', '.join(parts)}")


def cmd_waste():
    """Run waste-pattern detection standalone and print a summary."""
    init_db()
    conn = get_conn()
    from waste_patterns import detect_all as _detect_waste
    summary = _detect_waste(conn)
    print()
    print("  Waste patterns detected (last scan)")
    print(f"  {'-' * 40}")
    for k, v in summary.items():
        print(f"  {k:<20} {v:>6}")
    print()
    rows = conn.execute(
        "SELECT project, pattern_type, COUNT(*) AS n, SUM(token_cost) AS cost "
        "FROM waste_events GROUP BY project, pattern_type ORDER BY cost DESC LIMIT 10"
    ).fetchall()
    if rows:
        print("  Top waste events by estimated cost:")
        print(f"  {'Project':<18} {'Pattern':<18} {'Count':>6} {'$Cost':>10}")
        print(f"  {'-' * 56}")
        for r in rows:
            print(f"  {str(r[0] or '-'):<18} {str(r[1] or '-'):<18} "
                  f"{(r[2] or 0):>6} ${(r[3] or 0):>9.2f}")
        print()
    conn.close()


def _fmt_fix_header(f):
    dt = datetime.fromtimestamp(f["created_at"], tz=timezone.utc).strftime("%b %d")
    return f"#{f['id']:<3} {f['project']} · {f['waste_pattern']} · {f['title']}  (applied {dt})"


def _fmt_status_badge(status):
    return {
        "applied": "measuring",
        "measuring": "measuring",
        "confirmed": "confirmed ✓",
        "reverted": "reverted",
    }.get(status, status)


def cmd_fixes():
    """List all recorded fixes with current status."""
    init_db()
    conn = get_conn()
    from fix_tracker import all_fixes_with_latest
    fixes = all_fixes_with_latest(conn)
    conn.close()

    print()
    if not fixes:
        print("  Fix Tracker — no fixes recorded yet")
        print()
        print("  Start by recording one:")
        print("    python3 cli.py fix add")
        print()
        return

    print(f"  Fix Tracker — {len(fixes)} fix{'es' if len(fixes) != 1 else ''} recorded")
    print(f"  {'─' * 60}")
    now = int(time.time())
    for f in fixes:
        baseline = f.get("baseline") or {}
        plan = baseline.get("plan_type", "max")
        days_elapsed = max(int((now - (f["created_at"] or now)) / 86400), 0)
        status_txt = _fmt_status_badge(f["status"])
        print(f"  #{f['id']:<3} {f['project']} · {f['waste_pattern']} · {f['title']}")
        print(f"       applied {datetime.fromtimestamp(f['created_at'], tz=timezone.utc).strftime('%b %d')} · "
              f"status: {status_txt} · {days_elapsed}d elapsed")

        latest = f.get("latest")
        if f["status"] == "confirmed" and latest:
            delta = latest.get("delta", {})
            waste = delta.get("waste_events", {})
            eff = delta.get("effective_window_pct", {})
            cost = delta.get("avg_cost_per_session", {})
            wb = waste.get("before", 0); wa = waste.get("after", 0); wp = waste.get("pct_change", 0)
            if plan in ("max", "pro"):
                eb = eff.get("before", 0); ea = eff.get("after", 0)
                print(f"       before: {wb} → after: {wa} ({wp:+.0f}%) · window: {eb}% → {ea}%")
            else:
                cb = cost.get("before", 0); ca = cost.get("after", 0); cp = cost.get("pct_change", 0)
                print(f"       before: {wb} → after: {wa} ({wp:+.0f}%) · cost/sess: ${cb:.2f} → ${ca:.2f} ({cp:+.0f}%)")
        elif f["status"] in ("applied", "measuring"):
            waste_b = (baseline.get("waste_events") or {}).get("total", 0)
            print(f"       baseline: {waste_b} waste events · run: python3 cli.py measure {f['id']}")
        elif f["status"] == "reverted":
            print(f"       reverted")
        print()
    print(f"  {'─' * 60}")
    print()
    conn.close() if False else None  # conn already closed above; kept for pyflake silence


def cmd_fix_add():
    """Interactive baseline + fix recorder."""
    init_db()
    conn = get_conn()
    from fix_tracker import record_fix, WASTE_PATTERNS, FIX_TYPES, WASTE_PATTERN_LABELS

    # Discover candidate projects from the live DB
    project_rows = conn.execute(
        "SELECT project, COUNT(*) AS n FROM sessions GROUP BY project ORDER BY n DESC"
    ).fetchall()
    projects = [r[0] for r in project_rows if r[0]]

    print()
    print("  Record a fix — Claudash Fix Tracker")
    print(f"  {'─' * 50}")
    if projects:
        print("  Projects in the DB:")
        for i, p in enumerate(projects, 1):
            print(f"    {i}. {p}")
        print()
    project = input("  Project name: ").strip()
    if not project:
        print("  Cancelled.")
        return

    print()
    print("  What waste pattern did you fix?")
    for i, p in enumerate(WASTE_PATTERNS, 1):
        print(f"    {i}. {p} — {WASTE_PATTERN_LABELS.get(p, '')}")
    sel = input("  Number or name: ").strip()
    if sel.isdigit():
        idx = int(sel) - 1
        pattern = WASTE_PATTERNS[idx] if 0 <= idx < len(WASTE_PATTERNS) else "custom"
    else:
        pattern = sel if sel in WASTE_PATTERNS else "custom"

    title = input("  Fix title (one line): ").strip()
    if not title:
        title = f"{pattern} fix"

    print()
    print("  Fix type:")
    for i, t in enumerate(FIX_TYPES, 1):
        print(f"    {i}. {t}")
    sel = input("  Number or name: ").strip()
    if sel.isdigit():
        idx = int(sel) - 1
        fix_type = FIX_TYPES[idx] if 0 <= idx < len(FIX_TYPES) else "other"
    else:
        fix_type = sel if sel in FIX_TYPES else "other"

    print()
    print("  What exactly changed? (paste your fix, end with a blank line)")
    lines = []
    while True:
        try:
            line = input("    ")
        except EOFError:
            break
        if not line and (not lines or lines[-1] == ""):
            break
        lines.append(line)
    fix_detail = "\n".join(lines).strip()

    print()
    print(f"  Capturing baseline for {project}…")
    fix_id, baseline = record_fix(conn, project, pattern, title, fix_type, fix_detail)
    conn.close()

    waste_total = (baseline.get("waste_events") or {}).get("total", 0)
    eff = baseline.get("effective_window_pct", 0)
    avg_cost = baseline.get("avg_cost_per_session", 0)
    print(f"  ✓ Baseline: {waste_total} waste events, "
          f"{eff:.0f}% window efficiency, ${avg_cost:.2f}/session API-equiv")
    print(f"  ✓ Fix #{fix_id} recorded.")
    print()
    print("  Next steps:")
    print("    1. Apply your fix to the project now.")
    print("    2. Use Claude Code normally for 7+ days.")
    print(f"    3. Run: python3 cli.py measure {fix_id}")
    print()


def cmd_measure():
    """Capture current metrics for a fix and print a plan-aware verdict."""
    if len(sys.argv) < 3 or not sys.argv[2].isdigit():
        print("Usage: python3 cli.py measure <fix_id>")
        sys.exit(1)
    fix_id = int(sys.argv[2])
    init_db()
    conn = get_conn()
    from fix_tracker import measure_fix, build_share_card
    from db import get_fix, get_latest_fix_measurement
    delta, verdict, metrics = measure_fix(conn, fix_id)
    if delta is None:
        print(f"Fix #{fix_id} not found.")
        conn.close()
        sys.exit(1)

    fix = get_fix(conn, fix_id)
    plan = delta.get("plan_type", "max")
    plan_cost = delta.get("plan_cost_usd", 0)
    project = fix["project"]
    pattern = fix["waste_pattern"]
    title = fix["title"]

    waste = delta.get("waste_events", {})
    flounder = delta.get("floundering", {})
    reads = delta.get("repeated_reads", {})
    eff = delta.get("effective_window_pct", {})
    fpw = delta.get("files_per_window", {})
    turns = delta.get("avg_turns_per_session", {})
    cps = delta.get("avg_cost_per_session", {})
    total_cost = delta.get("cost_usd", {})
    days = delta.get("days_elapsed", 0)
    sessions_since = delta.get("sessions_since_fix", 0)
    api_eq = delta.get("api_equivalent_savings_monthly", 0)
    multiplier = delta.get("improvement_multiplier", 1.0)

    def row(label, before, after, change, sign="pct", ok=None):
        change_str = f"{change:+.0f}%"
        marker = ""
        if ok is not None:
            marker = "  ✓" if ok else "  ✗"
        if sign == "money":
            return f"  {label:<22} ${before:<10.2f} ${after:<10.2f} {change_str}{marker}"
        if sign == "pct":
            return f"  {label:<22} {before!s:<11} {after!s:<11} {change_str}{marker}"
        return f"  {label:<22} {before!s:<11} {after!s:<11} {change_str}{marker}"

    print()
    print(f"  Measuring Fix #{fix_id}: {project} · {pattern} — {title}")
    print(f"  {'─' * 60}")
    print(f"  {'Metric':<22} {'Before':<11} {'After':<11} {'Change'}")
    print(f"  {'─' * 60}")
    print(row("Floundering events", flounder.get("before", 0), flounder.get("after", 0), flounder.get("pct_change", 0), ok=flounder.get("pct_change", 0) < 0))
    print(row("Repeated reads", reads.get("before", 0), reads.get("after", 0), reads.get("pct_change", 0), ok=reads.get("pct_change", 0) < 0))
    print(row("Waste total", waste.get("before", 0), waste.get("after", 0), waste.get("pct_change", 0), ok=waste.get("pct_change", 0) < 0))

    if plan in ("max", "pro"):
        print(row("Window efficiency", f"{eff.get('before', 0)}%", f"{eff.get('after', 0)}%",
                  eff.get("pct_change", 0), ok=eff.get("pct_change", 0) > 0))
        print(row("Files per window", fpw.get("before", 0), fpw.get("after", 0),
                  fpw.get("pct_change", 0), ok=fpw.get("pct_change", 0) > 0))
        print(row("Avg turns/session", turns.get("before", 0), turns.get("after", 0), turns.get("pct_change", 0)))
        print(row("API-equiv cost/sess", cps.get("before", 0), cps.get("after", 0),
                  cps.get("pct_change", 0), sign="money"))
    else:
        print(row("Cost per session", cps.get("before", 0), cps.get("after", 0),
                  cps.get("pct_change", 0), sign="money", ok=cps.get("pct_change", 0) < 0))
        print(row("Total cost (window)", total_cost.get("before", 0), total_cost.get("after", 0),
                  total_cost.get("pct_change", 0), sign="money", ok=total_cost.get("pct_change", 0) < 0))

    print(f"  {'─' * 60}")
    verdict_upper = verdict.replace("_", " ").upper()
    marker = "✓" if verdict == "improving" else ("✗" if verdict == "worsened" else "—")
    print(f"  Verdict: {verdict_upper} {marker}  ({days} days, {sessions_since} sessions)")
    print()
    if plan in ("max", "pro"):
        print(f"  Same ${plan_cost:.0f}/mo {plan.upper()} plan — {multiplier}x more output per window.")
        print(f"  API-equivalent waste eliminated: ~${api_eq:.0f}/mo")
    else:
        print(f"  Monthly savings: ~${api_eq:.0f}/mo")
    print()

    latest = get_latest_fix_measurement(conn, fix_id)
    card = build_share_card(fix, latest)
    conn.close()
    print("  Share card:")
    print()
    for line in card.split("\n"):
        print("    " + line)
    print()


def cmd_mcp():
    """Print MCP server settings.json snippet + run a quick smoke test."""
    import subprocess as _sp
    mcp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    snippet = {
        "mcpServers": {
            "claudash": {
                "command": "python3",
                "args": [mcp_path],
            }
        }
    }
    print()
    print("  Claudash MCP server")
    print(f"  {'-' * 50}")
    print("  Add this to ~/.claude/settings.json (merge with any existing")
    print("  `mcpServers` block — don't overwrite the whole file):")
    print()
    print(json.dumps(snippet, indent=2))
    print()
    print("  Running smoke test…")
    print()
    try:
        result = _sp.run(["python3", mcp_path, "test"], capture_output=True, text=True, timeout=15)
        print("  " + (result.stdout.strip() or "(no output)"))
        if result.stderr.strip():
            print("  stderr: " + result.stderr.strip())
        if result.returncode != 0:
            print(f"  exit code: {result.returncode}")
    except Exception as e:
        print(f"  FAILED to run mcp_server.py test: {e}")
    print()


def _read_session_id_from_jsonl(filepath):
    """Return the first sessionId/session_id/uuid found in a JSONL file, or
    None. Only reads until it finds one — cheap even for huge files."""
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


def cmd_scan_reprocess():
    """Re-tag every tracked session using the current PROJECT_MAP.

    Steps:
      1. Sync config.PROJECT_MAP → account_projects (so keyword edits land).
      2. Walk scan_state.file_path (the authoritative list of scanned files).
      3. For each file, read the first sessionId and resolve project/account
         from the file's folder path.
      4. UPDATE sessions SET source_path, project, account WHERE session_id.
      5. Print a before/after distribution diff.
    """
    import json as _json  # local alias so we don't shadow module-level imports
    from scanner import resolve_project, _parse_subagent_info
    init_db()
    conn = get_conn()

    # Snapshot before
    before = dict(conn.execute(
        "SELECT project, COUNT(*) FROM sessions GROUP BY project"
    ).fetchall())
    total_before = sum(before.values())

    # Step 1 — sync keyword map from config.py
    sync_project_map_from_config(conn)
    project_map = get_project_map_config(conn)

    # Step 2 — list all tracked JSONL files
    files = [r[0] for r in conn.execute(
        "SELECT file_path FROM scan_state ORDER BY file_path"
    ).fetchall()]

    updated = 0
    skipped_missing = 0
    skipped_no_sid = 0
    resolved_counts = {}

    for filepath in files:
        if not os.path.isfile(filepath):
            skipped_missing += 1
            continue
        sid = _read_session_id_from_jsonl(filepath)
        if not sid:
            skipped_no_sid += 1
            continue
        # Subagent files inherit the parent's project tag — resolve against
        # the parent project folder (grandparent of `subagents/`) when this
        # is a subagent file.
        is_subagent, parent_sid = _parse_subagent_info(filepath)
        if is_subagent:
            parent_project_folder = filepath.split("/subagents/")[0]
            parent_project_folder = os.path.dirname(parent_project_folder)
            folder = parent_project_folder or os.path.dirname(filepath)
        else:
            folder = os.path.dirname(filepath)
        project, account = resolve_project(folder, project_map)
        cur = conn.execute(
            "UPDATE sessions SET source_path = ?, project = ?, account = ?, "
            "                     is_subagent = ?, parent_session_id = ? "
            "WHERE session_id = ?",
            (filepath, project, account, is_subagent, parent_sid, sid)
        )
        updated += cur.rowcount
        resolved_counts[project] = resolved_counts.get(project, 0) + 1

    conn.commit()

    # Snapshot after
    after = dict(conn.execute(
        "SELECT project, COUNT(*) FROM sessions GROUP BY project"
    ).fetchall())
    total_after = sum(after.values())

    print()
    print(f"  Reprocessed: {updated:,} session rows across {len(files):,} files")
    print(f"  Files skipped (missing on disk): {skipped_missing}")
    print(f"  Files skipped (no sessionId):    {skipped_no_sid}")
    print()
    print(f"  {'Project':<22} {'Before':>8} {'After':>8} {'Delta':>8}")
    print(f"  {'-' * 50}")
    all_projs = sorted(set(before.keys()) | set(after.keys()),
                       key=lambda p: -(after.get(p, 0) or 0))
    for p in all_projs:
        b = before.get(p, 0)
        a = after.get(p, 0)
        d = a - b
        delta = f"{d:+,}" if d else "—"
        print(f"  {str(p):<22} {b:>8,} {a:>8,} {delta:>8}")
    print(f"  {'-' * 50}")
    print(f"  {'TOTAL':<22} {total_before:>8,} {total_after:>8,}")
    print()

    conn.close()


def cmd_show_other():
    """List every source path currently tagged 'Other' so the user can see
    what keywords need adding to PROJECT_MAP."""
    init_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT source_path, COUNT(*) AS n, COUNT(DISTINCT session_id) AS sessions "
        "FROM sessions WHERE project = 'Other' "
        "GROUP BY source_path ORDER BY n DESC"
    ).fetchall()
    conn.close()

    if not rows:
        print("\n  No sessions are tagged 'Other'. Every session has a project.\n")
        return

    print(f"\n  Sessions tagged 'Other' — {len(rows)} distinct source paths:")
    print(f"  {'-' * 72}")
    for r in rows:
        path = r[0] or "(empty)"
        n = r[1]
        s = r[2]
        # Truncate long paths for readability
        display = path if len(path) <= 60 else "…" + path[-59:]
        print(f"  {display:<62} {n:>5} rows / {s:>3} sessions")
    print(f"  {'-' * 72}")
    print("  Add folder keywords to PROJECT_MAP in config.py, then run:")
    print("    python3 cli.py scan --reprocess")
    print()


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

    # Efficiency score (across all accounts)
    try:
        eff = compute_efficiency_score(conn)
        print(f"  Efficiency Score: {eff['score']}/100 (Grade {eff['grade']})")
        print(f"  Top improvement: {eff['top_improvement']}")
        print()
    except Exception:
        pass

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


def cmd_sync_daemon():
    """Run the sync daemon that pushes claude.ai browser data every 5 min."""
    daemon = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tools", "sync-daemon.py")
    os.execv(sys.executable, [sys.executable, daemon])


def cmd_keys():
    """Print dashboard_key and sync_token. Sensitive — do not paste into
    screenshots, chat transcripts, or shared terminals."""
    init_db()

    if len(sys.argv) >= 3 and sys.argv[2] == "--rotate":
        import secrets
        new_key = secrets.token_hex(32)
        conn = get_conn()
        set_setting(conn, "dashboard_key", new_key)
        conn.close()
        print()
        print(f"  New dashboard_key: {new_key}")
        print(f"  Update this in your browser localStorage and any scripts.")
        print()
        return

    conn = get_conn()
    dk = get_setting(conn, "dashboard_key") or "(not set)"
    st = get_setting(conn, "sync_token") or "(not set)"
    conn.close()
    print()
    print("  These values grant full write access to your dashboard.")
    print("  Keep them private. Do not share, screenshot, or commit them.")
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

    # Two-word commands: `fix add`
    if cmd == "fix":
        sub = sys.argv[2] if len(sys.argv) >= 3 else ""
        if sub == "add":
            cmd_fix_add()
            return
        print("Usage: python3 cli.py fix add")
        sys.exit(1)

    commands = {
        "dashboard": cmd_dashboard,
        "init": cmd_init,
        "scan": cmd_scan,
        "show-other": cmd_show_other,
        "stats": cmd_stats,
        "insights": cmd_insights,
        "window": cmd_window,
        "export": cmd_export,
        "waste": cmd_waste,
        "fixes": cmd_fixes,
        "measure": cmd_measure,
        "mcp": cmd_mcp,
        "keys": cmd_keys,
        "claude-ai": cmd_claude_ai,
        "sync-daemon": cmd_sync_daemon,
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
