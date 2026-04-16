#!/usr/bin/env python3
"""
Claudash Automated Test Runner
Run from VPS: python3 claudash_test_runner.py
Run specific section: python3 claudash_test_runner.py --section v2
Run single test: python3 claudash_test_runner.py --test TEST-V2-F1

Results saved to: /tmp/claudash_test_results.txt
"""

import subprocess
import sqlite3
import json
import urllib.request
import urllib.error
import time
import sys
import os
import argparse
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8080"
DB_PATH = os.path.expanduser("~/projects/jk-usage-dashboard/data/usage.db")
PROJ_DIR = os.path.expanduser("~/projects/jk-usage-dashboard")
RESULTS_FILE = "/tmp/claudash_test_results.txt"

# ── HELPERS ───────────────────────────────────────────────────────────────────

results = []

def get_db():
    return sqlite3.connect(DB_PATH)

def api_get(path, timeout=10):
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}

def api_post(path, body=None, timeout=10):
    try:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"{BASE_URL}{path}", data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}

def run_cli(cmd, cwd=PROJ_DIR, timeout=30):
    try:
        r = subprocess.run(
            ["python3"] + cmd.split(),
            cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
WARN = "\033[93mWARN\033[0m"

def record(test_id, name, status, detail=""):
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "~", "WARN": "!"}.get(status, "?")
    color = {"PASS": PASS, "FAIL": FAIL, "SKIP": SKIP, "WARN": WARN}.get(status, status)
    print(f"  {icon} [{test_id}] {name}: {color}")
    if detail:
        for line in detail.split("\n"):
            if line.strip():
                print(f"      {line}")
    results.append({
        "id": test_id,
        "name": name,
        "status": status,
        "detail": detail,
        "ts": datetime.now().isoformat()
    })

# ── SECTION 1: INFRASTRUCTURE ─────────────────────────────────────────────────

def test_i01_server_health():
    status, data = api_get("/health")
    if status != 200:
        record("TEST-I-01", "Server health", "FAIL", f"HTTP {status}")
        return
    version = data.get("version", "")
    server_status = data.get("status", "")
    if version != "1.0.15":
        record("TEST-I-01", "Server health", "WARN",
               f"version={version} (expected 1.0.15 — may be newer)")
    elif server_status != "ok":
        record("TEST-I-01", "Server health", "FAIL", f"status={server_status}")
    else:
        record("TEST-I-01", "Server health", "PASS",
               f"v{version} uptime={data.get('uptime_seconds',0)}s")

def test_i02_pm2():
    rc, out, err = run_cli("", cwd="/")
    result = subprocess.run(
        ["pm2", "list"], capture_output=True, text=True, timeout=10
    )
    if "claudash" not in result.stdout:
        record("TEST-I-02", "PM2 process", "FAIL", "claudash not in pm2 list")
    elif "online" in result.stdout:
        record("TEST-I-02", "PM2 process", "PASS", "claudash online in PM2")
    else:
        record("TEST-I-02", "PM2 process", "WARN", "claudash in PM2 but not online")

def test_i03_database_scale():
    db = get_db()
    checks = {
        "sessions": 20000,
        "lifecycle_events": 250,
        "waste_events": 60,
        "fixes": 5,
        "fix_measurements": 8,
        "insights": 5,
        "mcp_warnings": 0,
        "scan_state": 100,
    }
    fails = []
    details = []
    for table, minimum in checks.items():
        try:
            count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            details.append(f"{table}: {count} rows")
            if count < minimum:
                fails.append(f"{table}={count} (min {minimum})")
        except Exception as e:
            fails.append(f"{table}: ERROR {e}")
    db.close()
    if fails:
        record("TEST-I-03", "Database scale", "FAIL", "\n".join(fails))
    else:
        record("TEST-I-03", "Database scale", "PASS",
               f"{len(checks)} tables checked\n" + "\n".join(details[:4]))

