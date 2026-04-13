import time
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from config import MODEL_PRICING, MAX_WINDOW_HOURS, COST_TARGETS
from db import (
    get_conn, insert_alert, clear_alerts, query_alerts,
    upsert_daily_snapshot, get_daily_snapshots, insert_window_burn, get_window_burns,
    get_accounts_config, get_project_map_config,
)


def _now():
    return int(time.time())


def _days_ago(n):
    return _now() - (n * 86400)


def _today_midnight():
    dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(dt.timestamp())


def _fetch_rows(conn, account=None, since=None):
    sql = "SELECT * FROM sessions WHERE 1=1"
    params = []
    if account and account != "all":
        sql += " AND account = ?"
        params.append(account)
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    return conn.execute(sql, params).fetchall()


# ── Per-account metrics ──

def account_metrics(conn, account="all"):
    ACCOUNTS = get_accounts_config(conn)
    rows_30d = _fetch_rows(conn, account, _days_ago(30))
    rows_7d = _fetch_rows(conn, account, _days_ago(7))
    rows_today = _fetch_rows(conn, account, _today_midnight())

    total_cost_30d = sum(r["cost_usd"] for r in rows_30d)
    sessions_today = len(set(r["session_id"] for r in rows_today))

    session_tokens_7d = {}
    for r in rows_7d:
        sid = r["session_id"]
        session_tokens_7d[sid] = session_tokens_7d.get(sid, 0) + r["input_tokens"] + r["output_tokens"]
    avg_tokens_per_session = (
        sum(session_tokens_7d.values()) / len(session_tokens_7d) if session_tokens_7d else 0
    )

    # Honest cache hit rate: reads / (reads + writes). A "miss" is a cache
    # creation (write). Counting fresh input_tokens in the denominator biased
    # the old formula toward ~100% because Claude Code's input_tokens is near
    # zero once caching is active.
    total_cache_read = sum(r["cache_read_tokens"] for r in rows_30d)
    total_cache_create = sum(r["cache_creation_tokens"] for r in rows_30d)
    total_cache_activity = total_cache_read + total_cache_create
    cache_hit_rate = (total_cache_read / total_cache_activity * 100) if total_cache_activity > 0 else 0

    cache_roi_usd = 0.0
    for r in rows_30d:
        pricing = MODEL_PRICING.get(r["model"], MODEL_PRICING["claude-sonnet"])
        saved = r["cache_read_tokens"] * (pricing["input"] - pricing["cache_read"]) / 1_000_000
        cache_roi_usd += saved

    subscription_roi = 0.0
    if account and account != "all":
        acct_info = ACCOUNTS.get(account, {})
        monthly_cost = acct_info.get("monthly_cost_usd", 0)
        if monthly_cost > 0:
            subscription_roi = round(total_cost_30d / monthly_cost, 2)
    else:
        total_plan = sum(a.get("monthly_cost_usd", 0) for a in ACCOUNTS.values())
        if total_plan > 0:
            subscription_roi = round(total_cost_30d / total_plan, 2)

    session_turns = defaultdict(int)
    for r in rows_7d:
        session_turns[r["session_id"]] += 1
    avg_session_depth = (
        sum(session_turns.values()) / len(session_turns) if session_turns else 0
    )

    sessions_with_compact = set()
    sessions_all = set()
    for r in rows_30d:
        sessions_all.add(r["session_id"])
        if r["compaction_detected"]:
            sessions_with_compact.add(r["session_id"])
    compaction_rate = (len(sessions_with_compact) / len(sessions_all) * 100) if sessions_all else 0

    hour_tokens = defaultdict(int)
    for r in rows_7d:
        h = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).hour
        hour_tokens[h] += r["input_tokens"] + r["output_tokens"]
    peak_burn_hour = max(hour_tokens, key=hour_tokens.get) if hour_tokens else None

    day_sessions = defaultdict(int)
    for r in rows_30d:
        dow = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).strftime("%A")
        day_sessions[dow] += 1
    heaviest_day = max(day_sessions, key=day_sessions.get) if day_sessions else None

    return {
        "total_cost_30d": round(total_cost_30d, 2),
        "sessions_today": sessions_today,
        "avg_tokens_per_session": int(avg_tokens_per_session),
        "cache_hit_rate": round(cache_hit_rate, 1),
        "cache_roi_usd": round(cache_roi_usd, 2),
        "subscription_roi": subscription_roi,
        "avg_session_depth": round(avg_session_depth, 1),
        "compaction_rate": round(compaction_rate, 1),
        "peak_burn_hour": peak_burn_hour,
        "heaviest_day": heaviest_day,
    }


