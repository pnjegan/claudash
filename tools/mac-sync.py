#!/usr/bin/env python3
"""
mac-sync.py — Push claude.ai usage data from Mac browsers to VPS dashboard.

Flow: Mac polls claude.ai locally -> pushes usage data to VPS -> VPS stores it.
The VPS never contacts claude.ai directly.

Pure Python stdlib. Zero pip deps. Runs on macOS only.

Usage:
  python3 mac-sync.py

Setup:
  1. Download this file from your dashboard (SSH tunnel, then):
       curl http://localhost:8080/tools/mac-sync.py -o mac-sync.py
     The file is served WITHOUT the sync token pre-filled (by design — it
     used to be injected server-side, which leaked the token to any caller).
  2. Retrieve your sync token on the server:
       ssh user@YOUR_VPS_IP
       cd ~/claudash
       python3 cli.py claude-ai --sync-token
  3. Paste the token into SYNC_TOKEN below.
  4. Run: python3 mac-sync.py
"""

import json
import os
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import hashlib
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ── Configuration ──
# Set VPS_IP to your Claudash server's IP, or "localhost" if you're running
# via SSH tunnel (ssh -L 8080:localhost:8080 user@your-server).
VPS_IP = "localhost"
VPS_PORT = 8080
SYNC_TOKEN = ""

# Browser configs: (name, cookie_db_path_suffix, keychain_service, keychain_account)
BROWSERS = [
    ("Chrome", "Google/Chrome/Default/Cookies", "Chrome Safe Storage", "Chrome"),
    ("Vivaldi", "Vivaldi/Default/Cookies", "Vivaldi Safe Storage", "Vivaldi"),
]

CLAUDE_DOMAIN = ".claude.ai"
COOKIE_NAME = "sessionKey"


def main():
    if not SYNC_TOKEN:
        print("ERROR: SYNC_TOKEN is empty.", file=sys.stderr)
        print("", file=sys.stderr)
        print("To fix:", file=sys.stderr)
        print("  1. On your VPS, run: python3 cli.py claude-ai --sync-token", file=sys.stderr)
        print("  2. Paste the token into the SYNC_TOKEN variable at the top of this file", file=sys.stderr)
        print("  3. Or re-download from: http://{}:{}/tools/mac-sync.py".format(VPS_IP, VPS_PORT), file=sys.stderr)
        sys.exit(1)

    if sys.platform != "darwin":
        print("ERROR: mac-sync.py requires macOS (uses macOS Keychain for cookie decryption)", file=sys.stderr)
        print("For Claude Code users on any platform, use tools/oauth_sync.py instead", file=sys.stderr)
        sys.exit(1)

    app_support = os.path.expanduser("~/Library/Application Support")
    pushed = 0

    for browser_name, cookie_suffix, keychain_service, keychain_account in BROWSERS:
        cookie_db = os.path.join(app_support, cookie_suffix)
        if not os.path.exists(cookie_db):
            continue

        encrypted = _read_cookie(cookie_db, browser_name)
        if encrypted is None:
            print(f"{browser_name}: no sessionKey found for {CLAUDE_DOMAIN}")
            continue

        session_key = decrypt_cookie(encrypted, browser_name)
        if not session_key:
            print(f"{browser_name}: sessionKey found but decryption failed")
            continue

        # Verify session key and get account info
        account_info = _verify_with_claude(session_key)
        if not account_info:
            print(f"{browser_name}: sessionKey decrypted but could not verify with claude.ai")
            continue

        email = account_info.get("email", "unknown")
        org_id = account_info.get("org_id", "")
        plan = account_info.get("plan", "unknown")

        # Fetch usage data locally (Mac -> claude.ai)
        usage = _fetch_usage(session_key, org_id, plan)
        if usage:
            print(f"{browser_name}: {email} ({plan}) — {usage.get('pct_used', 0):.1f}% window used")
        else:
            print(f"{browser_name}: {email} ({plan}) — could not fetch usage (pushing session only)")

        # Push session key + usage data to VPS
        ok = _push_to_vps(session_key, org_id, browser_name, email, usage)
        if ok:
            print(f"{browser_name}: {email} ({plan}) -> pushed OK")
            pushed += 1
        else:
            print(f"{browser_name}: {email} ({plan}) -> push FAILED")

    if pushed == 0:
        print("\nNo session keys were pushed. Check that you're logged into claude.ai in Chrome or Vivaldi.")


