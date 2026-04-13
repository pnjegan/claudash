#!/usr/bin/env python3
"""Claudash OAuth sync — push claude.ai usage to a Claudash server using
Claude Code's existing OAuth access token.

This is the recommended collector for anyone who uses Claude Code: it
reuses the token that `claude` already put in ~/.claude/.credentials.json
so you don't need to scrape cookies or decrypt a keychain entry.

For claude.ai browser-only users (no Claude Code install), use the
companion tools/mac-sync.py script instead.

Works on Linux, macOS, and Windows. Pure Python stdlib. Zero pip deps.

Usage:
  1. On your Claudash server:
       python3 cli.py keys
     Copy the sync_token value.
  2. Edit this file, set SYNC_TOKEN to that value, and VPS_IP to your
     server (or "localhost" if you SSH-tunnel).
  3. Run:
       python3 oauth_sync.py
  4. Add to cron for automatic syncing:
       */15 * * * * /usr/bin/python3 /path/to/oauth_sync.py >/dev/null 2>&1
"""

import json
import os
import ssl
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ─── Configuration ───────────────────────────────────────────────
# Edit these three values.
VPS_IP = "localhost"
VPS_PORT = 8080
SYNC_TOKEN = ""

# Where Claude Code stores credentials. First hit wins per file; the
# script iterates all of them to support multi-account setups (one
# account_id per Claude install).
CREDENTIALS_PATHS = [
    "~/.claude/.credentials.json",
    "~/.claude-personal/.credentials.json",
    "~/.claude-work/.credentials.json",
]

# macOS keychain fallback
KEYCHAIN_SERVICE = "Claude Code-credentials"
KEYCHAIN_ACCOUNT = "Claude Code"


# ─── Credential sources ──────────────────────────────────────────

def _read_credentials_file(path):
    """Return the parsed .credentials.json or None."""
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return None
    try:
        with open(expanded, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  {path}: could not parse — {e}", file=sys.stderr)
        return None
    oauth = data.get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        return None
    return {"source": expanded, "oauth": oauth}


def _read_macos_keychain():
    """Return the parsed credentials stored in the macOS keychain, or None.
    Keychain holds the same shape as .credentials.json. Only tries on
    macOS — returns None on Linux/Windows."""
    if sys.platform != "darwin":
        return None
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-w",
             "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    oauth = data.get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        return None
    return {"source": "macOS keychain", "oauth": oauth}


def collect_credentials():
    """Yield every credential source we can find (files + keychain)."""
    seen_tokens = set()
    for path in CREDENTIALS_PATHS:
        info = _read_credentials_file(path)
        if info and info["oauth"].get("accessToken") not in seen_tokens:
            seen_tokens.add(info["oauth"]["accessToken"])
            yield info
    # Keychain as a secondary source — de-duped by accessToken above.
    info = _read_macos_keychain()
    if info and info["oauth"].get("accessToken") not in seen_tokens:
        seen_tokens.add(info["oauth"]["accessToken"])
        yield info


# ─── claude.ai API calls (OAuth Bearer) ──────────────────────────

def _bearer_request(url, access_token, timeout=15):
    """Authenticated GET to claude.ai using the OAuth access token.
    Returns (data_dict, None) on success, (None, error_str) on failure."""
    req = Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Claudash-oauth-sync/1.0")
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body), None
    except HTTPError as e:
        if e.code in (401, 403):
            return None, "expired"
        return None, f"http_{e.code}"
    except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
        return None, f"network_error:{type(e).__name__}"


def fetch_account(access_token):
    """GET /api/account → (email, org_id, plan) or (None, None, None)."""
    data, err = _bearer_request("https://claude.ai/api/account", access_token)
    if err or not data:
        return None, None, None, err
    email = data.get("email_address") or data.get("email") or ""
    org_id = ""
    plan = "max"
    memberships = data.get("memberships") or data.get("organizations") or []
    if isinstance(memberships, list) and memberships:
        first = memberships[0]
        org = first.get("organization") if isinstance(first, dict) else None
        if isinstance(org, dict):
            org_id = org.get("uuid") or ""
            caps = org.get("capabilities") or []
            if isinstance(caps, list):
                joined = " ".join(str(c).lower() for c in caps)
                if "max" in joined:
                    plan = "max"
                elif "pro" in joined:
                    plan = "pro"
        elif isinstance(first, dict):
            org_id = first.get("uuid") or first.get("id") or ""
    return email, org_id, plan, None