# ── Window metrics (per account) ──

def window_metrics(conn, account="personal_max"):
    ACCOUNTS = get_accounts_config(conn)
    acct_info = ACCOUNTS.get(account, {})
    if not acct_info:
        acct_info = next(iter(ACCOUNTS.values()), {})
    window_limit = acct_info.get("window_token_limit", 1_000_000)
    now = _now()
    window_seconds = MAX_WINDOW_HOURS * 3600

    acct_filter = account if account and account != "all" else None
    if acct_filter:
        row = conn.execute(
            "SELECT MAX(timestamp) as last_ts FROM sessions WHERE account = ?", (acct_filter,)
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(timestamp) as last_ts FROM sessions").fetchone()

    last_ts = row["last_ts"] if row and row["last_ts"] else now

    window_start = last_ts - (last_ts % window_seconds)
    if window_start + window_seconds < now:
        window_start = now - (now % window_seconds)
    window_end = window_start + window_seconds

    if acct_filter:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE account = ? AND timestamp >= ? AND timestamp < ?",
            (acct_filter, window_start, window_end),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE timestamp >= ? AND timestamp < ?",
            (window_start, window_end),
        ).fetchall()

    total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in rows)
    window_pct = (total_tokens / window_limit * 100) if window_limit > 0 else 0

    elapsed_seconds = max(now - window_start, 1)
    if total_tokens > 0:
        burn_per_second = total_tokens / elapsed_seconds
        remaining_tokens = window_limit - total_tokens
        if burn_per_second > 0 and remaining_tokens > 0:
            seconds_to_limit = remaining_tokens / burn_per_second
            predicted_limit_time = now + seconds_to_limit
            minutes_to_limit = int(seconds_to_limit / 60)
        else:
            predicted_limit_time = None
            minutes_to_limit = None
    else:
        burn_per_second = 0
        predicted_limit_time = None
        minutes_to_limit = None

    window_history = [dict(r) for r in get_window_burns(conn, account, 7)]

    return {
        "account": account,
        "window_start": window_start,
        "window_end": window_end,
        "total_tokens": total_tokens,
        "tokens_limit": window_limit,
        "window_pct": round(window_pct, 1),
        "burn_per_minute": round(burn_per_second * 60, 0),
        "minutes_to_limit": minutes_to_limit,
        "predicted_limit_time": predicted_limit_time,
        "window_history": window_history,
    }


# ── Per-project metrics ──

