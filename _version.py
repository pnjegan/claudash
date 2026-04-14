"""Shared version constant — reads from package.json so there's one source of truth."""
import json
import os

_PKG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "package.json")

try:
    with open(_PKG_PATH) as _f:
        VERSION = json.load(_f).get("version", "0.0.0")
except (OSError, ValueError):
    VERSION = "0.0.0"