def fetch_usage(access_token, org_id):
    """GET /api/organizations/{org_id}/usage → normalized usage dict."""
    if not org_id:
        return None, "no_org_id"
    url = f"https://claude.ai/api/organizations/{org_id}/usage"
    data, err = _bearer_request(url, access_token)
    if err or not data:
        return None, err

    five_hour = data.get("five_hour") or {}
    seven_day = data.get("seven_day") or {}
    extra = data.get("extra_usage") or {}
    pct_used = float(five_hour.get("utilization") or 0)

    # Parse reset timestamp → epoch
    window_end = 0
    resets_at = five_hour.get("resets_at") or five_hour.get("reset_at")
    if isinstance(resets_at, str):
        try:
            from datetime import datetime, timezone as _tz
            clean = resets_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            window_end = int(dt.timestamp())
        except Exception:
            window_end = 0
    window_start = (window_end - 18000) if window_end else 0

    return {
        "pct_used": round(pct_used, 2),
        "five_hour_utilization": pct_used,
        "seven_day_utilization": float(seven_day.get("utilization") or 0),
        "extra_credits_used": float(extra.get("used_credits") or 0),
        "extra_credits_limit": float(extra.get("monthly_limit") or 0),
        "window_start": window_start,
        "window_end": window_end,
        "tokens_used": int(pct_used * 10_000),  # normalized estimate
        "tokens_limit": 1_000_000,
        "messages_used": 0,
        "messages_limit": 0,
        "raw": json.dumps(data),
    }, None


# ─── Push to Claudash server ─────────────────────────────────────

def push_to_claudash(access_token, org_id, email, usage, plan):
    url = f"http://{VPS_IP}:{VPS_PORT}/api/claude-ai/sync"
    payload = {
        "session_key": access_token,  # stored verbatim on the server
        "org_id": org_id,
        "browser": "oauth",
        "account_hint": email,
        "plan": plan,
    }
    if usage:
        payload["usage"] = usage
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Sync-Token", SYNC_TOKEN)
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return data.get("success", False), data
    except HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            err_body = {"error": f"HTTP {e.code}"}
        return False, err_body
    except (URLError, OSError) as e:
        return False, {"error": f"network: {e}"}


# ─── Main ────────────────────────────────────────────────────────

def main():
    if not SYNC_TOKEN:
        print("ERROR: SYNC_TOKEN is empty.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Get your token on the Claudash server:", file=sys.stderr)
        print("  python3 cli.py keys", file=sys.stderr)
        print("", file=sys.stderr)
        print("Then edit this file and set SYNC_TOKEN at the top.", file=sys.stderr)
        sys.exit(1)

    sources = list(collect_credentials())
    if not sources:
        print("No Claude Code credentials found.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Run 'claude' in your terminal to authenticate first,", file=sys.stderr)
        print("or edit CREDENTIALS_PATHS at the top of this file.", file=sys.stderr)
        sys.exit(2)

    pushed = 0
    for src in sources:
        oauth = src["oauth"]
        token = oauth.get("accessToken") or ""
        expires_at = oauth.get("expiresAt") or 0
        # Claude Code stores expiresAt in milliseconds
        if expires_at and expires_at > 1e12:
            expires_at_sec = expires_at / 1000.0
        else:
            expires_at_sec = expires_at or 0
        if expires_at_sec and expires_at_sec < time.time():
            print(f"  {src['source']}: token expired at "
                  f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires_at_sec))}",
                  file=sys.stderr)
            continue

        email, org_id, plan, err = fetch_account(token)
        if err == "expired":
            print(f"  {src['source']}: token rejected by claude.ai "
                  "(run `claude` to refresh)", file=sys.stderr)
            continue
        if err:
            print(f"  {src['source']}: account lookup failed — {err}", file=sys.stderr)
            continue
        if not org_id:
            print(f"  {src['source']}: no org_id in /api/account response", file=sys.stderr)
            continue

        usage, usage_err = fetch_usage(token, org_id)
        if usage_err:
            print(f"  {src['source']}: {email} ({plan}) — usage fetch failed ({usage_err})", file=sys.stderr)
            usage = None

        ok, resp = push_to_claudash(token, org_id, email, usage, plan)
        if ok:
            pct = (usage or {}).get("pct_used", 0)
            pct_str = f" — {pct:.1f}%" if usage else ""
            print(f"  {src['source']}: {email or '(no email)'} ({plan}){pct_str} → pushed OK")
            pushed += 1
        else:
            print(f"  {src['source']}: push failed — {resp.get('error') if isinstance(resp, dict) else resp}", file=sys.stderr)

    print()
    print(f"Claudash OAuth sync complete: {pushed}/{len(sources)} accounts pushed")
    sys.exit(0 if pushed > 0 else 3)


if __name__ == "__main__":
    main()
