#!/usr/bin/env python3
"""Claudash — derived-key helper.

If you can't (or don't want to) call `security find-generic-password`
from cron on macOS, this script extracts the per-browser AES keys once
using your current interactive login and prints them in a format you
can paste into an environment-variable block for mac-sync.py.

Intended usage:

    1. Run this script once in your Mac terminal while logged in:
         python3 tools/get-derived-keys.py
       It will prompt for the Chrome/Vivaldi "Safe Storage" passwords
       from the macOS keychain (you may have to click "Always Allow"
       a couple of times), derive the PBKDF2 keys, and print:

         export CLAUDASH_CHROME_KEY=0123abcd...
         export CLAUDASH_VIVALDI_KEY=cafebabe...

    2. Add those exports to your ~/.zshenv (or the environment block
       of your cron entry).

    3. Update mac-sync.py to read the key from the env var instead of
       calling `security find-generic-password` on every run — that
       way cron can run unattended without triggering the keychain
       "allow/deny" prompt.

Runs on macOS only. Pure Python stdlib.
"""

import hashlib
import subprocess
import sys


BROWSERS = [
    ("Chrome", "Chrome Safe Storage", "Chrome"),
    ("Vivaldi", "Vivaldi Safe Storage", "Vivaldi"),
    ("Edge", "Microsoft Edge Safe Storage", "Microsoft Edge"),
    ("Brave", "Brave Safe Storage", "Brave"),
]

PBKDF2_ITERATIONS = 1003
PBKDF2_SALT = b"saltysalt"
PBKDF2_KEY_LEN = 16


def _fetch_safe_storage_password(service, account):
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-w",
             "-s", service, "-a", account],
            stderr=subprocess.DEVNULL,
        ).strip()
        return raw
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _derive_key(password):
    if not password:
        return None
    return hashlib.pbkdf2_hmac(
        "sha1", password, PBKDF2_SALT, PBKDF2_ITERATIONS, dklen=PBKDF2_KEY_LEN,
    )


def main():
    if sys.platform != "darwin":
        print("ERROR: this helper only runs on macOS.", file=sys.stderr)
        print("On Linux/Windows, Chromium cookies use a different scheme.", file=sys.stderr)
        sys.exit(1)

    print("Claudash — derived browser key extractor")
    print("=" * 50)
    print()
    print("Keychain will prompt for each browser the first time —")
    print("click 'Always Allow' so future runs are silent.")
    print()

    exports = []
    for display, service, account in BROWSERS:
        pw = _fetch_safe_storage_password(service, account)
        if pw is None:
            print(f"  {display}: not installed or no keychain entry — skipped")
            continue
        key = _derive_key(pw)
        if key is None:
            print(f"  {display}: empty password — skipped")
            continue
        env_name = f"CLAUDASH_{display.upper()}_KEY"
        exports.append((env_name, key.hex()))
        print(f"  {display}: key derived ({len(key)*8}-bit)")

    if not exports:
        print()
        print("No browser keys could be extracted. Are Chrome / Vivaldi / Edge / Brave installed?")
        sys.exit(2)

    print()
    print("Add these to your shell profile (~/.zshenv or ~/.bash_profile):")
    print()
    print("# Claudash — pre-derived browser cookie keys (safe to commit to private dotfiles)")
    for name, hex_key in exports:
        print(f"export {name}={hex_key}")
    print()
    print("Then update mac-sync.py to read os.environ.get(name) instead of")
    print("calling `security find-generic-password` every run.")


if __name__ == "__main__":
    main()