def project_metrics(conn, account="all"):
    ACCOUNTS = get_accounts_config(conn)
    rows_30d = _fetch_rows(conn, account, _days_ago(30))
    rows_7d = _fetch_rows(conn, account, _days_ago(7))
    rows_prev_7d = _fetch_rows(conn, account, _days_ago(14))
    if not rows_30d:
        return []

    total_tokens_all = sum(r["input_tokens"] + r["output_tokens"] for r in rows_30d)

    projects = {}
    for r in rows_30d:
        p = r["project"]
        if p not in projects:
            projects[p] = {
                "name": p, "account": r["account"], "tokens": 0, "cost": 0.0,
                "cache_read": 0, "cache_create": 0, "input_tokens": 0, "models": {}, "sessions": set(),
                "output_tokens_list": [], "timestamps": [],
            }
        d = projects[p]
        d["tokens"] += r["input_tokens"] + r["output_tokens"]
        d["cost"] += r["cost_usd"]
        d["cache_read"] += r["cache_read_tokens"]
        d["cache_create"] += r["cache_creation_tokens"]
        d["input_tokens"] += r["input_tokens"]
        d["models"][r["model"]] = d["models"].get(r["model"], 0) + 1
        d["sessions"].add(r["session_id"])
        d["output_tokens_list"].append(r["output_tokens"])
        d["timestamps"].append(r["timestamp"])

    this_week_cost = defaultdict(float)
    for r in rows_7d:
        this_week_cost[r["project"]] += r["cost_usd"]

    last_week_cost = defaultdict(float)
    for r in rows_prev_7d:
        if r["timestamp"] < _days_ago(7):
            last_week_cost[r["project"]] += r["cost_usd"]

    result = []
    for p, d in sorted(projects.items(), key=lambda x: -x[1]["cost"]):
        cache_activity = d["cache_read"] + d["cache_create"]
        cache_hit = (d["cache_read"] / cache_activity * 100) if cache_activity > 0 else 0
        dominant_model = max(d["models"], key=d["models"].get) if d["models"] else "claude-sonnet"
        session_count = len(d["sessions"])
        avg_cost = d["cost"] / session_count if session_count > 0 else 0
        token_share = (d["tokens"] / total_tokens_all * 100) if total_tokens_all > 0 else 0

        total_model_rows = sum(d["models"].values())
        model_consistency = (d["models"].get(dominant_model, 0) / total_model_rows * 100) if total_model_rows > 0 else 100

        if d["timestamps"] and len(d["timestamps"]) > 1:
            ts_sorted = sorted(d["timestamps"])
            span_hours = max((ts_sorted[-1] - ts_sorted[0]) / 3600, 1)
            token_velocity = d["tokens"] / span_hours
        else:
            token_velocity = 0

        cache_roi = 0.0
        for r in rows_30d:
            if r["project"] == p:
                pricing = MODEL_PRICING.get(r["model"], MODEL_PRICING["claude-sonnet"])
                cache_roi += r["cache_read_tokens"] * (pricing["input"] - pricing["cache_read"]) / 1_000_000

        tw = this_week_cost.get(p, 0)
        lw = last_week_cost.get(p, 0)
        wow_change = ((tw - lw) / lw * 100) if lw > 0 else 0

        avg_output = sum(d["output_tokens_list"]) / len(d["output_tokens_list"]) if d["output_tokens_list"] else 0
        rightsizing_savings = 0.0
        if dominant_model == "claude-opus" and avg_output < 800:
            opus_cost = d["cost"]
            sonnet_ratio = MODEL_PRICING["claude-sonnet"]["output"] / MODEL_PRICING["claude-opus"]["output"]
            rightsizing_savings = round(opus_cost * (1 - sonnet_ratio), 2)

        result.append({
            "name": p,
            "account": d["account"],
            "account_label": ACCOUNTS.get(d["account"], {}).get("label", d["account"]),
            "token_share_pct": round(token_share, 1),
            "cost_usd_30d": round(d["cost"], 2),
            "dominant_model": dominant_model,
            "cache_hit_rate": round(cache_hit, 1),
            "avg_cost_per_session": round(avg_cost, 4),
            "total_tokens": d["tokens"],
            "session_count": session_count,
            "model_consistency": round(model_consistency, 1),
            "token_velocity": round(token_velocity, 0),
            "cache_roi_usd": round(cache_roi, 2),
            "wow_change_pct": round(wow_change, 1),
            "rightsizing_savings": rightsizing_savings,
            "avg_output_tokens": int(avg_output),
        })

    return result


# ── Compaction intelligence ──