def _read_cookie(cookie_db, browser_name):
    """Read the encrypted_value for sessionKey from a browser cookie DB."""
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(cookie_db, tmp)
        for ext in ("-wal", "-shm"):
            src = cookie_db + ext
            if os.path.exists(src):
                shutil.copy2(src, tmp + ext)
    except OSError as e:
        print(f"{browser_name}: cannot copy cookie DB: {e}", file=sys.stderr)
        return None

    try:
        conn = sqlite3.connect(tmp)
        row = conn.execute(
            "SELECT encrypted_value FROM cookies "
            "WHERE host_key = ? AND name = ? "
            "ORDER BY last_access_utc DESC LIMIT 1",
            (CLAUDE_DOMAIN, COOKIE_NAME),
        ).fetchone()
        conn.close()
    except Exception as e:
        print(f"{browser_name}: cannot read cookie DB: {e}", file=sys.stderr)
        return None
    finally:
        for f in (tmp, tmp + "-wal", tmp + "-shm"):
            try:
                os.unlink(f)
            except OSError:
                pass

    if not row or not row[0]:
        return None

    return row[0]


def decrypt_cookie(encrypted_value, browser):
    """Decrypt a Chrome/Vivaldi v10 encrypted cookie value."""
    if not encrypted_value:
        return None

    if encrypted_value[:3] == b"v10":
        encrypted_value = encrypted_value[3:]
    else:
        try:
            return encrypted_value.decode("utf-8")
        except Exception:
            return None

    browser_name = "Vivaldi" if "vivaldi" in browser.lower() else "Chrome"
    try:
        key_password = subprocess.check_output(
            ["security", "find-generic-password", "-w",
             "-s", f"{browser_name} Safe Storage", "-a", browser_name],
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        print(f"  {browser_name}: cannot read keychain password", file=sys.stderr)
        return None

    key = hashlib.pbkdf2_hmac("sha1", key_password, b"saltysalt", 1003, dklen=16)
    iv = b" " * 16

    try:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(encrypted_value)
            tmp = f.name
        result = subprocess.check_output(
            ["openssl", "enc", "-d", "-aes-128-cbc",
             "-K", key.hex(), "-iv", iv.hex(), "-in", tmp, "-nosalt"],
            stderr=subprocess.DEVNULL,
        )
        os.unlink(tmp)
        marker = b"sk-ant-"
        idx = result.find(marker)
        if idx == -1:
            return None
        end = result.find(b"\x00", idx)
        if end == -1:
            end = len(result)
        return result[idx:end].decode("utf-8").strip()
    except subprocess.CalledProcessError:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass

    return None


def _claude_headers(session_key):
    return {
        "Accept": "application/json",
        "Cookie": f"sessionKey={session_key}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }


def _parse_iso(ts_str):
    if not ts_str:
        return 0
    try:
        from datetime import datetime, timezone
        clean = ts_str.replace("Z", "").replace("+00:00", "")
        if "." in clean:
            clean = clean.split(".")[0]
        dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def _verify_with_claude(session_key):
    """Verify session key with claude.ai and extract account info."""
    try:
        req = Request("https://claude.ai/api/account")
        for k, v in _claude_headers(session_key).items():
            req.add_header(k, v)
        resp = urlopen(req, timeout=10)
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            email = data.get("email_address", "")
            org_id = ""
            memberships = data.get("memberships", [])
            if memberships:
                org_id = memberships[0].get("organization", {}).get("uuid", "")
            plan = "unknown"
            for m in memberships:
                org_obj = m.get("organization", {})
                caps = org_obj.get("capabilities", [])
                if isinstance(caps, list):
                    for c in caps:
                        if "max" in str(c).lower():
                            plan = "max"
                            break
                        if "pro" in str(c).lower():
                            plan = "pro"
                            break
                    if plan != "unknown":
                        break
            return {"email": email, "org_id": org_id, "plan": plan}
    except HTTPError:
        return None
    except Exception:
        return None
    return None


def _fetch_usage(session_key, org_id, plan):
    """Fetch usage from claude.ai locally on Mac.
    Actual API response format:
    {
      "five_hour": {"utilization": 61.0, "resets_at": "2026-04-10T15:00:00Z"},
      "seven_day": {"utilization": 49.0, "resets_at": "2026-04-14T12:00:00Z"},
      "extra_usage": {"monthly_limit": 5000, "used_credits": 133.0, "utilization": 2.66}
    }
    """
    if not org_id:
        return None

    url = f"https://claude.ai/api/organizations/{org_id}/usage"
    try:
        req = Request(url)
        for k, v in _claude_headers(session_key).items():
            req.add_header(k, v)
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"  Usage API returned HTTP {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Usage API error: {e}", file=sys.stderr)
        return None

    raw = json.dumps(data)

    five_hour = data.get("five_hour", {})
    seven_day = data.get("seven_day", {})
    extra = data.get("extra_usage", {})

    pct_used = five_hour.get("utilization", 0.0)
    resets_at = five_hour.get("resets_at", "")

    # Parse window times
    window_end = None
    if resets_at:
        from datetime import datetime, timezone
        try:
            window_end = int(datetime.fromisoformat(
                resets_at.replace("Z", "+00:00")
            ).timestamp())
        except Exception:
            window_end = _parse_iso(resets_at)
    window_start = window_end - 18000 if window_end else None  # 5hr = 18000s

    return {
        "pct_used": pct_used,
        "five_hour_utilization": pct_used,
        "seven_day_utilization": seven_day.get("utilization", 0.0),
        "extra_credits_used": extra.get("used_credits", 0.0),
        "extra_credits_limit": extra.get("monthly_limit", 0.0),
        "extra_utilization": extra.get("utilization", 0.0),
        "window_start": window_start,
        "window_end": window_end,
        "tokens_used": int(pct_used * 10000),  # normalized estimate
        "tokens_limit": 1000000,
        "messages_used": 0,
        "messages_limit": 0,
        "plan": plan,
        "raw": raw,
    }


def _push_to_vps(session_key, org_id, browser, account_hint, usage):
    """Push session key + usage data to VPS dashboard sync endpoint."""
    url = f"http://{VPS_IP}:{VPS_PORT}/api/claude-ai/sync"
    payload = {
        "session_key": session_key,
        "org_id": org_id,
        "browser": browser,
        "account_hint": account_hint,
    }
    if usage:
        payload["usage"] = usage

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Sync-Token": SYNC_TOKEN,
    }
    req = Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("success", False)
    except HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
            print(f"  Sync error: {err.get('error', e.code)}", file=sys.stderr)
        except Exception:
            print(f"  Sync error: HTTP {e.code}", file=sys.stderr)
        return False
    except (URLError, OSError) as e:
        print(f"  Cannot reach VPS at {VPS_IP}:{VPS_PORT}: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    main()


# ── How to get your sync token ──
#
# The dashboard no longer injects the token into this file at download time
# (that used to leak the token to anyone who hit /tools/mac-sync.py).
#
# To get your token:
#   ssh user@YOUR_VPS_IP
#   cd ~/claudash
#   python3 cli.py claude-ai --sync-token
#
# Then paste the value into SYNC_TOKEN at the top of this file.
