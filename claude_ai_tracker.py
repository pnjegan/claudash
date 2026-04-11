"""Poll claude.ai browser usage API for configured accounts.
Session keys stored in SQLite only — never logged or written to files."""

import json
import sys
import time
import ssl
import threading
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from db import (
    get_conn, get_claude_ai_accounts_all, get_claude_ai_account,
    update_claude_ai_account_status, insert_claude_ai_snapshot,
    get_latest_claude_ai_snapshot, upsert_claude_ai_account,
)

_last_poll_time = 0
_account_statuses = {}


def get_last_poll_time():
    return _last_poll_time


def get_account_statuses():
    return dict(_account_statuses)


def _ssl_ctx():
    return ssl.create_default_context()


def _parse_iso(ts_str):
    """Parse ISO 8601 timestamp to epoch int."""
    if not ts_str:
        return 0
    try:
        clean = ts_str.replace("Z", "").replace("+00:00", "")
        if "." in clean:
            clean = clean.split(".")[0]
        dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def _safe_request(url, session_key, method="GET"):
    """Make an authenticated request to claude.ai. Returns (data_dict, None) or (None, error_str).
    NEVER logs session_key."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cookie": f"sessionKey={session_key}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    req = Request(url, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15, context=_ssl_ctx()) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body), None
    except HTTPError as e:
        if e.code in (401, 403):
            return None, "expired"
        return None, f"http_{e.code}"
    except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
        return None, f"network_error"


# ── Public API ──

def fetch_org_id(session_key):
    """GET https://claude.ai/api/account → extract organizations[0].uuid.
    Returns org_id string or None."""
    data, err = _safe_request("https://claude.ai/api/account", session_key)
    if err or not data:
        return None
    # Response shape: {"account_uuid": ..., "organizations": [{"uuid": "..."}]}
    orgs = data.get("organizations") or data.get("memberships", [])
    if isinstance(orgs, list) and orgs:
        org = orgs[0]
        return org.get("uuid") or org.get("organization", {}).get("uuid") or org.get("id")
    # Fallback: top-level uuid
    return data.get("uuid") or data.get("org_id")


def verify_session(session_key):
    """Verify a session key is valid. Returns {valid, org_id, error}."""
    if not session_key or not session_key.strip():
        return {"valid": False, "org_id": None, "error": "Session key is empty"}

    org_id = fetch_org_id(session_key)
    if org_id:
        return {"valid": True, "org_id": org_id, "error": None}

    # Try direct — maybe the API shape changed
    data, err = _safe_request("https://claude.ai/api/account", session_key)
    if err == "expired":
        return {"valid": False, "org_id": None, "error": "Session key invalid or expired"}
    if err:
        return {"valid": False, "org_id": None, "error": f"Connection error: {err}"}
    return {"valid": False, "org_id": None, "error": "Could not extract org_id from response"}


def fetch_usage(session_key, org_id, plan="max"):
    """Fetch usage for an account. Returns normalized dict or None.
    For Max: token-based window. For Pro: message-based."""
    if not session_key or not org_id:
        return None

    url = f"https://claude.ai/api/organizations/{org_id}/usage"
    data, err = _safe_request(url, session_key)

    if err == "expired":
        return {"error": "expired"}
    if err or not data:
        return {"error": err or "unknown"}

    raw = json.dumps(data)

    tokens_used = 0
    tokens_limit = 0
    messages_used = 0
    messages_limit = 0
    window_start = 0
    window_end = 0

    # Parse reset_at → window_end
    reset_at = data.get("reset_at") or data.get("expires_at") or data.get("window_end")
    if isinstance(reset_at, str):
        window_end = _parse_iso(reset_at)
    elif isinstance(reset_at, (int, float)):
        window_end = int(reset_at)

    # window_start = window_end - 5 hours (standard Anthropic window)
    if window_end > 0:
        window_start = window_end - (5 * 3600)

    # Try extracting message counts (Pro plan)
    if "messageLimit" in data:
        ml = data["messageLimit"]
        remaining = ml.get("remaining", 0) or 0
        limit = ml.get("limit", 0) or 0
        messages_limit = limit
        messages_used = limit - remaining if limit > 0 else 0

    if "raw_message_count" in data:
        messages_used = data["raw_message_count"]
    if "message_limit" in data:
        messages_limit = data["message_limit"]

    # Token-based usage (Max plan)
    if "usage" in data and isinstance(data["usage"], dict):
        u = data["usage"]
        tokens_used = u.get("tokens_used", 0) or u.get("used", 0) or 0
        tokens_limit = u.get("tokens_limit", 0) or u.get("limit", 0) or 0

    # Fallback: top-level token fields
    if tokens_used == 0 and tokens_limit == 0:
        for key in ("tokens_used", "used_tokens", "current_usage", "used"):
            if key in data and data[key]:
                tokens_used = data[key]
                break
        for key in ("tokens_limit", "token_limit", "limit", "max_tokens"):
            if key in data and data[key]:
                tokens_limit = data[key]
                break

    # Compute unified pct_used
    if plan == "pro" and messages_limit > 0:
        pct_used = round(messages_used / messages_limit * 100, 1)
    elif tokens_limit > 0:
        pct_used = round(tokens_used / tokens_limit * 100, 1)
    else:
        pct_used = 0

    return {
        "tokens_used": tokens_used,
        "tokens_limit": tokens_limit,
        "messages_used": messages_used,
        "messages_limit": messages_limit,
        "window_start": window_start,
        "window_end": window_end,
        "pct_used": pct_used,
        "plan": plan,
        "raw": raw,
    }


def poll_single(account_id, conn=None):
    """Poll a single account. Returns snapshot dict or None."""
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True

    acct = get_claude_ai_account(conn, account_id)
    if not acct:
        if should_close:
            conn.close()
        return None

    sk = acct.get("session_key", "").strip()
    oid = acct.get("org_id", "").strip()
    plan = acct.get("plan", "max")
    label = acct.get("label", account_id)

    # Skip mac-sync accounts — Mac pushes data, VPS doesn't poll
    if acct.get("mac_sync_mode"):
        print(f"[claude.ai] {label}: mac-sync mode, skipping poll", file=sys.stderr)
        if should_close:
            conn.close()
        return None

    if not sk or not oid:
        _account_statuses[account_id] = {"status": "unconfigured", "label": label}
        if should_close:
            conn.close()
        return None

    result = fetch_usage(sk, oid, plan)
    if not result:
        update_claude_ai_account_status(conn, account_id, "error", "No response")
        _account_statuses[account_id] = {"status": "error", "label": label, "error": "No response"}
        if should_close:
            conn.close()
        return None

    if "error" in result:
        err = result["error"]
        if err == "expired":
            update_claude_ai_account_status(conn, account_id, "expired", "Session expired")
            _account_statuses[account_id] = {"status": "expired", "label": label}
        else:
            update_claude_ai_account_status(conn, account_id, "error", err)
            _account_statuses[account_id] = {"status": "error", "label": label, "error": err}
        if should_close:
            conn.close()
        return None

    # Success
    insert_claude_ai_snapshot(conn, account_id, result)
    update_claude_ai_account_status(conn, account_id, "active", None)

    _account_statuses[account_id] = {
        "status": "active",
        "label": label,
        "pct_used": result["pct_used"],
        "tokens_used": result["tokens_used"],
        "tokens_limit": result["tokens_limit"],
        "messages_used": result["messages_used"],
        "messages_limit": result["messages_limit"],
        "plan": plan,
    }

    if plan == "pro" and result["messages_limit"] > 0:
        print(f"[claude.ai] {label}: {result['messages_used']}/{result['messages_limit']} messages used", file=sys.stderr)
    else:
        print(f"[claude.ai] {label}: {result['pct_used']}% used", file=sys.stderr)

    if should_close:
        conn.close()
    return result


def poll_all():
    """Poll all configured claude.ai accounts (status != unconfigured)."""
    global _last_poll_time
    conn = get_conn()
    accounts = get_claude_ai_accounts_all(conn)
    count = 0

    for acct in accounts:
        aid = acct["account_id"]
        sk = (acct.get("session_key") or "").strip()
        oid = (acct.get("org_id") or "").strip()
        label = acct.get("label", aid)

        # Skip mac-sync accounts — Mac pushes data, VPS doesn't poll
        if acct.get("mac_sync_mode"):
            print(f"[claude.ai] {label}: mac-sync mode, skipping poll", file=sys.stderr)
            continue

        if not sk or not oid:
            _account_statuses[aid] = {"status": "unconfigured", "label": label}
            continue

        try:
            result = poll_single(aid, conn)
            if result and "error" not in result:
                count += 1
        except Exception as e:
            print(f"[claude.ai] Error polling {aid}: {e}", file=sys.stderr)
            _account_statuses[aid] = {"status": "error", "label": label, "error": str(e)}

    conn.close()
    _last_poll_time = int(time.time())
    print(f"[claude.ai] Poll complete: {count}/{len(accounts)} accounts updated", file=sys.stderr)
    return count


def start_periodic_poll(interval_seconds=300):
    def _run():
        while True:
            try:
                poll_all()
            except Exception as e:
                print(f"[claude.ai] Periodic poll error: {e}", file=sys.stderr)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def setup_account(account_id, session_key):
    """Verify session key, extract org_id, store in DB, poll immediately.
    Returns {success, error, org_id, plan, pct_used, label}."""
    conn = get_conn()

    # Get account info
    acct_row = conn.execute("SELECT label, plan FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    if not acct_row:
        conn.close()
        return {"success": False, "error": f"Account '{account_id}' not found"}

    label = acct_row["label"]
    plan = acct_row["plan"]

    # Verify session
    verification = verify_session(session_key)
    if not verification["valid"]:
        conn.close()
        return {"success": False, "error": verification["error"]}

    org_id = verification["org_id"]

    # Store in DB
    upsert_claude_ai_account(conn, account_id, label, org_id, session_key, plan, "active")

    # Immediately poll
    result = fetch_usage(session_key, org_id, plan)
    pct_used = 0
    if result and "error" not in result:
        insert_claude_ai_snapshot(conn, account_id, result)
        update_claude_ai_account_status(conn, account_id, "active", None)
        pct_used = result.get("pct_used", 0)

    conn.close()

    return {
        "success": True,
        "org_id": org_id,
        "plan": plan,
        "pct_used": pct_used,
        "label": label,
    }