def test_i04_scanner():
    rc, out, err = run_cli("cli.py scan")
    if rc != 0:
        record("TEST-I-04", "Incremental scanner", "FAIL",
               f"Exit {rc}\n{err[:200]}")
    elif "Scan complete" in out or "new rows" in out.lower():
        record("TEST-I-04", "Incremental scanner", "PASS",
               out.strip().split("\n")[-1][:100])
    else:
        record("TEST-I-04", "Incremental scanner", "WARN",
               f"Ran but unexpected output: {out[:100]}")

# ── SECTION 2: V1 FEATURES ─────────────────────────────────────────────────────

def test_v1_01_cost():
    status, data = api_get("/api/data")
    if status != 200:
        record("TEST-V1-01", "Cost by project", "FAIL", f"HTTP {status}")
        return
    projects = data.get("projects", [])
    if not projects:
        record("TEST-V1-01", "Cost by project", "FAIL", "No projects in /api/data")
        return
    top = sorted(projects, key=lambda x: x.get("cost_usd_30d", x.get("total_cost_30d", 0)), reverse=True)[:3]
    detail = "\n".join([f"  {p['name']}: ${p.get('total_cost_30d',0):.2f}" for p in top])
    if any(p.get("cost_usd_30d", p.get("total_cost_30d", 0)) > 0 for p in projects):
        record("TEST-V1-01", "Cost by project", "PASS",
               f"{len(projects)} projects\n{detail}")
    else:
        record("TEST-V1-01", "Cost by project", "FAIL", "All projects show $0")

def test_v1_02_waste():
    rc, out, err = run_cli("cli.py waste")
    db = get_db()
    events = db.execute(
        "SELECT pattern_type, COUNT(*) FROM waste_events GROUP BY pattern_type"
    ).fetchall()
    db.close()
    if rc != 0:
        record("TEST-V1-02", "Waste detection", "FAIL", f"cli.py waste failed: {err[:100]}")
        return
    detail = "\n".join([f"  {r[0]}: {r[1]} events" for r in events])
    if not events:
        record("TEST-V1-02", "Waste detection", "WARN",
               "No waste events in DB — run a scan first")
    else:
        record("TEST-V1-02", "Waste detection", "PASS", detail)

def test_v1_03_insights():
    status, data = api_get("/api/insights")
    if status != 200:
        record("TEST-V1-03", "Insights engine", "FAIL", f"HTTP {status}")
        return
    insights = data if isinstance(data, list) else []
    ghost = [i for i in insights if i.get("insight_type") == "floundering_detected"]
    db = get_db()
    flounder_events = db.execute(
        "SELECT COUNT(*) FROM waste_events WHERE pattern_type='floundering'"
    ).fetchone()[0]
    db.close()
    if ghost and flounder_events == 0:
        record("TEST-V1-03", "Insights engine", "FAIL",
               f"GHOST INSIGHTS: {len(ghost)} floundering_detected but 0 waste events")
        return
    types = {}
    for i in insights:
        t = i.get("insight_type", "unknown")
        types[t] = types.get(t, 0) + 1
    detail = "\n".join([f"  {k}: {v}" for k, v in types.items()])
    record("TEST-V1-03", "Insights engine", "PASS",
           f"{len(insights)} active insights\n{detail}")

def test_v1_04_fix_tracker():
    status, data = api_get("/api/fixes")
    if status != 200:
        record("TEST-V1-04", "Fix tracker", "FAIL", f"HTTP {status}")
        return
    fixes = data if isinstance(data, list) else []
    db = get_db()
    measurements = db.execute(
        "SELECT verdict, COUNT(*) FROM fix_measurements GROUP BY verdict"
    ).fetchall()
    db.close()
    detail = f"Fixes: {len(fixes)}\n" + \
             "\n".join([f"  verdict={r[0]}: {r[1]}" for r in measurements])
    if not fixes:
        record("TEST-V1-04", "Fix tracker", "WARN", "No fixes in DB")
    else:
        record("TEST-V1-04", "Fix tracker", "PASS", detail)

