import sqlite3
import json
import os
import stat
import time
import re

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "usage.db")


def _lock_db_file():
    """Enforce 0600 perms on the SQLite file and its WAL/SHM side files.
    The DB holds plaintext claude.ai session keys and the dashboard/sync
    auth tokens — it must not be world-readable."""
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            try:
                os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _lock_db_file()
    return conn


def _column_exists(conn, table, column):
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] > 0


def init_db():
    conn = get_conn()

    # Core tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            timestamp INTEGER,
            project TEXT,
            account TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_creation_tokens INTEGER,
            cost_usd REAL,
            UNIQUE(session_id, timestamp, model)
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_timestamp ON sessions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
        CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account);

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER,
            level TEXT,
            project TEXT,
            message TEXT,
            seen INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);

        CREATE TABLE IF NOT EXISTS claude_ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_label TEXT,
            timestamp INTEGER,
            tokens_used INTEGER,
            tokens_limit INTEGER,
            window_pct REAL,
            window_start INTEGER,
            window_end INTEGER,
            status TEXT DEFAULT 'ok',
            raw_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_claude_ai_ts ON claude_ai_usage(timestamp);
        CREATE INDEX IF NOT EXISTS idx_claude_ai_account ON claude_ai_usage(account_label);
    """)

    # --- Schema migration: add new columns to sessions ---
    for col, typedef in [
        ("source_path", "TEXT"),
        ("compaction_detected", "INTEGER DEFAULT 0"),
        ("tokens_before_compact", "INTEGER"),
        ("tokens_after_compact", "INTEGER"),
    ]:
        if not _column_exists(conn, "sessions", col):
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typedef}")

    # --- Additional index ---
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_model ON sessions(model)")

    # --- Scan state for incremental scanning ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scan_state (
            file_path TEXT PRIMARY KEY,
            last_offset INTEGER DEFAULT 0,
            last_scanned INTEGER,
            lines_processed INTEGER DEFAULT 0
        );
    """)

    # --- One-time migration of old account values (gated) ---
    migrated = conn.execute("SELECT value FROM settings WHERE key = 'account_migration_done'").fetchone() if _table_exists(conn, "settings") else None
    if not migrated:
        conn.execute("UPDATE sessions SET account = 'personal_max' WHERE account = 'personal'")
        conn.execute("UPDATE sessions SET account = 'work_pro' WHERE account = 'work'")

    # --- Existing analytics tables ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            account TEXT,
            project TEXT,
            total_tokens INTEGER,
            total_cost_usd REAL,
            cache_hit_rate REAL,
            session_count INTEGER,
            UNIQUE(date, account, project)
        );

        CREATE TABLE IF NOT EXISTS window_burns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT,
            window_start INTEGER,
            window_end INTEGER,
            tokens_used INTEGER,
            tokens_limit INTEGER,
            pct_used REAL,
            hit_limit INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_wb_account ON window_burns(account);
        CREATE INDEX IF NOT EXISTS idx_wb_start ON window_burns(window_start);

        CREATE TABLE IF NOT EXISTS insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER,
            account TEXT,
            project TEXT,
            insight_type TEXT,
            message TEXT,
            detail_json TEXT,
            dismissed INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_insights_created ON insights(created_at);
        CREATE INDEX IF NOT EXISTS idx_insights_account ON insights(account);
        CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(insight_type);
    """)

    # --- Account management tables ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT UNIQUE,
            label TEXT,
            plan TEXT,
            monthly_cost_usd REAL,
            window_token_limit INTEGER,
            color TEXT,
            data_paths TEXT,
            active INTEGER DEFAULT 1,
            created_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS account_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            project_name TEXT,
            keywords TEXT,
            UNIQUE(account_id, project_name)
        );
    """)

    # --- claude.ai browser tracking tables ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS claude_ai_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT UNIQUE,
            label TEXT,
            org_id TEXT,
            session_key TEXT,
            plan TEXT,
            status TEXT DEFAULT 'unconfigured',
            last_polled INTEGER,
            last_error TEXT,
            created_at INTEGER,
            updated_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS claude_ai_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            polled_at INTEGER,
            window_start INTEGER,
            window_end INTEGER,
            tokens_used INTEGER,
            tokens_limit INTEGER,
            messages_used INTEGER,
            messages_limit INTEGER,
            pct_used REAL,
            plan TEXT,
            raw_response TEXT,
            UNIQUE(account_id, polled_at)
        );
        CREATE INDEX IF NOT EXISTS idx_cas_account ON claude_ai_snapshots(account_id);
        CREATE INDEX IF NOT EXISTS idx_cas_polled ON claude_ai_snapshots(polled_at);
    """)

    # --- Migration: add mac_sync_mode column ---
    if not _column_exists(conn, "claude_ai_accounts", "mac_sync_mode"):
        conn.execute("ALTER TABLE claude_ai_accounts ADD COLUMN mac_sync_mode INTEGER DEFAULT 0")

    # --- Migration: add utilization columns to claude_ai_snapshots ---
    for col, typedef in [
        ("five_hour_utilization", "REAL DEFAULT 0"),
        ("seven_day_utilization", "REAL DEFAULT 0"),
        ("extra_credits_used", "REAL DEFAULT 0"),
        ("extra_credits_limit", "REAL DEFAULT 0"),
    ]:
        if not _column_exists(conn, "claude_ai_snapshots", col):
            conn.execute(f"ALTER TABLE claude_ai_snapshots ADD COLUMN {col} {typedef}")

    # --- Settings table ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Seed sync_token if missing
    row = conn.execute("SELECT value FROM settings WHERE key = 'sync_token'").fetchone()
    if not row:
        import secrets
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO settings (key, value) VALUES ('sync_token', ?)", (token,))

    # Seed dashboard_key if missing (required for all write endpoints)
    row = conn.execute("SELECT value FROM settings WHERE key = 'dashboard_key'").fetchone()
    if not row:
        import secrets
        key = secrets.token_hex(16)
        conn.execute("INSERT INTO settings (key, value) VALUES ('dashboard_key', ?)", (key,))

    # Mark one-time account migration as done
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('account_migration_done', '1')")

    # --- Seed from config.py if accounts table is empty ---
    count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    if count == 0:
        _seed_from_config(conn)

    # --- Seed claude_ai_accounts for each active account if not present ---
    active_accounts = conn.execute("SELECT account_id, label, plan FROM accounts WHERE active = 1").fetchall()
    for a in active_accounts:
        exists = conn.execute("SELECT id FROM claude_ai_accounts WHERE account_id = ?", (a["account_id"],)).fetchone()
        if not exists:
            conn.execute(
                """INSERT OR IGNORE INTO claude_ai_accounts
                   (account_id, label, org_id, session_key, plan, status, created_at, updated_at)
                   VALUES (?, ?, '', '', ?, 'unconfigured', ?, ?)""",
                (a["account_id"], a["label"], a["plan"], int(time.time()), int(time.time())),
            )

    conn.commit()
    conn.close()
    _lock_db_file()


def _seed_from_config(conn):
    """Migrate ACCOUNTS and PROJECT_MAP from config.py into DB tables."""
    from config import ACCOUNTS as CFG_ACCOUNTS, PROJECT_MAP as CFG_PROJECTS
    now = int(time.time())

    for acct_id, acct in CFG_ACCOUNTS.items():
        data_paths_json = json.dumps(acct.get("data_paths", []))
        conn.execute(
            """INSERT OR IGNORE INTO accounts
               (account_id, label, plan, monthly_cost_usd, window_token_limit, color, data_paths, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (acct_id, acct["label"], acct.get("plan", acct.get("type", "max")),
             acct.get("monthly_cost_usd", 0), acct.get("window_token_limit", 1_000_000),
             acct.get("color", "teal"), data_paths_json, now),
        )

    for proj_name, info in CFG_PROJECTS.items():
        keywords_json = json.dumps(info.get("keywords", []))
        conn.execute(
            "INSERT OR IGNORE INTO account_projects (account_id, project_name, keywords) VALUES (?, ?, ?)",
            (info["account"], proj_name, keywords_json),
        )


