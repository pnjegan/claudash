#!/usr/bin/env python3
"""
Claudash sync daemon — runs in background,
pushes claude.ai browser data every 5 minutes.
Works on macOS (uses mac-sync.py) or any OS (uses oauth_sync.py).
"""
import time
import os
import sys
import subprocess
import platform

INTERVAL = 300  # 5 minutes
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_sync_script():
    if platform.system() == "Darwin":
        mac_sync = os.path.join(SCRIPT_DIR, "mac-sync.py")
        if os.path.exists(mac_sync):
            return mac_sync
    return os.path.join(SCRIPT_DIR, "oauth_sync.py")


def run_sync():
    script = get_sync_script()
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"[sync] OK: {result.stdout.strip()[:200]}")
        else:
            print(f"[sync] Error: {result.stderr.strip()[:200]}")
    except subprocess.TimeoutExpired:
        print("[sync] Timeout after 30s")
    except Exception as e:
        print(f"[sync] Failed: {e}")


if __name__ == "__main__":
    print(f"Claudash sync daemon starting (every {INTERVAL//60} min)")
    print(f"Using: {get_sync_script()}")
    print("Press Ctrl+C to stop")
    print()

    run_sync()  # run immediately on start
    try:
        while True:
            time.sleep(INTERVAL)
            run_sync()
    except KeyboardInterrupt:
        print("\nSync daemon stopped.")