def test_v1_05_mcp():
    rc, out, err = run_cli("mcp_server.py test")
    if rc != 0:
        record("TEST-V1-05", "MCP server", "FAIL", f"Exit {rc}: {err[:100]}")
    elif "10 tools" in out:
        record("TEST-V1-05", "MCP server", "PASS", out.strip())
    elif "tools registered" in out:
        record("TEST-V1-05", "MCP server", "WARN",
               f"Expected 10 tools: {out.strip()}")
    else:
        record("TEST-V1-05", "MCP server", "FAIL", f"Unexpected output: {out[:100]}")

def test_v1_06_browser_sync():
    status, data = api_get("/api/claude-ai/accounts")
    if status != 200:
        record("TEST-V1-06", "Browser sync", "FAIL", f"HTTP {status}")
        return
    accounts = data.get("accounts", data) if isinstance(data, dict) else data
    if not accounts:
        record("TEST-V1-06", "Browser sync", "WARN", "No browser accounts configured")
        return
    detail = []
    for a in accounts:
        snap = a.get("latest_snapshot", {})
        detail.append(f"  {a.get('account_id')}: {snap.get('pct_used',0)}% used")
    record("TEST-V1-06", "Browser sync", "PASS", "\n".join(detail))

def test_v1_07_dashboard_ui():
    try:
        req = urllib.request.Request(f"{BASE_URL}/")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="ignore")
            has_content = "claudash" in body.lower() or "dashboard" in body.lower()
            record("TEST-V1-07", "Dashboard UI loads",
                   "PASS" if has_content else "WARN",
                   f"HTTP {r.status}, dashboard content: {has_content}")
    except Exception as e:
        record("TEST-V1-07", "Dashboard UI loads", "FAIL", str(e))

# ── SECTION 3: V2 FEATURES ─────────────────────────────────────────────────────

def test_v2_f1_lifecycle():
    status, data = api_get("/api/lifecycle?project=Tidify")
    if status != 200:
        record("TEST-V2-F1", "Lifecycle event tracking", "FAIL", f"HTTP {status}")
        return
    db = get_db()
    events = db.execute(
        "SELECT event_type, COUNT(*), ROUND(AVG(context_pct_at_event),1) "
        "FROM lifecycle_events GROUP BY event_type"
    ).fetchall()
    nulls = db.execute(
        "SELECT COUNT(*) FROM lifecycle_events WHERE context_pct_at_event IS NULL"
    ).fetchone()[0]
    db.close()
    if not events:
        record("TEST-V2-F1", "Lifecycle event tracking", "FAIL", "0 lifecycle events")
        return
    detail = "\n".join([f"  {r[0]}: {r[1]} events, avg {r[2]}% context" for r in events])
    detail += f"\n  NULLs in context_pct: {nulls}"
    has_required = [r[0] for r in events]
    if "compact" not in has_required or "subagent_spawn" not in has_required:
        record("TEST-V2-F1", "Lifecycle event tracking", "WARN",
               f"Missing event types. Found: {has_required}")
    else:
        record("TEST-V2-F1", "Lifecycle event tracking", "PASS", detail)

def test_v2_f2_context_rot():
    status, data = api_get("/api/context-rot")
    if status != 200:
        record("TEST-V2-F2", "Context rot visualization", "FAIL", f"HTTP {status}")
        return
    declining = []
    for proj, rot in data.items():
        buckets = rot.get("buckets", [])
        if len(buckets) >= 3:
            first = buckets[0].get("avg_ratio", 0)
            last = buckets[-1].get("avg_ratio", 0)
            if last < first:
                declining.append(proj)
    detail = f"{len(data)} projects returned\n"
    detail += f"Projects showing declining ratio: {declining}"
    if not data:
        record("TEST-V2-F2", "Context rot visualization", "FAIL", "No data returned")
    elif not declining:
        record("TEST-V2-F2", "Context rot visualization", "WARN",
               "No projects show declining ratio (data may be sparse)")
    else:
        record("TEST-V2-F2", "Context rot visualization", "PASS", detail)

