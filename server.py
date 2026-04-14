import hmac
import json
import os
import sys
import re
import time
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from db import (
    get_conn, query_alerts, get_session_count, get_db_size_mb,
    get_latest_claude_ai_usage, get_claude_ai_history,
    get_insights, dismiss_insight, get_daily_snapshots, get_window_burns,
    get_all_accounts, get_account_projects, get_accounts_config,
    create_account, update_account, delete_account,
    add_account_project, remove_account_project,
    get_claude_ai_accounts_all, get_claude_ai_account,
    get_latest_claude_ai_snapshot, get_claude_ai_snapshot_history,
    clear_claude_ai_session,
    get_setting,
    upsert_claude_ai_account, update_claude_ai_account_status,
    insert_claude_ai_snapshot,
    get_real_story_insights,
)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
from _version import VERSION
from analyzer import full_analysis, project_metrics, window_intelligence, trend_metrics
from scanner import scan_all, get_last_scan_time, preview_paths, discover_claude_paths
from insights import generate_insights
from claude_ai_tracker import (
    poll_all as poll_claude_ai, get_account_statuses, get_last_poll_time,
    setup_account as tracker_setup_account, poll_single as tracker_poll_single,
)

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# Response cache for /api/data — {account: (timestamp, result)}
_data_cache = {}
CACHE_TTL = 30  # seconds
_server_start_time = time.time()


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._serve_template("dashboard.html")

        elif path == "/accounts":
            self._serve_template("accounts.html")

        elif path == "/api/data":
            account = params.get("account", ["all"])[0]
            self._serve_json(self._get_data(account))

        elif path == "/api/projects":
            account = params.get("account", ["all"])[0]
            conn = get_conn()
            data = project_metrics(conn, account)
            conn.close()
            self._serve_json(data)

        elif path == "/api/insights":
            account = params.get("account", [None])[0]
            dismissed = int(params.get("dismissed", ["0"])[0])
            conn = get_conn()
            rows = get_insights(conn, account, dismissed)
            conn.close()
            self._serve_json([dict(r) for r in rows])

        elif path == "/api/window":
            account = params.get("account", ["personal_max"])[0]
            conn = get_conn()
            data = window_intelligence(conn, account)
            conn.close()
            self._serve_json(data)

        elif path == "/api/trends":
            account = params.get("account", ["all"])[0]
            days = int(params.get("days", ["7"])[0])
            conn = get_conn()
            data = trend_metrics(conn, account, days)
            conn.close()
            self._serve_json(data)

        elif path == "/api/alerts":
            conn = get_conn()
            alerts = [dict(r) for r in query_alerts(conn)]
            conn.close()
            self._serve_json(alerts)

        elif path == "/api/claude-ai":
            conn = get_conn()
            latest = [dict(r) for r in get_latest_claude_ai_usage(conn)]
            history = [dict(r) for r in get_claude_ai_history(conn)]
            statuses = get_account_statuses()
            conn.close()
            self._serve_json({
                "accounts": latest,
                "history": history,
                "statuses": statuses,
                "last_poll": get_last_poll_time(),
            })

        elif path == "/api/health":
            conn = get_conn()
            total = get_session_count(conn)
            accounts = get_accounts_config(conn)
            conn.close()
            self._serve_json({
                "db_size_mb": get_db_size_mb(),
                "total_records": total,
                "last_scan": get_last_scan_time(),
                "accounts_active": list(accounts.keys()),
            })

        elif path == "/api/real-story":
            import time as _time
            stories = get_real_story_insights()
            conn = get_conn()
            total = get_session_count(conn)
            conn.close()
            self._serve_json({
                "stories": stories,
                "generated_at": int(_time.time()),
                "sessions_analyzed": total,
                "date_range_days": 30,
            })

        # ── Account management GET endpoints ──
        elif path == "/api/accounts":
            conn = get_conn()
            accounts = get_all_accounts(conn)
            # Add session stats per account
            for a in accounts:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) as cnt, COALESCE(SUM(cost_usd),0) as cost "
                    "FROM sessions WHERE account = ? AND timestamp >= ?",
                    (a["account_id"], int((__import__("time").time()) - 30 * 86400)),
                ).fetchone()
                a["sessions_30d"] = row["cnt"] if row else 0
                a["cost_30d"] = round(row["cost"], 2) if row else 0
            conn.close()
            self._serve_json(accounts)

        elif re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/projects$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/projects$", path)
            account_id = m.group(1)
            conn = get_conn()
            data = get_account_projects(conn, account_id)
            conn.close()
            self._serve_json(data)

        elif re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/preview$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/preview$", path)
            account_id = m.group(1)
            conn = get_conn()
            row = conn.execute("SELECT data_paths FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            conn.close()
            if not row:
                self._serve_json({"error": "account not found"}, 404)
                return
            paths = json.loads(row["data_paths"]) if row["data_paths"] else []
            info = preview_paths(paths)
            total_est = sum(p["jsonl_files"] for p in info)
            self._serve_json({
                "paths": info,
                "estimated_records": total_est,
            })

        # ── claude.ai browser tracking GET endpoints ──
        elif path == "/api/claude-ai/accounts":
            conn = get_conn()
            accounts = get_claude_ai_accounts_all(conn)
            # Attach latest snapshot to each
            for a in accounts:
                snap = get_latest_claude_ai_snapshot(conn, a["account_id"])
                a["latest_snapshot"] = snap
                # Never expose session_key in API responses
                a.pop("session_key", None)
            conn.close()
            self._serve_json(accounts)

        elif re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/history$", path):
            m = re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/history$", path)
            account_id = m.group(1)
            conn = get_conn()
            history = get_claude_ai_snapshot_history(conn, account_id, 48)
            conn.close()
            self._serve_json(history)

        elif path == "/tools/mac-sync.py":
            self._serve_mac_sync()

        # ── Fix tracker GET endpoints ──
        elif path == "/api/fixes":
            from fix_tracker import all_fixes_with_latest
            conn = get_conn()
            data = all_fixes_with_latest(conn)
            conn.close()
            self._serve_json(data)

        elif re.match(r"^/api/fixes/(\d+)$", path):
            m = re.match(r"^/api/fixes/(\d+)$", path)
            fix_id = int(m.group(1))
            from fix_tracker import fix_with_latest
            conn = get_conn()
            data = fix_with_latest(conn, fix_id)
            conn.close()
            if data is None:
                self._serve_json({"error": "fix not found"}, 404)
            else:
                self._serve_json(data)

        elif re.match(r"^/api/fixes/(\d+)/share-card$", path):
            m = re.match(r"^/api/fixes/(\d+)/share-card$", path)
            fix_id = int(m.group(1))
            from db import get_fix, get_latest_fix_measurement
            from fix_tracker import build_share_card
            conn = get_conn()
            fix = get_fix(conn, fix_id)
            latest = get_latest_fix_measurement(conn, fix_id) if fix else None
            conn.close()
            if not fix:
                self._serve_json({"error": "fix not found"}, 404)
            else:
                text = build_share_card(fix, latest)
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self._cors_origin())
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        elif path == "/health":
            conn = get_conn()
            total = get_session_count(conn)
            conn.close()
            last_scan = get_last_scan_time()
            last_scan_iso = datetime.fromtimestamp(last_scan, tz=timezone.utc).isoformat() if last_scan else None
            self._serve_json({
                "status": "ok",
                "version": VERSION,
                "uptime_seconds": int(time.time() - _server_start_time),
                "records": total,
                "last_scan": last_scan_iso,
            })

        else:
            self._serve_404()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._check_origin():
            return

        # Body size guard — cap at 100 KB
        if int(self.headers.get("Content-Length", 0) or 0) > 102400:
            self._serve_json({"error": "request too large"}, 413)
            return

        # /api/claude-ai/sync keeps its existing X-Sync-Token check (for mac-sync.py).
        # All other write endpoints require X-Dashboard-Key.
        if path != "/api/claude-ai/sync" and not self._require_dashboard_key():
            return

        body = self._read_body()

        if path == "/api/scan":
            _data_cache.clear()
            rows = scan_all()
            conn = get_conn()
            insights_count = generate_insights(conn)
            conn.close()
            self._serve_json({"status": "ok", "rows_added": rows, "insights_generated": insights_count})

        elif re.match(r"^/api/insights/(\d+)/dismiss$", path):
            match = re.match(r"^/api/insights/(\d+)/dismiss$", path)
            insight_id = int(match.group(1))
            conn = get_conn()
            dismiss_insight(conn, insight_id)
            conn.close()
            self._serve_json({"status": "ok", "id": insight_id})

        elif path == "/api/claude-ai/poll":
            count = poll_claude_ai()
            self._serve_json({"status": "ok", "accounts_polled": count})

        # ── Account management POST endpoints ──
        elif path == "/api/accounts":
            data = body or {}
            conn = get_conn()
            ok, err = create_account(conn, data)
            conn.close()
            if ok:
                self._serve_json({"success": True, "account_id": data.get("account_id")})
            else:
                self._serve_json({"success": False, "error": err}, 400)

        elif re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/projects$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/projects$", path)
            account_id = m.group(1)
            data = body or {}
            conn = get_conn()
            ok, err = add_account_project(conn, account_id, data.get("project_name", ""), data.get("keywords", []))
            conn.close()
            if ok:
                self._serve_json({"success": True})
            else:
                self._serve_json({"success": False, "error": err}, 400)

        elif re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/scan$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/scan$", path)
            account_id = m.group(1)
            rows = scan_all(account_filter=account_id)
            conn = get_conn()
            insights_count = generate_insights(conn)
            conn.close()
            self._serve_json({"status": "ok", "rows_added": rows, "insights_generated": insights_count})

        elif path == "/api/accounts/discover":
            discovered = discover_claude_paths()
            self._serve_json({"discovered_paths": discovered})

        # ── claude.ai browser tracking POST endpoints ──
        elif re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/setup$", path):
            m = re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/setup$", path)
            account_id = m.group(1)
            data = body or {}
            session_key = data.get("session_key", "").strip()
            if not session_key:
                self._serve_json({"success": False, "error": "session_key is required"}, 400)
            else:
                result = tracker_setup_account(account_id, session_key)
                status = 200 if result.get("success") else 400
                self._serve_json(result, status)

        elif re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/refresh$", path):
            m = re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/refresh$", path)
            account_id = m.group(1)
            conn = get_conn()
            snap = tracker_poll_single(account_id, conn)
            acct = get_claude_ai_account(conn, account_id)
            conn.close()
            # Never expose session_key
            if acct:
                acct.pop("session_key", None)
            self._serve_json({
                "success": snap is not None and "error" not in (snap or {}),
                "account": acct,
                "snapshot": snap if snap and "error" not in snap else None,
            })

        elif path == "/api/claude-ai/sync":
            self._handle_sync(body or {})

        # ── Fix tracker POST endpoints ──
        elif path == "/api/fixes":
            data = body or {}
            project = (data.get("project") or "").strip()
            if not project:
                self._serve_json({"success": False, "error": "project is required"}, 400)
                return
            from fix_tracker import record_fix
            conn = get_conn()
            try:
                fix_id, baseline = record_fix(
                    conn,
                    project,
                    data.get("waste_pattern") or "custom",
                    (data.get("title") or "").strip(),
                    data.get("fix_type") or "other",
                    data.get("fix_detail") or "",
                )
            finally:
                conn.close()
            self._serve_json({
                "success": True,
                "fix_id": fix_id,
                "baseline": baseline,
                "message": "Fix recorded. Check back in 7 days to measure improvement.",
            })

        elif re.match(r"^/api/fixes/(\d+)/measure$", path):
            m = re.match(r"^/api/fixes/(\d+)/measure$", path)
            fix_id = int(m.group(1))
            from fix_tracker import measure_fix
            conn = get_conn()
            try:
                delta, verdict, metrics = measure_fix(conn, fix_id)
            finally:
                conn.close()
            if delta is None:
                self._serve_json({"success": False, "error": "fix not found"}, 404)
            else:
                msg = {
                    "improving": "Fix is working. Keep it in place.",
                    "worsened": "Fix regressed. Consider reverting or iterating.",
                    "neutral": "No statistically meaningful change yet.",
                    "insufficient_data": "Not enough sessions since fix — give it more time.",
                }.get(verdict, "Measurement recorded.")
                self._serve_json({
                    "success": True,
                    "delta": delta,
                    "verdict": verdict,
                    "message": msg,
                })

        else:
            self.send_error(404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._check_origin():
            return

        if int(self.headers.get("Content-Length", 0) or 0) > 102400:
            self._serve_json({"error": "request too large"}, 413)
            return

        if not self._require_dashboard_key():
            return

        body = self._read_body()

        if re.match(r"^/api/accounts/([a-z][a-z0-9_]*)$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)$", path)
            account_id = m.group(1)
            data = body or {}
            conn = get_conn()
            ok, err = update_account(conn, account_id, data)
            conn.close()
            if ok:
                # Re-scan if data_paths changed
                if "data_paths" in data:
                    scan_all(account_filter=account_id)
                self._serve_json({"success": True})
            else:
                self._serve_json({"success": False, "error": err}, 400)
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._check_origin():
            return

        if not self._require_dashboard_key():
            return

        if re.match(r"^/api/accounts/([a-z][a-z0-9_]*)$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)$", path)
            account_id = m.group(1)
            conn = get_conn()
            ok, err = delete_account(conn, account_id)
            conn.close()
            if ok:
                self._serve_json({"success": True})
            else:
                self._serve_json({"success": False, "error": err}, 400)

        elif re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/projects/(.+)$", path):
            m = re.match(r"^/api/accounts/([a-z][a-z0-9_]*)/projects/(.+)$", path)
            account_id = m.group(1)
            project_name = m.group(2)
            conn = get_conn()
            ok, err = remove_account_project(conn, account_id, project_name)
            conn.close()
            if ok:
                self._serve_json({"success": True})
            else:
                self._serve_json({"success": False, "error": err}, 400)

        elif re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/session$", path):
            m = re.match(r"^/api/claude-ai/accounts/([a-z][a-z0-9_]*)/session$", path)
            account_id = m.group(1)
            conn = get_conn()
            clear_claude_ai_session(conn, account_id)
            conn.close()
            self._serve_json({"success": True})

        elif re.match(r"^/api/fixes/(\d+)$", path):
            m = re.match(r"^/api/fixes/(\d+)$", path)
            fix_id = int(m.group(1))
            from db import update_fix_status, get_fix
            conn = get_conn()
            try:
                fix = get_fix(conn, fix_id)
                if not fix:
                    self._serve_json({"success": False, "error": "fix not found"}, 404)
                    return
                update_fix_status(conn, fix_id, "reverted")
            finally:
                conn.close()
            self._serve_json({"success": True})

        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Dashboard-Key, X-Sync-Token")
        self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
        return {}

    def _check_origin(self):
        """Reject cross-origin mutating requests. Origin is only sent by browsers;
        direct curl/script calls omit it and are allowed through (auth still required)."""
        allowed = {"http://127.0.0.1:8080", "http://localhost:8080"}
        origin = self.headers.get("Origin", "")
        if origin and origin not in allowed:
            self._serve_json({"error": "forbidden"}, 403)
            return False
        return True

    def _require_dashboard_key(self):
        """Enforce X-Dashboard-Key header on write endpoints. Returns True on pass;
        on failure writes 401 and returns False."""
        received = self.headers.get("X-Dashboard-Key", "").strip()
        conn = get_conn()
        try:
            stored = get_setting(conn, "dashboard_key")
        finally:
            conn.close()
        if not stored or not hmac.compare_digest(received.encode("utf-8"), stored.strip().encode("utf-8")):
            self._serve_json({"error": "unauthorized"}, 401)
            return False
        return True

    def _serve_template(self, filename):
        filename = os.path.basename(filename)
        filepath = os.path.join(TEMPLATE_DIR, filename)
        try:
            with open(filepath, "r") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        except FileNotFoundError:
            self.send_error(500, f"{filename} not found")

    def _cors_origin(self):
        origin = self.headers.get("Origin", "")
        allowed = {"http://127.0.0.1:8080", "http://localhost:8080"}
        return origin if origin in allowed else "http://127.0.0.1:8080"

    def _serve_json(self, data, status=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def _serve_404(self):
        html = (
            '<!DOCTYPE html>\n<html>\n<head>\n'
            '  <title>Claudash</title>\n'
            '  <meta http-equiv="refresh" content="5;url=/">\n'
            '  <style>\n'
            '    body { font-family: monospace; padding: 40px;\n'
            '           background: #F5F0E8; color: #1A1916; }\n'
            '    code { background: #E8E0D0; padding: 2px 6px; }\n'
            '  </style>\n'
            '</head>\n<body>\n'
            '  <h2>Claudash</h2>\n'
            '  <p>Page not found. Redirecting to dashboard in 5 seconds...</p>\n'
            '  <p>If this keeps happening: <a href="/">click here</a></p>\n'
            '</body>\n</html>'
        )
        body = html.encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mac_sync(self):
        """Serve tools/mac-sync.py as-is. The sync token is NOT injected — the
        user must retrieve it via `python3 cli.py claude-ai --sync-token` on the
        VPS and paste it into SYNC_TOKEN manually. This removes the token-leak
        vector where any caller could download a pre-filled script."""
        filepath = os.path.join(PROJECT_DIR, "tools", "mac-sync.py")
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="mac-sync.py"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(500, "tools/mac-sync.py not found")

    def _handle_sync(self, data):
        """Handle POST /api/claude-ai/sync from mac-sync.py.
        Trust boundary is the sync token — if it matches, we trust the pushed data."""
        received_token = self.headers.get("X-Sync-Token", "").strip()
        conn = get_conn()
        try:
            stored_token = get_setting(conn, "sync_token")
            if not stored_token or not hmac.compare_digest(received_token.encode("utf-8"), stored_token.strip().encode("utf-8")):
                self._serve_json({"success": False, "error": "Invalid sync token"}, 403)
                return

            session_key = data.get("session_key", "").strip()
            org_id = data.get("org_id", "").strip()
            browser = data.get("browser", "")
            account_hint = data.get("account_hint", "")

            if not session_key:
                self._serve_json({"success": False, "error": "session_key required"}, 400)
                return

            accounts = get_claude_ai_accounts_all(conn)
            target_id = None
            target_label = ""

            for a in accounts:
                if a.get("org_id") == org_id and org_id:
                    target_id = a["account_id"]
                    target_label = a.get("label", target_id)
                    break

            if not target_id and account_hint:
                hint_lower = account_hint.lower()
                for a in accounts:
                    label_lower = (a.get("label") or "").lower()
                    if any(word in hint_lower for word in label_lower.split() if len(word) > 2):
                        target_id = a["account_id"]
                        target_label = a.get("label", target_id)
                        break

            if not target_id:
                for a in accounts:
                    if a.get("status") == "unconfigured":
                        target_id = a["account_id"]
                        target_label = a.get("label", target_id)
                        break

            if not target_id and accounts:
                target_id = accounts[0]["account_id"]
                target_label = accounts[0].get("label", target_id)
                print(f"WARNING: no org_id match for {org_id}, falling back to {target_id}", file=sys.stderr)
                print("Check your config.py ACCOUNTS org_id settings", file=sys.stderr)

            if not target_id:
                self._serve_json({"success": False, "error": "No accounts configured"}, 400)
                return

            acct_row = conn.execute(
                "SELECT plan FROM accounts WHERE account_id = ?", (target_id,)
            ).fetchone()
            plan = acct_row["plan"] if acct_row else "max"

            upsert_claude_ai_account(conn, target_id, target_label, org_id, session_key, plan, "active")
            conn.execute(
                "UPDATE claude_ai_accounts SET mac_sync_mode = 1 WHERE account_id = ?",
                (target_id,),
            )
            update_claude_ai_account_status(conn, target_id, "active", None)
            print(f"[sync] Stored session for {target_id} from {browser} ({account_hint})", file=sys.stderr)

            pct_used = 0
            usage = data.get("usage")
            if usage and isinstance(usage, dict):
                insert_claude_ai_snapshot(conn, target_id, usage)
                pct_used = usage.get("pct_used", 0)
                print(f"[sync] Stored usage snapshot for {target_id}: {pct_used}% used", file=sys.stderr)

            self._serve_json({
                "success": True,
                "account_label": target_label,
                "matched_account": target_id,
                "pct_used": pct_used,
                "browser": browser,
            })
        finally:
            conn.close()

    def _get_data(self, account):
        # Check cache first
        cached = _data_cache.get(account)
        if cached and (time.time() - cached[0]) < CACHE_TTL:
            return cached[1]

        # Run analysis with 10-second timeout
        result_holder = [None]
        error_holder = [None]

        def run_analysis():
            try:
                conn = get_conn()
                result_holder[0] = self._build_data(conn, account)
                conn.close()
            except Exception as e:
                error_holder[0] = str(e)

        t = threading.Thread(target=run_analysis)
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            return {"error": "Analysis timeout — DB may be under load"}
        if error_holder[0]:
            return {"error": error_holder[0]}

        data = result_holder[0]
        _data_cache[account] = (time.time(), data)
        return data

    def _build_data(self, conn, account):
        data = full_analysis(conn, account)
        data["last_scan"] = get_last_scan_time()
        data["total_rows"] = get_session_count(conn)
        if data["total_rows"] == 0:
            data["first_run"] = True
            data["first_run_message"] = (
                "No sessions found. "
                "Run: python3 cli.py scan\n"
                "Then check that ~/.claude/projects/ contains JSONL files."
            )
        data["db_size_mb"] = get_db_size_mb()
        # claude.ai browser tracking data
        browser_accounts = get_claude_ai_accounts_all(conn)
        browser_data = {}
        for ba in browser_accounts:
            aid = ba["account_id"]
            snap = get_latest_claude_ai_snapshot(conn, aid)
            browser_data[aid] = {
                "status": ba.get("status", "unconfigured"),
                "label": ba.get("label", aid),
                "plan": ba.get("plan", "max"),
                "last_polled": ba.get("last_polled"),
                "snapshot": snap,
            }
        data["claude_ai_browser"] = browser_data
        data["claude_ai"] = {
            "accounts": [dict(r) for r in get_latest_claude_ai_usage(conn)],
            "statuses": get_account_statuses(),
            "last_poll": get_last_poll_time(),
        }
        conn.close()
        return data

    def log_message(self, format, *args):
        print(f"[server] {args[0]}", file=sys.stderr)


def start_server(port=8080):
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{port} (localhost only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] Shutting down", file=sys.stderr)
        server.server_close()