def compaction_metrics(conn, account="all"):
    ACCOUNTS = get_accounts_config(conn)
    rows_30d = _fetch_rows(conn, account, _days_ago(30))
    if not rows_30d:
        return {"avg_savings_pct": 0, "compaction_count": 0, "sessions_needing_compact": 0, "per_project": []}

    sessions = defaultdict(list)
    for r in rows_30d:
        sessions[r["session_id"]].append(r)

    savings = []
    high_usage_no_compact = 0

    for sid, turns in sessions.items():
        turns.sort(key=lambda x: x["timestamp"])
        session_has_compact = False
        # Compute both tokens-seen (for window budgeting) and context-size
        # (for compaction heuristic). Context = input + cache_read because
        # under prompt caching the real inbound prompt size lives in cache_read.
        total_tokens = sum(t["input_tokens"] + t["output_tokens"] for t in turns)

        for i in range(1, len(turns)):
            prev_ctx = turns[i - 1]["input_tokens"] + turns[i - 1]["cache_read_tokens"]
            curr_ctx = turns[i]["input_tokens"] + turns[i]["cache_read_tokens"]
            if prev_ctx > 1000 and curr_ctx < prev_ctx * 0.7:
                pct = (prev_ctx - curr_ctx) / prev_ctx * 100
                savings.append(pct)
                session_has_compact = True

        # Use the first matching account's limit, or 1M default
        first_acct = turns[0]["account"] if turns else None
        window_limit = ACCOUNTS.get(first_acct, {}).get("window_token_limit", 1_000_000)
        # Peak context in session: largest single-turn input+cache_read
        peak_ctx = max((t["input_tokens"] + t["cache_read_tokens"] for t in turns), default=0)
        if peak_ctx > window_limit * 0.7 and not session_has_compact:
            high_usage_no_compact += 1

    project_compact = defaultdict(lambda: {"compact_count": 0, "turn_count": 0, "session_count": 0})
    for sid, turns in sessions.items():
        proj = turns[0]["project"] if turns else "Other"
        project_compact[proj]["session_count"] += 1
        project_compact[proj]["turn_count"] += len(turns)
        for i in range(1, len(turns)):
            prev_ctx = turns[i - 1]["input_tokens"] + turns[i - 1]["cache_read_tokens"]
            curr_ctx = turns[i]["input_tokens"] + turns[i]["cache_read_tokens"]
            if prev_ctx > 1000 and curr_ctx < prev_ctx * 0.7:
                project_compact[proj]["compact_count"] += 1

    per_project = []
    for proj, data in project_compact.items():
        avg_turns_between = (data["turn_count"] / data["compact_count"]) if data["compact_count"] > 0 else 0
        per_project.append({
            "project": proj,
            "compact_count": data["compact_count"],
            "avg_turns_between_compact": round(avg_turns_between, 1),
            "sessions_needing_compact": 0,
        })

    avg = sum(savings) / len(savings) if savings else 0
    return {
        "avg_savings_pct": round(avg, 1),
        "compaction_count": len(savings),
        "sessions_needing_compact": high_usage_no_compact,
        "per_project": per_project,
    }


# ── Model rightsizing ──

def model_rightsizing(conn, account="all"):
    rows_30d = _fetch_rows(conn, account, _days_ago(30))
    project_opus = {}
    for r in rows_30d:
        if r["model"] != "claude-opus":
            continue
        p = r["project"]
        if p not in project_opus:
            project_opus[p] = {"output_tokens": [], "cost": 0.0, "sessions": set()}
        project_opus[p]["output_tokens"].append(r["output_tokens"])
        project_opus[p]["cost"] += r["cost_usd"]
        project_opus[p]["sessions"].add(r["session_id"])

    suggestions = []
    for p, d in project_opus.items():
        avg_output = sum(d["output_tokens"]) / len(d["output_tokens"]) if d["output_tokens"] else 0
        if avg_output < 800:
            opus_cost = d["cost"]
            sonnet_ratio = MODEL_PRICING["claude-sonnet"]["output"] / MODEL_PRICING["claude-opus"]["output"]
            estimated_sonnet_cost = opus_cost * sonnet_ratio
            monthly_savings = opus_cost - estimated_sonnet_cost
            suggestions.append({
                "project": p,
                "avg_output_tokens": int(avg_output),
                "current_model": "claude-opus",
                "monthly_savings": round(monthly_savings, 2),
            })
    return suggestions


# ── Trends ──