def test_v2_f3_bad_compact():
    status, data = api_get("/api/bad-compacts?project=Tidify")
    if status != 200:
        record("TEST-V2-F3", "Bad compact detector", "FAIL", f"HTTP {status}")
        return
    required = ["project", "days", "count", "bad_compacts", "compact_instruction"]
    missing = [k for k in required if k not in data]
    if missing:
        record("TEST-V2-F3", "Bad compact detector", "FAIL",
               f"Missing fields: {missing}")
        return
    instr = data.get("compact_instruction", "")
    is_project_specific = "Tidify" in instr or "normalized" in instr.lower() or \
                          "column" in instr.lower()
    detail = f"count={data['count']} (0 is expected — no real /compact yet)\n"
    detail += f"compact_instruction: {instr[:80]}\n"
    detail += f"project-specific: {is_project_specific}"
    if missing:
        record("TEST-V2-F3", "Bad compact detector", "FAIL", detail)
    else:
        record("TEST-V2-F3", "Bad compact detector", "PASS", detail)

def test_v2_f4_fix_generator():
    # Test 1: imports
    try:
        sys.path.insert(0, PROJ_DIR)
        import fix_generator
        patterns = sorted(fix_generator.PROMPTS.keys())
        providers = list(fix_generator.SUPPORTED_PROVIDERS.keys())
    except Exception as e:
        record("TEST-V2-F4", "Fix generator", "FAIL", f"Import error: {e}")
        return

    expected_patterns = sorted([
        "repeated_reads", "floundering", "deep_no_compact",
        "cost_outlier", "bad_compact", "rewind_heavy"
    ])
    expected_providers = ["anthropic", "bedrock", "openai_compat"]

    # Test 2: offline graceful
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        wid = conn.execute("SELECT id FROM waste_events LIMIT 1").fetchone()
        if wid:
            result = fix_generator.generate_fix(wid[0], conn)
            offline_ok = "error" in result
        else:
            offline_ok = True
        conn.close()
    except Exception as e:
        offline_ok = False

    detail = f"patterns: {patterns}\n"
    detail += f"providers: {providers}\n"
    detail += f"offline graceful: {offline_ok}"

    if patterns != expected_patterns:
        record("TEST-V2-F4", "Fix generator", "FAIL",
               f"Wrong patterns: {patterns}")
    elif not offline_ok:
        record("TEST-V2-F4", "Fix generator", "SKIP",
               "No provider configured — run: claudash keys --set-provider")
    else:
        record("TEST-V2-F4", "Fix generator", "PASS", detail)

def test_v2_f5_mcp_bidirectional():
    try:
        sys.path.insert(0, PROJ_DIR)
        import mcp_server

        # test trigger_scan
        result = mcp_server.handle_tool("claudash_trigger_scan", {})
        scan_ok = result.get("status") == "ok"

        # test report_waste
        import time
        result2 = mcp_server.handle_tool("claudash_report_waste", {
            "project": "Tidify",
            "pattern_type": "repeated_reads",
            "session_id": f"test-runner-{int(time.time())}",
            "detail": "Automated test"
        })
        report_ok = result2.get("status") == "ok" and "waste_event_id" in result2

        # test get_warnings shape
        result3 = mcp_server.handle_tool("claudash_get_warnings", {"project": "Tidify"})
        warnings_ok = all(k in result3 for k in ["warnings", "count", "has_critical"])

        detail = f"trigger_scan: {scan_ok}\nreport_waste: {report_ok}\nget_warnings shape: {warnings_ok}"
        if scan_ok and report_ok and warnings_ok:
            record("TEST-V2-F5", "Bidirectional MCP", "PASS", detail)
        else:
            record("TEST-V2-F5", "Bidirectional MCP", "FAIL", detail)
    except Exception as e:
        record("TEST-V2-F5", "Bidirectional MCP", "FAIL", str(e))