def sync_project_map_from_config(conn):
    """UPSERT config.PROJECT_MAP into account_projects so keyword edits in
    config.py actually take effect on next scan/reprocess. Adds new projects
    and updates keyword lists on existing ones."""
    from config import PROJECT_MAP as CFG_PROJECTS
    for proj_name, info in CFG_PROJECTS.items():
        keywords_json = json.dumps(info.get("keywords", []))
        conn.execute(
            "INSERT INTO account_projects (account_id, project_name, keywords) VALUES (?, ?, ?) "
            "ON CONFLICT(account_id, project_name) DO UPDATE SET keywords=excluded.keywords",
            (info["account"], proj_name, keywords_json),
        )
    conn.commit()


# ── Account config from DB (source of truth) ──

def get_accounts_config(conn=None):
    """Return accounts dict in same shape as config.ACCOUNTS, from DB.
    Falls back to config.py if DB has no active accounts."""
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True

    rows = conn.execute("SELECT * FROM accounts WHERE active = 1").fetchall()
    if should_close:
        conn.close()

    if not rows:
        from config import ACCOUNTS
        return dict(ACCOUNTS)

    result = {}
    for r in rows:
        paths = []
        try:
            paths = json.loads(r["data_paths"]) if r["data_paths"] else []
        except (json.JSONDecodeError, TypeError):
            pass
        # Expand ~ in paths
        paths = [os.path.expanduser(p) for p in paths]

        result[r["account_id"]] = {
            "label": r["label"],
            "type": r["plan"],
            "plan": r["plan"],
            "monthly_cost_usd": r["monthly_cost_usd"] or 0,
            "window_token_limit": r["window_token_limit"] or 1_000_000,
            "color": r["color"] or "teal",
            "data_paths": paths,
        }
    return result