def compute_daily_snapshots(conn, account="all"):
    rows_30d = _fetch_rows(conn, account, _days_ago(30))
    if not rows_30d:
        return

    buckets = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "cache_read": 0, "cache_create": 0, "sessions": set()})
    for r in rows_30d:
        dt = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d")
        key = (date_str, r["account"], r["project"])
        b = buckets[key]
        b["tokens"] += r["input_tokens"] + r["output_tokens"]
        b["cost"] += r["cost_usd"]
        b["cache_read"] += r["cache_read_tokens"]
        b["cache_create"] += r["cache_creation_tokens"]
        b["sessions"].add(r["session_id"])

    for (date_str, acct, proj), b in buckets.items():
        cache_activity = b["cache_read"] + b["cache_create"]
        cache_rate = (b["cache_read"] / cache_activity * 100) if cache_activity > 0 else 0
        upsert_daily_snapshot(conn, date_str, acct, proj, b["tokens"], round(b["cost"], 4), round(cache_rate, 1), len(b["sessions"]))

    conn.commit()


def trend_metrics(conn, account="all", days=7):
    snapshots = get_daily_snapshots(conn, account, days)

    daily = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "sessions": 0})
    for s in snapshots:
        d = daily[s["date"]]
        d["tokens"] += s["total_tokens"]
        d["cost"] += s["total_cost_usd"]
        d["sessions"] += s["session_count"]

    result = []
    for date_str in sorted(daily.keys()):
        d = daily[date_str]
        result.append({
            "date": date_str,
            "tokens": d["tokens"],
            "cost": round(d["cost"], 2),
            "sessions": d["sessions"],
        })

    if result:
        recent_days = result[-min(7, len(result)):]
        avg_daily_cost = sum(d["cost"] for d in recent_days) / len(recent_days)
        monthly_projection = round(avg_daily_cost * 30, 2)
    else:
        monthly_projection = 0

    proj_snapshots = defaultdict(lambda: {"this_week": 0, "last_week": 0})
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    two_weeks_ago = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    for s in snapshots:
        if s["date"] >= week_ago:
            proj_snapshots[s["project"]]["this_week"] += s["total_cost_usd"]
        elif s["date"] >= two_weeks_ago:
            proj_snapshots[s["project"]]["last_week"] += s["total_cost_usd"]

    project_wow = {}
    for proj, data in proj_snapshots.items():
        if data["last_week"] > 0:
            project_wow[proj] = round((data["this_week"] - data["last_week"]) / data["last_week"] * 100, 1)
        else:
            project_wow[proj] = 0

    return {
        "daily": result,
        "monthly_projection": monthly_projection,
        "project_wow": project_wow,
    }


# ── 5-hour window intelligence ──

def window_intelligence(conn, account="personal_max"):
    wm = window_metrics(conn, account)

    rows_7d = _fetch_rows(conn, account, _days_ago(7))
    hour_tokens = defaultdict(int)
    for r in rows_7d:
        h = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).hour
        hour_tokens[h] += r["input_tokens"] + r["output_tokens"]

    best_start = 0
    min_usage = float("inf")
    for start_h in range(24):
        block_usage = sum(hour_tokens.get((start_h + i) % 24, 0) for i in range(5))
        if block_usage < min_usage:
            min_usage = block_usage
            best_start = start_h

    history = wm.get("window_history", [])
    avg_pct = sum(w.get("pct_used", 0) for w in history) / len(history) if history else 0
    hit_limit_count = sum(1 for w in history if w.get("hit_limit", 0))

    safe_for_heavy = wm["window_pct"] < 50

    wm["best_start_hour"] = best_start
    wm["avg_window_pct_7d"] = round(avg_pct, 1)
    wm["windows_hit_limit_7d"] = hit_limit_count
    wm["safe_for_heavy_session"] = safe_for_heavy

    return wm


# ── Alert generation ──