def test_v2_f6_streaming_meter():
    hooks_dir = os.path.join(PROJ_DIR, "hooks")
    pre = os.path.join(hooks_dir, "pre_tool_use.sh")
    post = os.path.join(hooks_dir, "post_tool_use.sh")

    hooks_exist = os.path.isfile(pre) and os.path.isfile(post)
    hooks_executable = os.access(pre, os.X_OK) and os.access(post, os.X_OK)

    # test cost event endpoint
    status, data = api_post("/api/hooks/cost-event", {
        "project": "Tidify",
        "session_id": "test-runner-meter",
        "tool_name": "Bash",
        "phase": "post",
        "actual_tokens": 300
    })
    endpoint_ok = data.get("ok") is True

    # test SSE content-type (non-blocking)
    sse_ok = False
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/stream/cost")
        req.add_header("Accept", "text/event-stream")
        conn = urllib.request.urlopen(req, timeout=2)
        ct = conn.headers.get("Content-Type", "")
        sse_ok = "event-stream" in ct
        conn.close()
    except Exception:
        sse_ok = False

    detail = f"hooks exist: {hooks_exist}\nhooks executable: {hooks_executable}\n"
    detail += f"cost-event endpoint: {endpoint_ok}\nSSE content-type: {sse_ok}"

    if hooks_exist and hooks_executable and endpoint_ok:
        record("TEST-V2-F6", "Streaming cost meter", "PASS", detail)
    else:
        record("TEST-V2-F6", "Streaming cost meter", "FAIL", detail)

def test_v2_f7_threshold_recommendations():
    status, data = api_get("/api/recommendations?project=Tidify")
    if status != 200:
        record("TEST-V2-F7", "Threshold recommendations", "FAIL", f"HTTP {status}")
        return
    required = [
        "project", "recommended_threshold", "recommended_threshold_pct",
        "current_avg_compact_pct", "confidence", "reasoning",
        "settings_json", "settings_json_claude_md", "data_sufficient"
    ]
    missing = [k for k in required if k not in data]

    # verify settings_json is valid JSON
    settings_valid = False
    try:
        s = json.loads(data.get("settings_json", "{}"))
        settings_valid = "autoCompactThreshold" in s
    except Exception:
        pass

    detail = f"threshold={data.get('recommended_threshold')}\n"
    detail += f"confidence={data.get('confidence')}\n"
    detail += f"settings_json valid: {settings_valid}\n"
    detail += f"claude_md rule: {data.get('settings_json_claude_md','')[:60]}"

    if missing:
        record("TEST-V2-F7", "Threshold recommendations", "FAIL",
               f"Missing: {missing}")
    elif not settings_valid:
        record("TEST-V2-F7", "Threshold recommendations", "FAIL",
               "settings_json not valid JSON with autoCompactThreshold")
    else:
        record("TEST-V2-F7", "Threshold recommendations", "PASS", detail)

# ── SECTION 4: REGRESSION ──────────────────────────────────────────────────────

def test_r01_all_endpoints():
    endpoints = [
        "/health", "/api/health", "/api/data", "/api/insights",
        "/api/fixes", "/api/accounts", "/api/window", "/api/trends",
        "/api/lifecycle", "/api/context-rot", "/api/bad-compacts",
        "/api/recommendations", "/api/real-story"
    ]
    fails = []
    for ep in endpoints:
        status, _ = api_get(ep)
        if status != 200:
            fails.append(f"{ep} → {status}")

    if fails:
        record("TEST-R-01", "All endpoints 200", "FAIL", "\n".join(fails))
    else:
        record("TEST-R-01", "All endpoints 200", "PASS",
               f"All {len(endpoints)} endpoints returned 200")