def get_project_map_config(conn=None):
    """Return project map dict in same shape as config.PROJECT_MAP, from DB."""
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True

    rows = conn.execute("SELECT * FROM account_projects").fetchall()
    if should_close:
        conn.close()

    if not rows:
        from config import PROJECT_MAP
        return dict(PROJECT_MAP)

    result = {}
    for r in rows:
        keywords = []
        try:
            keywords = json.loads(r["keywords"]) if r["keywords"] else []
        except (json.JSONDecodeError, TypeError):
            pass
        result[r["project_name"]] = {
            "keywords": keywords,
            "account": r["account_id"],
        }
    return result


# ── Account CRUD ──

def validate_account_id(account_id):
    """Validate account_id slug: lowercase, underscores only, max 32 chars."""
    if not account_id:
        return False, "account_id is required"
    if len(account_id) > 32:
        return False, "account_id must be <= 32 characters"
    if not re.match(r'^[a-z][a-z0-9_]*$', account_id):
        return False, "account_id must be lowercase letters, numbers, underscores; start with letter"
    return True, ""


def create_account(conn, data):
    """Create a new account. Returns (success, error_msg)."""
    account_id = data.get("account_id", "")
    valid, err = validate_account_id(account_id)
    if not valid:
        return False, err

    # Check uniqueness
    existing = conn.execute("SELECT id FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    if existing:
        return False, f"account_id '{account_id}' already exists"

    data_paths = data.get("data_paths", [])
    if not data_paths:
        return False, "at least one data_path is required"

    label = data.get("label", "")
    if not label:
        return False, "label is required"

    conn.execute(
        """INSERT INTO accounts
           (account_id, label, plan, monthly_cost_usd, window_token_limit, color, data_paths, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (account_id, label, data.get("plan", "max"),
         data.get("monthly_cost_usd", 0), data.get("window_token_limit", 1_000_000),
         data.get("color", "teal"), json.dumps(data_paths), int(time.time())),
    )
    conn.commit()
    return True, ""


def update_account(conn, account_id, data):
    """Update an existing account. Returns (success, error_msg)."""
    existing = conn.execute("SELECT id FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    if not existing:
        return False, f"account '{account_id}' not found"

    updates = []
    params = []
    for field in ("label", "plan", "monthly_cost_usd", "window_token_limit", "color"):
        if field in data:
            updates.append(f"{field} = ?")
            params.append(data[field])
    if "data_paths" in data:
        updates.append("data_paths = ?")
        params.append(json.dumps(data["data_paths"]))

    if not updates:
        return True, ""

    params.append(account_id)
    conn.execute(f"UPDATE accounts SET {', '.join(updates)} WHERE account_id = ?", params)
    conn.commit()
    return True, ""


def delete_account(conn, account_id):
    """Soft delete (active=0). Returns (success, error_msg)."""
    existing = conn.execute("SELECT id FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    if not existing:
        return False, f"account '{account_id}' not found"
    conn.execute("UPDATE accounts SET active = 0 WHERE account_id = ?", (account_id,))
    conn.commit()
    return True, ""


def get_all_accounts(conn):
    """Get all active accounts with their projects."""
    accounts = conn.execute("SELECT * FROM accounts WHERE active = 1 ORDER BY created_at").fetchall()
    result = []
    for a in accounts:
        paths = []
        try:
            paths = json.loads(a["data_paths"]) if a["data_paths"] else []
        except (json.JSONDecodeError, TypeError):
            pass

        projects = conn.execute(
            "SELECT * FROM account_projects WHERE account_id = ?", (a["account_id"],)
        ).fetchall()
        proj_list = []
        for p in projects:
            kw = []
            try:
                kw = json.loads(p["keywords"]) if p["keywords"] else []
            except (json.JSONDecodeError, TypeError):
                pass
            proj_list.append({"project_name": p["project_name"], "keywords": kw})

        result.append({
            "account_id": a["account_id"],
            "label": a["label"],
            "plan": a["plan"],
            "monthly_cost_usd": a["monthly_cost_usd"],
            "window_token_limit": a["window_token_limit"],
            "color": a["color"],
            "data_paths": paths,
            "active": a["active"],
            "created_at": a["created_at"],
            "projects": proj_list,
        })
    return result


def get_account_projects(conn, account_id):
    """Get projects for a specific account."""
    rows = conn.execute(
        "SELECT * FROM account_projects WHERE account_id = ?", (account_id,)
    ).fetchall()
    result = []
    for r in rows:
        kw = []
        try:
            kw = json.loads(r["keywords"]) if r["keywords"] else []
        except (json.JSONDecodeError, TypeError):
            pass
        result.append({"project_name": r["project_name"], "keywords": kw})
    return result


def add_account_project(conn, account_id, project_name, keywords):
    """Add a project to an account. Returns (success, error_msg)."""
    if not project_name:
        return False, "project_name is required"
    try:
        conn.execute(
            "INSERT INTO account_projects (account_id, project_name, keywords) VALUES (?, ?, ?)",
            (account_id, project_name, json.dumps(keywords)),
        )
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, f"project '{project_name}' already exists for account '{account_id}'"


def remove_account_project(conn, account_id, project_name):
    """Remove a project from an account. Returns (success, error_msg)."""
    cursor = conn.execute(
        "DELETE FROM account_projects WHERE account_id = ? AND project_name = ?",
        (account_id, project_name),
    )
    conn.commit()
    if cursor.rowcount == 0:
        return False, f"project '{project_name}' not found for account '{account_id}'"
    return True, ""


# ── Session CRUD (unchanged) ──

def insert_session(conn, row):
    try:
        conn.execute(
            """INSERT OR IGNORE INTO sessions
               (session_id, timestamp, project, account, model,
                input_tokens, output_tokens, cache_read_tokens,
                cache_creation_tokens, cost_usd, source_path,
                compaction_detected, tokens_before_compact, tokens_after_compact)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["session_id"], row["timestamp"], row["project"],
                row["account"], row["model"], row["input_tokens"],
                row["output_tokens"], row["cache_read_tokens"],
                row["cache_creation_tokens"], row["cost_usd"],
                row.get("source_path", ""),
                row.get("compaction_detected", 0),
                row.get("tokens_before_compact"),
                row.get("tokens_after_compact"),
            ),
        )
        return conn.total_changes > 0
    except sqlite3.Error:
        return False