def generate_alerts(conn):
    ACCOUNTS = get_accounts_config(conn)
    clear_alerts(conn)

    rows_7d = _fetch_rows(conn, since=_days_ago(7))
    rows_24h = _fetch_rows(conn, since=_days_ago(1))

    project_cache_7d = defaultdict(int)
    for r in rows_7d:
        project_cache_7d[r["project"]] += r["cache_creation_tokens"]

    project_cache_24h = defaultdict(int)
    for r in rows_24h:
        project_cache_24h[r["project"]] += r["cache_creation_tokens"]

    for p, cache_24h in project_cache_24h.items():
        avg_daily = project_cache_7d.get(p, 0) / 7
        if avg_daily > 0 and cache_24h > avg_daily * 3:
            insert_alert(conn, "red", p, f"Cache spike: {p}")

    for acct_key in ACCOUNTS:
        wm = window_metrics(conn, acct_key)
        if wm["minutes_to_limit"] is not None and wm["minutes_to_limit"] <= 60:
            label = ACCOUNTS[acct_key]["label"]
            insert_alert(conn, "red", acct_key,
                         f"{label} window limit in ~{wm['minutes_to_limit']} min")

    for s in model_rightsizing(conn):
        insert_alert(conn, "amber", s["project"],
                     f"Opus overuse in {s['project']} — Sonnet saves ${s['monthly_savings']:.2f}/mo")

    for acct_key in ACCOUNTS:
        wm = window_metrics(conn, acct_key)
        if wm["window_pct"] > 80:
            comp = compaction_metrics(conn, acct_key)
            if comp["compaction_count"] == 0:
                insert_alert(conn, "amber", acct_key,
                             f"No /compact detected for {ACCOUNTS[acct_key]['label']} — context bloat risk")

    projs = project_metrics(conn)
    for pm in projs:
        target = COST_TARGETS.get(pm["name"])
        if target and pm["avg_cost_per_session"] <= target:
            insert_alert(conn, "green", pm["name"],
                         f"{pm['name']} hit cost target (${pm['avg_cost_per_session']:.4f}/session)")

    conn.commit()


# ── Record window burn ──

def record_window_burn(conn, account="personal_max"):
    ACCOUNTS = get_accounts_config(conn)
    wm = window_metrics(conn, account)
    acct_info = ACCOUNTS.get(account, {})
    insert_window_burn(
        conn, account, wm["window_start"], wm["window_end"],
        wm["total_tokens"], wm["tokens_limit"],
        wm["window_pct"], 1 if wm["window_pct"] >= 100 else 0,
    )
    conn.commit()


# ── Sub-agent metrics ──

def subagent_metrics(conn, account="all"):
    """Per-project subagent cost rollup. Returns a dict keyed by project
    with subagent_session_count, subagent_cost_usd, subagent_pct_of_total,
    and the top 5 spawning parent sessions by subagent cost."""
    acct_filter = None if account == "all" else account
    params = []
    where = "1=1"
    if acct_filter:
        where += " AND account = ?"
        params.append(acct_filter)

    # Per-project rollup
    proj_rows = conn.execute(
        f"SELECT project, "
        f"       SUM(CASE WHEN is_subagent=1 THEN cost_usd ELSE 0 END) AS sub_cost, "
        f"       SUM(CASE WHEN is_subagent=1 THEN 1 ELSE 0 END) AS sub_rows, "
        f"       SUM(cost_usd) AS total_cost, "
        f"       COUNT(DISTINCT CASE WHEN is_subagent=1 THEN session_id END) AS sub_sessions "
        f"FROM sessions WHERE {where} GROUP BY project",
        params,
    ).fetchall()

    result = {}
    for r in proj_rows:
        total = r["total_cost"] or 0
        sub_cost = r["sub_cost"] or 0
        pct = (sub_cost / total * 100) if total > 0 else 0
        result[r["project"]] = {
            "subagent_session_count": r["sub_sessions"] or 0,
            "subagent_cost_usd": round(sub_cost, 4),
            "subagent_pct_of_total": round(pct, 1),
            "top_spawning_sessions": [],
        }

    # Top 5 spawning parents (per project) — parents ordered by subagent cost
    top_rows = conn.execute(
        f"SELECT project, parent_session_id, "
        f"       COUNT(DISTINCT session_id) AS spawned, "
        f"       SUM(cost_usd) AS cost "
        f"FROM sessions "
        f"WHERE is_subagent = 1 AND parent_session_id IS NOT NULL "
        f"  AND {where.replace('1=1', 'project IS NOT NULL')} "
        f"GROUP BY project, parent_session_id "
        f"ORDER BY cost DESC",
        params,
    ).fetchall()
    buckets = {}
    for r in top_rows:
        p = r["project"]
        if p not in buckets:
            buckets[p] = []
        if len(buckets[p]) < 5:
            buckets[p].append({
                "parent_session_id": r["parent_session_id"],
                "subagents_spawned": r["spawned"],
                "cost_usd": round(r["cost"] or 0, 4),
            })
    for p, lst in buckets.items():
        if p in result:
            result[p]["top_spawning_sessions"] = lst

    return result