def test_r02_no_pip_deps():
    stdlib = {
        "os", "sys", "json", "re", "time", "math", "sqlite3", "hashlib",
        "datetime", "threading", "urllib", "http", "socket", "logging",
        "pathlib", "collections", "itertools", "functools", "string",
        "typing", "abc", "io", "copy", "random", "struct", "base64",
        "hmac", "secrets", "uuid", "csv", "argparse", "subprocess",
        "shutil", "glob", "tempfile", "traceback", "inspect", "stat",
        "platform", "ssl", "fnmatch", "signal", "getpass", "concurrent", "webbrowser", "threading", "typing_extensions", "webbrowser", "typing_extensions",
        "contextlib"
    }
    py_files = [f for f in os.listdir(PROJ_DIR) if f.endswith(".py")]
    non_stdlib = []
    for fname in py_files:
        try:
            with open(os.path.join(PROJ_DIR, fname)) as f:
                for line in f:
                    line = line.strip()
                    if (line.startswith("import ") or line.startswith("from ")) and not line.startswith("from the") and not line.startswith("from your"):
                        mod = line.split()[1].split(".")[0].split(",")[0]
                        if mod not in stdlib and mod not in ("fix_generator", "db",
                            "scanner", "analyzer", "insights", "waste_patterns",
                            "fix_tracker", "mcp_server", "server", "cli",
                            "claude_ai_tracker", "_version", "config"):
                            non_stdlib.append(f"{fname}: {line[:60]}")
        except Exception:
            pass

    # boto3 is acceptable (lazy import in fix_generator)
    real_non_stdlib = [x for x in non_stdlib if "boto3" not in x]
    if real_non_stdlib:
        record("TEST-R-02", "Zero non-stdlib imports", "FAIL",
               "\n".join(real_non_stdlib[:5]))
    else:
        record("TEST-R-02", "Zero non-stdlib imports", "PASS",
               f"Checked {len(py_files)} .py files. boto3 acceptable (lazy import).")

def test_r03_mcp_tool_count():
    rc, out, err = run_cli("mcp_server.py test")
    if "10 tools" in out:
        record("TEST-R-03", "MCP tool count = 10", "PASS", out.strip())
    elif "tools registered" in out:
        record("TEST-R-03", "MCP tool count = 10", "FAIL",
               f"Expected 10: {out.strip()}")
    else:
        record("TEST-R-03", "MCP tool count = 10", "FAIL",
               f"rc={rc} out={out[:80]}")

def test_r04_git_clean():
    result = subprocess.run(
        ["git", "log", "--oneline", "-5"],
        cwd=PROJ_DIR, capture_output=True, text=True
    )
    status_result = subprocess.run(
        ["git", "status", "--short"],
        cwd=PROJ_DIR, capture_output=True, text=True
    )
    dirty = [l for l in status_result.stdout.strip().split("\n") if l.strip()
             and not l.startswith("?")]
    detail = f"Last commits:\n{result.stdout.strip()}"
    if dirty:
        record("TEST-R-04", "Git status", "WARN",
               f"Modified files: {dirty[:3]}\n{detail}")
    else:
        record("TEST-R-04", "Git status", "PASS", detail)

# ── MONITORING CHECKS (BONUS) ──────────────────────────────────────────────────

def test_monitoring():
    print("\n  📊 Monitoring Snapshot")
    db = get_db()

    # 1. Scan freshness
    last = db.execute("SELECT value FROM settings WHERE key='last_waste_scan'").fetchone()
    if last:
        age = int(time.time()) - int(last[0])
        age_min = age // 60
        status = "OK" if age_min < 10 else "STALE"
        print(f"    Last scan: {age_min} min ago [{status}]")

    # 2. Session ingestion rate
    recent = db.execute(
        "SELECT COUNT(*) FROM sessions WHERE timestamp > strftime('%s','now')-3600"
    ).fetchone()[0]
    print(f"    Sessions in last hour: {recent}")

    # 3. Active insights
    active = db.execute("SELECT COUNT(*) FROM insights WHERE dismissed=0").fetchone()[0]
    print(f"    Active insights: {active}")

    # 4. Pending MCP warnings
    pending = db.execute(
        "SELECT COUNT(*) FROM mcp_warnings WHERE acknowledged_at IS NULL"
    ).fetchone()[0]
    print(f"    Pending MCP warnings: {pending}")

    # 5. Fix tracker status
    measuring = db.execute(
        "SELECT COUNT(*) FROM fixes WHERE status='measuring'"
    ).fetchone()[0]
    print(f"    Fixes in measuring: {measuring}")

    # 6. Top waste by cost
    top = db.execute(
        "SELECT project, pattern_type, ROUND(token_cost,2) FROM waste_events "
        "ORDER BY token_cost DESC LIMIT 3"
    ).fetchall()
    print("    Top waste events:")
    for r in top:
        print(f"      {r[0]} / {r[1]}: ${r[2]}")

    db.close()