def insert_alert(conn, level, project, message):
    conn.execute(
        "INSERT INTO alerts (created_at, level, project, message) VALUES (?, ?, ?, ?)",
        (int(time.time()), level, project, message),
    )


def query_sessions(conn, account=None, since=None):
    sql = "SELECT * FROM sessions WHERE 1=1"
    params = []
    if account and account != "all":
        sql += " AND account = ?"
        params.append(account)
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    sql += " ORDER BY timestamp DESC"
    return conn.execute(sql, params).fetchall()


def query_alerts(conn, limit=20):
    return conn.execute(
        "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def clear_alerts(conn):
    conn.execute("DELETE FROM alerts")
    conn.commit()


def get_session_count(conn):
    return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def insert_claude_ai_usage(conn, row):
    conn.execute(
        """INSERT INTO claude_ai_usage
           (account_label, timestamp, tokens_used, tokens_limit,
            window_pct, window_start, window_end, status, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["account_label"], row["timestamp"], row["tokens_used"],
            row["tokens_limit"], row["window_pct"], row["window_start"],
            row["window_end"], row["status"], row.get("raw_json", ""),
        ),
    )


def get_latest_claude_ai_usage(conn):
    return conn.execute("""
        SELECT c1.* FROM claude_ai_usage c1
        INNER JOIN (
            SELECT account_label, MAX(timestamp) as max_ts
            FROM claude_ai_usage GROUP BY account_label
        ) c2 ON c1.account_label = c2.account_label AND c1.timestamp = c2.max_ts
        ORDER BY c1.account_label
    """).fetchall()


def get_claude_ai_history(conn, account_label=None, hours=24):
    since = int(time.time()) - (hours * 3600)
    if account_label:
        return conn.execute(
            "SELECT * FROM claude_ai_usage WHERE account_label = ? AND timestamp >= ? ORDER BY timestamp",
            (account_label, since),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM claude_ai_usage WHERE timestamp >= ? ORDER BY timestamp",
        (since,),
    ).fetchall()


# --- Daily snapshots ---

def upsert_daily_snapshot(conn, date_str, account, project, total_tokens, total_cost, cache_hit_rate, session_count):
    conn.execute(
        """INSERT INTO daily_snapshots (date, account, project, total_tokens, total_cost_usd, cache_hit_rate, session_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date, account, project) DO UPDATE SET
             total_tokens=excluded.total_tokens,
             total_cost_usd=excluded.total_cost_usd,
             cache_hit_rate=excluded.cache_hit_rate,
             session_count=excluded.session_count""",
        (date_str, account, project, total_tokens, total_cost, cache_hit_rate, session_count),
    )


def get_daily_snapshots(conn, account=None, days=7):
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = "SELECT * FROM daily_snapshots WHERE date >= ?"
    params = [since]
    if account and account != "all":
        sql += " AND account = ?"
        params.append(account)
    sql += " ORDER BY date"
    return conn.execute(sql, params).fetchall()


# --- Window burns ---

def insert_window_burn(conn, account, window_start, window_end, tokens_used, tokens_limit, pct_used, hit_limit):
    conn.execute(
        """INSERT INTO window_burns (account, window_start, window_end, tokens_used, tokens_limit, pct_used, hit_limit)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (account, window_start, window_end, tokens_used, tokens_limit, pct_used, hit_limit),
    )


def get_window_burns(conn, account=None, limit=7):
    sql = "SELECT * FROM window_burns"
    params = []
    if account and account != "all":
        sql += " WHERE account = ?"
        params.append(account)
    sql += " ORDER BY window_start DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


# --- Insights ---

def insert_insight(conn, account, project, insight_type, message, detail_json="{}"):
    conn.execute(
        """INSERT INTO insights (created_at, account, project, insight_type, message, detail_json, dismissed)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        (int(time.time()), account, project, insight_type, message, detail_json),
    )


def get_insights(conn, account=None, dismissed=0, limit=50):
    sql = "SELECT * FROM insights WHERE dismissed = ?"
    params = [dismissed]
    if account and account != "all":
        sql += " AND account = ?"
        params.append(account)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def dismiss_insight(conn, insight_id):
    conn.execute("UPDATE insights SET dismissed = 1 WHERE id = ?", (insight_id,))
    conn.commit()


def get_db_size_mb():
    try:
        return round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
    except OSError:
        return 0


# ── claude.ai browser tracking ──

def get_claude_ai_accounts_all(conn):
    """Get all claude_ai_accounts rows."""
    return [dict(r) for r in conn.execute("SELECT * FROM claude_ai_accounts").fetchall()]


def get_claude_ai_account(conn, account_id):
    row = conn.execute("SELECT * FROM claude_ai_accounts WHERE account_id = ?", (account_id,)).fetchone()
    return dict(row) if row else None


def upsert_claude_ai_account(conn, account_id, label, org_id, session_key, plan, status):
    now = int(time.time())
    existing = conn.execute("SELECT id FROM claude_ai_accounts WHERE account_id = ?", (account_id,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE claude_ai_accounts
               SET label=?, org_id=?, session_key=?, plan=?, status=?, updated_at=?
               WHERE account_id=?""",
            (label, org_id, session_key, plan, status, now, account_id),
        )
    else:
        conn.execute(
            """INSERT INTO claude_ai_accounts
               (account_id, label, org_id, session_key, plan, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, label, org_id, session_key, plan, status, now, now),
        )
    conn.commit()


def update_claude_ai_account_status(conn, account_id, status, last_error=None):
    now = int(time.time())
    conn.execute(
        "UPDATE claude_ai_accounts SET status=?, last_polled=?, last_error=?, updated_at=? WHERE account_id=?",
        (status, now, last_error, now, account_id),
    )
    conn.commit()


def clear_claude_ai_session(conn, account_id):
    now = int(time.time())
    conn.execute(
        "UPDATE claude_ai_accounts SET session_key='', org_id='', status='unconfigured', updated_at=? WHERE account_id=?",
        (now, account_id),
    )
    conn.commit()


def insert_claude_ai_snapshot(conn, account_id, data):
    """Insert a snapshot, auto-purge old ones (keep last 200 per account)."""
    now = int(time.time())
    conn.execute(
        """INSERT OR REPLACE INTO claude_ai_snapshots
           (account_id, polled_at, window_start, window_end,
            tokens_used, tokens_limit, messages_used, messages_limit,
            pct_used, plan, raw_response,
            five_hour_utilization, seven_day_utilization,
            extra_credits_used, extra_credits_limit)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (account_id, now,
         data.get("window_start") or 0, data.get("window_end") or 0,
         data.get("tokens_used", 0), data.get("tokens_limit", 0),
         data.get("messages_used", 0), data.get("messages_limit", 0),
         data.get("pct_used", 0), data.get("plan", ""),
         data.get("raw", ""),
         data.get("five_hour_utilization", 0),
         data.get("seven_day_utilization", 0),
         data.get("extra_credits_used", 0),
         data.get("extra_credits_limit", 0)),
    )
    # Auto-purge: keep last 200 per account
    conn.execute(
        """DELETE FROM claude_ai_snapshots WHERE account_id = ? AND id NOT IN (
             SELECT id FROM claude_ai_snapshots WHERE account_id = ?
             ORDER BY polled_at DESC LIMIT 200
           )""",
        (account_id, account_id),
    )
    conn.commit()


def get_latest_claude_ai_snapshot(conn, account_id):
    row = conn.execute(
        "SELECT * FROM claude_ai_snapshots WHERE account_id = ? ORDER BY polled_at DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


def get_claude_ai_snapshot_history(conn, account_id, limit=48):
    rows = conn.execute(
        "SELECT * FROM claude_ai_snapshots WHERE account_id = ? ORDER BY polled_at DESC LIMIT ?",
        (account_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── Settings ──

def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