# ── Daily budget metrics ──

def daily_budget_metrics(conn, account="all"):
    """Per-account today-vs-budget rollup. Returns dict keyed by account_id
    with today_cost, budget_usd, budget_pct, budget_remaining,
    projected_daily, on_track."""
    ACCOUNTS = get_accounts_config(conn)
    # Today midnight UTC → epoch
    now_dt = datetime.now(timezone.utc)
    midnight = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_epoch = int(midnight.timestamp())
    hours_elapsed = max((now_dt - midnight).total_seconds() / 3600.0, 0.1)

    result = {}
    keys = ACCOUNTS.keys() if account == "all" else [account]
    for acct_id in keys:
        info = ACCOUNTS.get(acct_id, {})
        budget = float(info.get("daily_budget_usd") or 0)
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS cost FROM sessions WHERE account=? AND timestamp >= ?",
            (acct_id, midnight_epoch),
        ).fetchone()
        today_cost = row["cost"] or 0
        projected = (today_cost / hours_elapsed) * 24 if hours_elapsed > 0 else today_cost
        result[acct_id] = {
            "today_cost": round(today_cost, 4),
            "budget_usd": round(budget, 2),
            "budget_pct": round((today_cost / budget * 100) if budget > 0 else 0, 1),
            "budget_remaining": round(max(budget - today_cost, 0), 4) if budget > 0 else 0,
            "projected_daily": round(projected, 4),
            "on_track": (projected <= budget) if budget > 0 else True,
            "has_budget": budget > 0,
        }
    return result


# ── Full analysis ──

def full_analysis(conn, account="all"):
    ACCOUNTS = get_accounts_config(conn)
    generate_alerts(conn)
    compute_daily_snapshots(conn, account)

    for acct_key in ACCOUNTS:
        try:
            record_window_burn(conn, acct_key)
        except Exception:
            pass

    am = account_metrics(conn, account)
    pm = project_metrics(conn, account)
    comp = compaction_metrics(conn, account)
    rs = model_rightsizing(conn, account)
    alerts = [dict(r) for r in query_alerts(conn)]
    trends = trend_metrics(conn, account, 7)

    windows = {}
    for acct_key in ACCOUNTS:
        windows[acct_key] = window_intelligence(conn, acct_key)

    from db import get_insights
    active_insights = get_insights(conn, account if account != "all" else None, dismissed=0, limit=100)

    # Include account list for dynamic tabs — attach session count so UI can hide empty accounts
    acct_session_counts = {}
    for row in conn.execute("SELECT account, COUNT(*) as cnt FROM sessions GROUP BY account").fetchall():
        acct_session_counts[row["account"]] = row["cnt"]
    accounts_list = [{"account_id": k, "label": v["label"], "color": v.get("color", "teal"),
                      "sessions_count": acct_session_counts.get(k, 0)}
                     for k, v in ACCOUNTS.items()]

    # Sub-agent rollup, daily budget, waste summary
    sub_metrics = subagent_metrics(conn, account)
    budget_metrics = daily_budget_metrics(conn, account)
    try:
        from waste_patterns import waste_summary_by_project
        waste_summary = waste_summary_by_project(conn, days=7)
    except Exception:
        waste_summary = {}

    return {
        "account": account,
        "account_label": ACCOUNTS.get(account, {}).get("label", "All Accounts"),
        "metrics": am,
        "windows": windows,
        "projects": pm,
        "compaction": comp,
        "rightsizing": rs,
        "alerts": alerts,
        "trends": trends,
        "insights_count": len(active_insights),
        "accounts_list": accounts_list,
        "subagent_metrics": sub_metrics,
        "daily_budget": budget_metrics,
        "waste_summary": waste_summary,
        "generated_at": _now(),
    }