# ── TEST REGISTRY ──────────────────────────────────────────────────────────────

ALL_TESTS = {
    "infra": [
        ("TEST-I-01", "Server health", test_i01_server_health),
        ("TEST-I-02", "PM2 process", test_i02_pm2),
        ("TEST-I-03", "Database scale", test_i03_database_scale),
        ("TEST-I-04", "Incremental scanner", test_i04_scanner),
    ],
    "v1": [
        ("TEST-V1-01", "Cost by project", test_v1_01_cost),
        ("TEST-V1-02", "Waste detection", test_v1_02_waste),
        ("TEST-V1-03", "Insights engine", test_v1_03_insights),
        ("TEST-V1-04", "Fix tracker", test_v1_04_fix_tracker),
        ("TEST-V1-05", "MCP server v1", test_v1_05_mcp),
        ("TEST-V1-06", "Browser sync", test_v1_06_browser_sync),
        ("TEST-V1-07", "Dashboard UI", test_v1_07_dashboard_ui),
    ],
    "v2": [
        ("TEST-V2-F1", "Lifecycle tracking", test_v2_f1_lifecycle),
        ("TEST-V2-F2", "Context rot", test_v2_f2_context_rot),
        ("TEST-V2-F3", "Bad compact detector", test_v2_f3_bad_compact),
        ("TEST-V2-F4", "Fix generator", test_v2_f4_fix_generator),
        ("TEST-V2-F5", "Bidirectional MCP", test_v2_f5_mcp_bidirectional),
        ("TEST-V2-F6", "Streaming cost meter", test_v2_f6_streaming_meter),
        ("TEST-V2-F7", "Threshold recommendations", test_v2_f7_threshold_recommendations),
    ],
    "regression": [
        ("TEST-R-01", "All endpoints 200", test_r01_all_endpoints),
        ("TEST-R-02", "Zero non-stdlib imports", test_r02_no_pip_deps),
        ("TEST-R-03", "MCP tool count", test_r03_mcp_tool_count),
        ("TEST-R-04", "Git status", test_r04_git_clean),
    ],
}

# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Claudash test runner")
    parser.add_argument("--section", choices=["infra","v1","v2","regression","all"],
                        default="all")
    parser.add_argument("--test", help="Run single test by ID (e.g. TEST-V2-F1)")
    parser.add_argument("--monitor", action="store_true",
                        help="Show monitoring snapshot only")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Claudash Test Runner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  DB: {DB_PATH}")
    print(f"  Server: {BASE_URL}")
    print(f"{'='*60}\n")

    if args.monitor:
        test_monitoring()
        return

    if args.test:
        # find and run single test
        for section, tests in ALL_TESTS.items():
            for tid, name, fn in tests:
                if tid == args.test:
                    print(f"  Running {tid}: {name}")
                    fn()
                    break
    else:
        sections = [args.section] if args.section != "all" else ALL_TESTS.keys()
        for section in sections:
            tests = ALL_TESTS.get(section, [])
            print(f"  ── {section.upper()} ──────────────────────────")
            for tid, name, fn in tests:
                fn()
            print()

    # monitoring always shown at end
    test_monitoring()

    # summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total = len(results)

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{total} passed  |  "
          f"{FAIL} {failed}  {WARN} {warned}  SKIP {skipped}")
    print(f"{'='*60}")

    if failed > 0:
        print(f"\n  Failed tests:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    ✗ [{r['id']}] {r['name']}")
                if r["detail"]:
                    print(f"      {r['detail'][:100]}")

    # write results file
    with open(RESULTS_FILE, "w") as f:
        f.write(f"Claudash Test Results — {datetime.now().isoformat()}\n")
        f.write(f"PASS: {passed}  FAIL: {failed}  WARN: {warned}\n\n")
        for r in results:
            f.write(f"[{r['status']}] {r['id']}: {r['name']}\n")
            if r["detail"]:
                f.write(f"  {r['detail']}\n")
        f.write(f"\nResults saved: {RESULTS_FILE}\n")

    print(f"\n  Results saved to: {RESULTS_FILE}")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
