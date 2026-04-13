"""Claudash configuration.

Edit this file on first run, or use the browser UI at /accounts to manage
accounts after the DB is seeded. Config.py only seeds the database once — the
live source of truth after that is the `accounts` table in data/usage.db.
"""
import os

# ─── Host settings ───────────────────────────────────────────────
# If you run Claudash on a VPS and reach it via SSH tunnel, set
# CLAUDASH_VPS_IP in your environment so banners and help text show
# the correct host. Defaults to "localhost" for a same-machine install.
VPS_IP = os.environ.get("CLAUDASH_VPS_IP", "localhost")
VPS_PORT = int(os.environ.get("CLAUDASH_VPS_PORT", "8080"))

# ─── Account Setup ───────────────────────────────────────────────
# Add your Claude accounts here. These are the seed values — once the
# DB is populated, edit accounts via the /accounts page in the browser.
#
#   account_id: short slug (lowercase letters, digits, underscores)
#   label:      display name shown in dashboard
#   plan:       "max" | "pro" | "api"
#   monthly_cost_usd: your subscription cost (for ROI math)
#   window_token_limit: 1_000_000 for Max, 200_000 for Pro, 0 for API
#   data_paths: folders where Claude Code writes JSONL session logs
#               default is ["~/.claude/projects/"]; add more if you
#               run multiple Claude Code installs or rsync in JSONL
#               from other machines.
#   color:      teal | purple | blue | coral | amber (UI accent)

ACCOUNTS = {
    "personal_max": {
        "label": "Personal (Max)",
        "type": "max",
        "plan": "max",
        "monthly_cost_usd": 100,
        "window_token_limit": 1_000_000,
        "data_paths": [
            os.path.expanduser("~/.claude/projects/"),
        ],
        "color": "teal",
    },
}

# ─── Project Map ─────────────────────────────────────────────────
# Maps folder-name keywords → project labels. Claudash walks the JSONL
# folder paths under each account's data_paths and looks for any of
# these substrings (case-insensitive) in the path.
#
# Empty on a fresh install — add your own. Example:
#
#   PROJECT_MAP = {
#       "MyProject":  {"keywords": ["myproject", "-root-myproject"],
#                      "account": "personal_max"},
#       "ClientWork": {"keywords": ["acme", "client-a"],
#                      "account": "personal_max"},
#   }
#
# The DB is the live source of truth after first run. Edits here only
# take effect on `cli.py scan --reprocess` (which UPSERTs into the
# account_projects table).

PROJECT_MAP = {}

UNKNOWN_PROJECT = "Other"

# ─── Daily budget per account (USD, API-equivalent) ──────────────
# Set per account_id. Claudash compares today's cost to this value
# and fires BUDGET_WARNING / BUDGET_EXCEEDED insights.
# Set to 0 (or omit an account) to disable budget tracking.
#
# Example:
#   DAILY_BUDGET_USD = {
#       "personal_max": 20.0,
#       "work_pro":      5.0,
#   }

DAILY_BUDGET_USD = {}

# Per million tokens, USD
MODEL_PRICING = {
    "claude-opus":   {"input": 15.0,  "output": 75.0,  "cache_read": 1.5,  "cache_write": 18.75},
    "claude-sonnet": {"input": 3.0,   "output": 15.0,  "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku":  {"input": 0.25,  "output": 1.25,  "cache_read": 0.025, "cache_write": 0.30},
}

# Window settings per plan
MAX_WINDOW_HOURS = 5

# claude.ai web chat accounts — add yours here if using mac-sync.py browser tracking.
# Example:
#   CLAUDE_AI_ACCOUNTS = [
#       {"label": "Personal Max", "session_key": "", "org_id": ""},
#   ]
CLAUDE_AI_ACCOUNTS = []

# Cost targets per project (for insights).
# Example:
#   COST_TARGETS = {"MyProject": 0.10}
COST_TARGETS = {}
