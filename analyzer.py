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

    # Cache hit rate: cache_reads / (cache_reads + input_tokens).
    # input_tokens = non-cached input tokens. This measures what fraction of
    # total inbound context came from cache vs. fresh input.
    total_cache_read = sum(r["cache_read_tokens"] for r in rows_30d)
    total_input = sum(r["input_tokens"] for r in rows_30d)
    cache_denominator = total_cache_read + total_input
    cache_hit_rate = (total_cache_read / cache_denominator * 100) if cache_denominator > 0 else 0

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
    # Rolling 5-hour lookback from `now`. The prior epoch-modulo snap to
    # 00/05/10/15/20 UTC excluded sessions from earlier in the same real
    # 5-hour period whenever `now` had just crossed a snap boundary.
    # Anthropic's actual window resets_at may still differ — for precise
    # tracking, enable browser sync (mac-sync.py or oauth_sync.py) which
    # reads resets_at from the claude.ai API.
    ACCOUNTS = get_accounts_config(conn)
    acct_info = ACCOUNTS.get(account, {})
    if not acct_info:
        acct_info = next(iter(ACCOUNTS.values()), {})
    window_limit = acct_info.get("window_token_limit", 1_000_000)
    now = _now()
    window_seconds = MAX_WINDOW_HOURS * 3600

    acct_filter = account if account and account != "all" else None

    window_start = now - window_seconds
    window_end = now

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

    # Peak burn from the last 30 minutes, not averaged across the whole rolling
    # window. Using the full 5-h average produced a constant "~892 min to cap"
    # that never tripped the window_risk <60-min threshold.
    lookback_30 = now - 1800
    if acct_filter:
        peak_row = conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens), 0) AS peak_tokens "
            "FROM sessions WHERE account = ? AND timestamp > ?",
            (acct_filter, lookback_30),
        ).fetchone()
    else:
        peak_row = conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens), 0) AS peak_tokens "
            "FROM sessions WHERE timestamp > ?",
            (lookback_30,),
        ).fetchone()
    peak_tokens_30 = peak_row["peak_tokens"] or 0
    burn_per_second = peak_tokens_30 / 1800 if peak_tokens_30 > 0 else 0

    if total_tokens > 0 and burn_per_second > 0:
        remaining_tokens = window_limit - total_tokens
        if remaining_tokens > 0:
            seconds_to_limit = remaining_tokens / burn_per_second
            predicted_limit_time = now + seconds_to_limit
            minutes_to_limit = int(seconds_to_limit / 60)
        else:
            predicted_limit_time = None
            minutes_to_limit = None
    else:
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
                "output_tokens_list": [], "timestamps": [], "cache_roi": 0.0,
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
        pricing = MODEL_PRICING.get(r["model"], MODEL_PRICING["claude-sonnet"])
        d["cache_roi"] += r["cache_read_tokens"] * (pricing["input"] - pricing["cache_read"]) / 1_000_000

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

        cache_roi = d["cache_roi"]

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
    conditions = []
    params = []
    if acct_filter:
        conditions.append("account = ?")
        params.append(acct_filter)
    where_clause = (" AND ".join(conditions)) if conditions else "1=1"

    # Per-project rollup
    proj_rows = conn.execute(
        "SELECT project, "
        "       SUM(CASE WHEN is_subagent=1 THEN cost_usd ELSE 0 END) AS sub_cost, "
        "       SUM(CASE WHEN is_subagent=1 THEN 1 ELSE 0 END) AS sub_rows, "
        "       SUM(cost_usd) AS total_cost, "
        "       COUNT(DISTINCT CASE WHEN is_subagent=1 THEN session_id END) AS sub_sessions "
        "FROM sessions WHERE " + where_clause + " GROUP BY project",
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
    top_conditions = ["is_subagent = 1", "parent_session_id IS NOT NULL", "project IS NOT NULL"]
    if acct_filter:
        top_conditions.append("account = ?")
    top_where = " AND ".join(top_conditions)
    top_rows = conn.execute(
        "SELECT project, parent_session_id, "
        "       COUNT(DISTINCT session_id) AS spawned, "
        "       SUM(cost_usd) AS cost "
        "FROM sessions "
        "WHERE " + top_where + " "
        "GROUP BY project, parent_session_id "
        "ORDER BY cost DESC",
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


# ── v3.1 — Sub-agent work classification ──

def classify_subagent_work(s):
    """Classify a single sub-agent session's work as mechanical / mixed /
    reasoning. Input is a dict with the session-aggregate tool counts
    AND a 'turns' key (COUNT(*) of per-turn rows).

    Heuristic (additive score):
      write > 0                  → +2  (producing code = reasoning)
      mcp_count > 2              → +1
      max_output_tokens >= 2000  → +1
      tool_call_count >= 40      → +1  (high volume = investigation)
      bash > 15 AND write > 0    → +1  (build-test-iterate)

    v3.2 hallucination fix — turns_per_tool guard on the 'mechanical' label:
      If score == 0 AND turns_per_tool > 10:
        the session has lots of conversation between sparse tool calls —
        that correlates with text-heavy reasoning work, NOT mechanical
        file-shuffling. Downgrade to 'mixed' rather than confidently
        saying mechanical.
      Only return 'mechanical' when score==0 AND the session is
      actually tool-dense (turns_per_tool <= 10, equivalent to
      tools/turns >= 0.10). This avoids over-estimating Haiku savings
      on reasoning-heavy work like audits.

    Returns: 'mechanical' | 'reasoning' | 'mixed'
    """
    write = s.get("write_count") or 0
    mcp = s.get("mcp_count") or 0
    max_out = s.get("max_output_tokens") or 0
    tools = s.get("tool_call_count") or 0
    bash = s.get("bash_count") or 0
    turns = s.get("turns") or 0

    score = 0
    if write > 0:
        score += 2
    if mcp > 2:
        score += 1
    if max_out >= 2000:
        score += 1
    if tools >= 40:
        score += 1
    if bash > 15 and write > 0:
        score += 1

    if score >= 2:
        return "reasoning"

    if score == 0:
        # Tool density guard — only "mechanical" if session was tool-dense
        if tools > 0 and turns > 0:
            turns_per_tool = turns / tools
            if turns_per_tool > 10:
                # Lots of conversation between rare tool calls — not mechanical
                return "mixed"
        return "mechanical"

    return "mixed"


def subagent_intelligence(conn, account="all"):
    """Per-project sub-agent work classification with Haiku savings estimate.

    Returns {project: {mechanical_count, mechanical_cost, reasoning_count,
    reasoning_cost, mixed_count, mixed_cost, total_subagent_cost,
    haiku_savings_estimate, top_sessions: [...], verdict}}.

    Verdict:
      optimize_possible  → mechanical_cost / total > 30%
      review_mechanical  → mechanical_count > 0 (but not dominant)
      justified          → no mechanical work"""
    acct_filter = None if account == "all" else account
    where = "is_subagent=1"
    params = []
    if acct_filter:
        where += " AND account=?"
        params.append(acct_filter)

    rows = conn.execute(
        "SELECT session_id, project, "
        "       SUM(cost_usd) AS cost_usd, "
        "       COUNT(*) AS turns, "
        "       MAX(tool_call_count) AS tool_call_count, "
        "       MAX(bash_count) AS bash_count, "
        "       MAX(read_count) AS read_count, "
        "       MAX(write_count) AS write_count, "
        "       MAX(grep_count) AS grep_count, "
        "       MAX(mcp_count) AS mcp_count, "
        "       MAX(max_output_tokens) AS max_output_tokens, "
        "       MAX(prompt_quality) AS prompt_quality "
        "FROM sessions WHERE " + where + " "
        "GROUP BY session_id "
        "ORDER BY cost_usd DESC",
        params,
    ).fetchall()

    result = {}
    for r in rows:
        s = dict(r)
        project = s["project"] or "Other"
        classification = classify_subagent_work(s)

        if project not in result:
            result[project] = {
                "mechanical_count": 0, "mechanical_cost": 0.0,
                "reasoning_count": 0, "reasoning_cost": 0.0,
                "mixed_count": 0, "mixed_cost": 0.0,
                "top_sessions": [],
            }

        p = result[project]
        cost = s["cost_usd"] or 0.0
        turns = s["turns"] or 0
        tools = s["tool_call_count"] or 0
        turns_per_tool = round(turns / tools, 2) if tools > 0 else None
        cost_per_turn = round(cost / turns, 6) if turns > 0 else 0.0

        if classification == "mechanical":
            p["mechanical_count"] += 1
            p["mechanical_cost"] += cost
        elif classification == "reasoning":
            p["reasoning_count"] += 1
            p["reasoning_cost"] += cost
        else:
            p["mixed_count"] += 1
            p["mixed_cost"] += cost

        p["top_sessions"].append({
            "session_id": (s["session_id"] or "")[:12],
            "classification": classification,
            "tool_call_count": tools,
            "turns": turns,
            "turns_per_tool": turns_per_tool,
            "cost_per_turn": cost_per_turn,
            "prompt_quality": s["prompt_quality"] or "unknown",
            "cost_usd": round(cost, 4),
        })

    for project, p in result.items():
        total = p["mechanical_cost"] + p["reasoning_cost"] + p["mixed_cost"]
        p["total_subagent_cost"] = round(total, 4)
        # Haiku is ~95% cheaper than Opus on input/output; the mechanical
        # classification is a heuristic (not a guarantee). The caveat
        # field is returned alongside so consumers can render the number
        # with the appropriate hedging.
        p["haiku_savings_estimate"] = round(p["mechanical_cost"] * 0.95, 4)
        p["haiku_savings_caveat"] = (
            "mechanical_cost × 0.95 — verify classification per session "
            "before switching model; tool-dense mechanical work is safest "
            "candidate, text-heavy sessions may regress on Haiku"
        )
        p["top_sessions"] = sorted(
            p["top_sessions"], key=lambda x: x["cost_usd"], reverse=True
        )[:5]

        if total > 0 and (p["mechanical_cost"] / total) > 0.30:
            p["verdict"] = "optimize_possible"
        elif p["mechanical_count"] > 0:
            p["verdict"] = "review_mechanical"
        else:
            p["verdict"] = "justified"

    return result


# ── Context rot (v2-F2) ──

_CONTEXT_ROT_BUCKET_SIZE = 10
_CONTEXT_ROT_MIN_SESSIONS = 5
_CONTEXT_ROT_MIN_BUCKETS = 3
_CONTEXT_ROT_INFLECTION_DROP = 0.15  # first bucket >=15% below bucket 0


def compute_context_rot(conn, project, days=30):
    """Output/input ratio vs turn depth for one project. Turns are bucketed
    in groups of 10 (0-9, 10-19, ...). Inflection = first bucket whose avg
    ratio is >=15% below bucket 0. Returns a self-contained dict; never
    raises on missing/empty data."""
    fallback = {
        "project": project,
        "buckets": [],
        "inflection_bucket": None,
        "inflection_label": None,
        "recommendation": "",
        "data_sufficient": False,
    }
    if not project or not isinstance(project, str):
        fallback["recommendation"] = "project name required"
        return fallback

    since = _now() - (days * 86400)
    rows = conn.execute(
        "SELECT session_id, input_tokens, output_tokens "
        "FROM sessions WHERE project = ? AND timestamp >= ? "
        "ORDER BY session_id, timestamp",
        (project, since),
    ).fetchall()

    if not rows:
        fallback["recommendation"] = (
            f"{project}: no sessions in last {days}d"
        )
        return fallback

    # Group by session; compute turn_index per session (0-based, timestamp-ordered)
    sessions = defaultdict(list)
    for r in rows:
        sessions[r["session_id"]].append((r["input_tokens"] or 0, r["output_tokens"] or 0))

    bucket_ratios = defaultdict(list)
    bucket_sids = defaultdict(set)
    for sid, turns in sessions.items():
        for idx, (inp, out) in enumerate(turns):
            if inp <= 0:
                continue
            ratio = out / inp
            b = idx // _CONTEXT_ROT_BUCKET_SIZE
            bucket_ratios[b].append(ratio)
            bucket_sids[b].add(sid)

    if not bucket_ratios:
        fallback["recommendation"] = (
            f"{project}: no turns with input_tokens > 0 "
            "(all fully-cached — ratio undefined)"
        )
        return fallback

    buckets = []
    for b in sorted(bucket_ratios.keys()):
        ratios = bucket_ratios[b]
        lo = b * _CONTEXT_ROT_BUCKET_SIZE
        hi = lo + _CONTEXT_ROT_BUCKET_SIZE - 1
        buckets.append({
            "bucket": b,
            "label": f"{lo}-{hi}",
            "avg_ratio": round(sum(ratios) / len(ratios), 4),
            "session_count": len(bucket_sids[b]),
        })

    total_sessions = len(sessions)
    data_sufficient = (
        total_sessions >= _CONTEXT_ROT_MIN_SESSIONS
        and len(buckets) >= _CONTEXT_ROT_MIN_BUCKETS
    )

    # Inflection detection
    inflection_bucket = None
    inflection_label = None
    if buckets:
        base = buckets[0]["avg_ratio"]
        if base > 0:
            threshold = base * (1 - _CONTEXT_ROT_INFLECTION_DROP)
            for b in buckets[1:]:
                if b["avg_ratio"] < threshold:
                    inflection_bucket = b["bucket"]
                    inflection_label = b["label"]
                    break

    if not data_sufficient:
        recommendation = (
            f"{project}: not enough data ({total_sessions} session"
            f"{'s' if total_sessions != 1 else ''}, {len(buckets)} bucket"
            f"{'s' if len(buckets) != 1 else ''}) — need "
            f"{_CONTEXT_ROT_MIN_SESSIONS}+ sessions and {_CONTEXT_ROT_MIN_BUCKETS}+ buckets"
        )
    elif inflection_bucket is not None:
        compact_turn = max(inflection_bucket * _CONTEXT_ROT_BUCKET_SIZE - 5, 10)
        recommendation = (
            f"{project} sessions show context rot after ~turn "
            f"{inflection_bucket * _CONTEXT_ROT_BUCKET_SIZE}. "
            f"Consider /compact at turn {compact_turn}."
        )
    else:
        recommendation = (
            f"{project}: stable output ratio across {len(buckets)} "
            f"buckets — no rot detected"
        )

    return {
        "project": project,
        "buckets": buckets,
        "inflection_bucket": inflection_bucket,
        "inflection_label": inflection_label,
        "recommendation": recommendation,
        "data_sufficient": data_sufficient,
    }


def context_rot_by_project(conn, days=30):
    """Run compute_context_rot for every project in the window. Returns a
    dict keyed by project name."""
    since = _now() - (days * 86400)
    projs = [r[0] for r in conn.execute(
        "SELECT DISTINCT project FROM sessions WHERE timestamp >= ? AND project IS NOT NULL",
        (since,),
    ).fetchall() if r[0]]
    return {p: compute_context_rot(conn, p, days=days) for p in projs}


# ── Lifecycle events summary (v2-F1) ──

def lifecycle_by_project(conn, days=30):
    """Per-project rollup of lifecycle events for the dashboard. Returns a
    dict keyed by project name with compact_count, subagent_spawn_count,
    avg_compact_timing_pct, late_compacts (>75%)."""
    since = _now() - (days * 86400)
    rows = conn.execute(
        "SELECT project, event_type, context_pct_at_event "
        "FROM lifecycle_events WHERE timestamp >= ?",
        (since,),
    ).fetchall()
    buckets = {}
    for r in rows:
        p = r["project"]
        if p not in buckets:
            buckets[p] = {
                "compact_count": 0,
                "subagent_spawn_count": 0,
                "compact_pcts": [],
                "late_compacts": 0,
            }
        b = buckets[p]
        if r["event_type"] == "compact":
            b["compact_count"] += 1
            pct = r["context_pct_at_event"]
            if pct is not None:
                b["compact_pcts"].append(pct)
                if pct > 75:
                    b["late_compacts"] += 1
        elif r["event_type"] == "subagent_spawn":
            b["subagent_spawn_count"] += 1
    result = {}
    for p, b in buckets.items():
        pcts = b.pop("compact_pcts")
        avg = round(sum(pcts) / len(pcts), 1) if pcts else 0
        b["avg_compact_timing_pct"] = avg
        result[p] = b
    return result


# ── autoCompactThreshold recommendations (v2-F7) ──

_F7_DEFAULT_THRESHOLD = 0.70
_F7_DEFAULT_CLAUDE_MD = (
    "When context reaches 70%, run /compact with a focused description "
    "of the current task before continuing."
)


def _f7_fallback(project, compact_count=0, bad_compact_count=0,
                 reasoning=None):
    pct = int(round(_F7_DEFAULT_THRESHOLD * 100))
    return {
        "project": project or "",
        "recommended_threshold": _F7_DEFAULT_THRESHOLD,
        "recommended_threshold_pct": pct,
        "current_avg_compact_pct": 0.0,
        "compact_count": compact_count,
        "bad_compact_count": bad_compact_count,
        "confidence": "low",
        "reasoning": reasoning or (
            "No compact history yet. 0.70 is a safe default that balances "
            "context depth with quality."
        ),
        "settings_json": json.dumps(
            {"autoCompactThreshold": _F7_DEFAULT_THRESHOLD}, indent=2
        ),
        "settings_json_claude_md": _F7_DEFAULT_CLAUDE_MD,
        "data_sufficient": False,
    }


def recommend_compact_threshold(conn, project, days=30):
    """Analyse compact timing for one project and recommend an
    autoCompactThreshold setting. Returns a dict with 11 fields; never
    raises — falls back to a safe default on any error."""
    try:
        if not project or not isinstance(project, str):
            return _f7_fallback(project)

        since = _now() - (days * 86400)

        rows = conn.execute(
            "SELECT context_pct_at_event FROM lifecycle_events "
            "WHERE event_type = 'compact' AND project = ? "
            "  AND timestamp >= ? AND context_pct_at_event IS NOT NULL",
            (project, since),
        ).fetchall()
        pcts = [r[0] for r in rows if r[0] is not None]
        compact_count = len(pcts)

        bad_row = conn.execute(
            "SELECT COUNT(*) FROM waste_events "
            "WHERE pattern_type = 'bad_compact' AND project = ? "
            "  AND detected_at >= ?",
            (project, since),
        ).fetchone()
        bad_compact_count = (bad_row[0] if bad_row else 0) or 0

        # Rule E: <3 events → insufficient data, safe default
        if compact_count < 3:
            fb = _f7_fallback(
                project, compact_count, bad_compact_count,
                reasoning=(
                    "Not enough compact events to recommend yet "
                    f"(need 3+, have {compact_count}). 0.70 is a safe "
                    "default until more data accumulates."
                ),
            )
            return fb

        avg_pct = sum(pcts) / len(pcts)

        # Rules A–D
        if avg_pct > 80:
            # Rule A — late compaction
            recommended = 0.65
            reasoning = (
                f"Your {project} sessions compact at avg {avg_pct:.0f}% — "
                "too late. Setting 0.65 gives a 15% safety buffer before "
                "context rot sets in."
            )
        elif 60 <= avg_pct <= 80 and bad_compact_count > 0:
            # Rule B — good timing but bad compacts: compact 10% earlier
            recommended = round(avg_pct / 100 - 0.10, 2)
            # Safety clamp in case of extreme outliers
            recommended = max(0.30, min(recommended, 0.90))
            reasoning = (
                "Bad compacts detected — compacting slightly earlier gives "
                "more context for a quality summary."
            )
        elif 60 <= avg_pct <= 80 and bad_compact_count == 0:
            # Rule C — healthy, formalise current pattern
            recommended = round(avg_pct / 100, 2)
            reasoning = (
                "Your compact timing looks healthy. This setting formalizes "
                "your current natural pattern."
            )
        else:
            # Rule D — too early (avg < 60%)
            recommended = 0.70
            reasoning = (
                f"Your sessions compact very early (avg {avg_pct:.0f}%). "
                "Setting 0.70 allows more context to accumulate before "
                "compacting — reduces unnecessary compactions."
            )

        if compact_count >= 10:
            confidence = "high"
        else:
            confidence = "medium"

        recommended_pct = int(round(recommended * 100))
        settings_json = json.dumps(
            {"autoCompactThreshold": recommended}, indent=2
        )
        claude_md_rule = (
            f"When context reaches {recommended_pct}%, run /compact with "
            "a focused description of the current task before continuing."
        )

        return {
            "project": project,
            "recommended_threshold": recommended,
            "recommended_threshold_pct": recommended_pct,
            "current_avg_compact_pct": round(avg_pct, 1),
            "compact_count": compact_count,
            "bad_compact_count": bad_compact_count,
            "confidence": confidence,
            "reasoning": reasoning,
            "settings_json": settings_json,
            "settings_json_claude_md": claude_md_rule,
            "data_sufficient": True,
        }
    except Exception:
        return _f7_fallback(project)


def recommend_compact_all(conn, days=30):
    """Per-project recommendations for every project with at least one
    compact event in the window. Returns dict keyed by project name."""
    try:
        since = _now() - (days * 86400)
        rows = conn.execute(
            "SELECT project FROM lifecycle_events "
            "WHERE event_type = 'compact' AND timestamp >= ? "
            "  AND project IS NOT NULL AND project != '' "
            "GROUP BY project HAVING COUNT(*) >= 1",
            (since,),
        ).fetchall()
    except Exception:
        return {}
    result = {}
    for r in rows:
        proj = r[0]
        if not proj:
            continue
        result[proj] = recommend_compact_threshold(conn, proj, days=days)
    return result


def lifecycle_summary(conn, project=None, days=30):
    """Roll up compact + subagent_spawn events for one project (or all).
    A 'late compact' is one where context_pct_at_event > 75."""
    since = _now() - (days * 86400)
    sql = ("SELECT session_id, project, event_type, timestamp, "
           "context_pct_at_event, event_metadata "
           "FROM lifecycle_events WHERE timestamp >= ?")
    params = [since]
    if project:
        sql += " AND project = ?"
        params.append(project)
    sql += " ORDER BY timestamp DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    compacts = [r for r in rows if r["event_type"] == "compact"]
    spawns = [r for r in rows if r["event_type"] == "subagent_spawn"]
    compact_pcts = [r["context_pct_at_event"] for r in compacts
                    if r.get("context_pct_at_event") is not None]
    avg_timing = round(sum(compact_pcts) / len(compact_pcts), 1) if compact_pcts else 0
    late_compacts = sum(1 for p in compact_pcts if p > 75)

    # v2-F7: embed a per-project autoCompactThreshold recommendation so
    # the dashboard can render it without a second fetch. Null on error
    # or when no project is specified.
    recommendation = None
    if project:
        try:
            recommendation = recommend_compact_threshold(conn, project, days=days)
        except Exception:
            recommendation = None

    return {
        "project": project or "all",
        "days": days,
        "summary": {
            "compact_count": len(compacts),
            "subagent_spawn_count": len(spawns),
            "avg_compact_timing_pct": avg_timing,
            "late_compacts": late_compacts,
        },
        "events": rows,
        "recommendation": recommendation,
    }


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


# ── Efficiency Score ──

def compute_efficiency_score(conn, account="all"):
    """
    Compute Claude Code efficiency score 0-100.
    Five dimensions, weighted:
      1. Cache efficiency    25% — cache_read/(cache_read+input_tokens)
      2. Model right-sizing  25% — % sessions NOT using Opus for <300 tok output
      3. Window discipline   20% — avg window utilization (ideal 60-80%)
      4. Floundering rate    20% — % sessions without floundering
      5. Compaction          10% — % long sessions that used compaction
    """
    cutoff = _days_ago(30)
    where = "timestamp > ?"
    params = [cutoff]
    if account and account != "all":
        where += " AND account = ?"
        params.append(account)

    # Dimension 1: Cache efficiency
    r = conn.execute(
        f"SELECT COALESCE(SUM(cache_read_tokens), 0), COALESCE(SUM(input_tokens), 0) "
        f"FROM sessions WHERE {where}", params
    ).fetchone()
    cache_reads = r[0] or 0
    cache_inputs = r[1] or 0
    denom = cache_reads + cache_inputs
    cache_score = round(cache_reads / denom * 100) if denom > 0 else 0

    # Dimension 2: Model right-sizing
    total_opus = conn.execute(
        f"SELECT COUNT(*) FROM sessions "
        f"WHERE model LIKE '%opus%' AND {where}", params
    ).fetchone()[0]
    opus_short = conn.execute(
        f"SELECT COUNT(*) FROM sessions "
        f"WHERE model LIKE '%opus%' AND output_tokens < 300 "
        f"AND {where}", params
    ).fetchone()[0]
    if total_opus > 0:
        opus_waste_pct = opus_short / total_opus
        model_score = round((1 - opus_waste_pct) * 100)
    else:
        model_score = 100

    # Dimension 3: Window discipline (ideal 60-80%)
    avg_window = conn.execute(
        "SELECT AVG(pct_used) FROM window_burns "
        "WHERE window_start > ? AND pct_used > 0",
        [cutoff]
    ).fetchone()[0] or 0
    if avg_window < 60:
        window_score = round(avg_window / 60 * 70)
    elif avg_window <= 80:
        window_score = round(70 + (avg_window - 60) / 20 * 30)
    else:
        window_score = round(100 - (avg_window - 80) * 2)
    window_score = max(0, min(100, window_score))

    # Dimension 4: Floundering rate
    # Count DISTINCT sessions (not events) with floundering, filtered by account
    total_sessions = conn.execute(
        f"SELECT COUNT(DISTINCT session_id) FROM sessions WHERE {where}",
        params
    ).fetchone()[0] or 1
    flounder_where = "pattern_type='floundering' AND detected_at > ?"
    flounder_params = [cutoff]
    if account and account != "all":
        flounder_where += " AND account = ?"
        flounder_params.append(account)
    flounder_sessions = conn.execute(
        f"SELECT COUNT(DISTINCT session_id) FROM waste_events WHERE {flounder_where}",
        flounder_params
    ).fetchone()[0]
    # Linear penalty: 0% flounder = 100, 1% = 90, 5% = 50, 10%+ = 0
    flounder_pct = flounder_sessions / total_sessions * 100
    flounder_score = max(0, round(100 - flounder_pct * 10))

    # Dimension 5: Compaction discipline
    compact_events = conn.execute(
        f"SELECT COUNT(*) FROM sessions "
        f"WHERE compaction_detected=1 AND {where}", params
    ).fetchone()[0]
    compact_rate = compact_events / total_sessions
    compaction_score = min(round(compact_rate / 0.05 * 100), 100)

    # Weighted total
    dimensions = [
        {"name": "cache", "score": cache_score, "weight": 0.25,
         "label": "Cache efficiency",
         "detail": f"{cache_score}% of input tokens served from cache"},
        {"name": "model", "score": model_score, "weight": 0.25,
         "label": "Model right-sizing",
         "detail": f"{100 - model_score}% of Opus sessions had short outputs"},
        {"name": "window", "score": window_score, "weight": 0.20,
         "label": "Window discipline",
         "detail": f"{round(avg_window, 1)}% avg window utilization (ideal: 60-80%)"},
        {"name": "flounder", "score": flounder_score, "weight": 0.20,
         "label": "Floundering rate",
         "detail": f"{flounder_sessions} stuck sessions detected"},
        {"name": "compaction", "score": compaction_score, "weight": 0.10,
         "label": "Compaction discipline",
         "detail": f"{compact_events} compaction events in 30d"},
        # TODO(v3.1): add 6th dimension `arch_compliance` from compliance_events
        # when 2+ weeks of data accumulates. Proposed 10% weight; rebalance
        # others -2% each. Skipped today because compliance_events has only
        # 127 rows across 30d (mostly 'passed') — not enough signal yet.
    ]

    total = round(sum(d["score"] * d["weight"] for d in dimensions))
    total = max(0, min(100, total))

    if total >= 90:
        grade = "A"
    elif total >= 80:
        grade = "B"
    elif total >= 70:
        grade = "C"
    elif total >= 60:
        grade = "D"
    else:
        grade = "F"

    worst = min(dimensions, key=lambda d: d["score"] * d["weight"])

    return {
        "score": total,
        "grade": grade,
        "dimensions": dimensions,
        "top_improvement": worst["label"],
        "top_improvement_detail": worst["detail"],
    }


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

    # Include account list for dynamic tabs — attach session count + browser data
    acct_session_counts = {}
    for row in conn.execute("SELECT account, COUNT(*) as cnt FROM sessions GROUP BY account").fetchall():
        acct_session_counts[row["account"]] = row["cnt"]
    # Latest browser snapshot per account (from claude.ai tracking)
    browser_snaps = {}
    for row in conn.execute(
        "SELECT account_id, five_hour_utilization, seven_day_utilization "
        "FROM claude_ai_snapshots "
        "WHERE id IN (SELECT MAX(id) FROM claude_ai_snapshots GROUP BY account_id)"
    ).fetchall():
        five = row["five_hour_utilization"] or 0
        seven = row["seven_day_utilization"] or 0
        browser_snaps[row["account_id"]] = {"five": five, "seven": seven}
    accounts_list = []
    for k, v in ACCOUNTS.items():
        bs = browser_snaps.get(k, {})
        accounts_list.append({
            "account_id": k, "label": v["label"], "color": v.get("color", "teal"),
            "sessions_count": acct_session_counts.get(k, 0),
            "browser_window_pct": bs.get("five", 0),
            "seven_day_pct": bs.get("seven", 0),
            "has_browser_data": bs.get("five", 0) > 0 or bs.get("seven", 0) > 0,
        })

    # Sub-agent rollup, daily budget, waste summary
    sub_metrics = subagent_metrics(conn, account)
    # v3.1 — per-project mechanical vs reasoning classification
    try:
        sub_intel = subagent_intelligence(conn, account)
    except Exception:
        sub_intel = {}
    budget_metrics = daily_budget_metrics(conn, account)
    try:
        from waste_patterns import waste_summary_by_project
        waste_summary = waste_summary_by_project(conn, days=7)
    except Exception:
        waste_summary = {}

    # v2-F1: lifecycle events per project (compact + subagent_spawn)
    try:
        lifecycle = lifecycle_by_project(conn, days=30)
    except Exception:
        lifecycle = {}

    # v2-F2: context rot trajectory per project
    try:
        context_rot = context_rot_by_project(conn, days=30)
    except Exception:
        context_rot = {}

    # v2-F7: autoCompactThreshold recommendations per project
    try:
        recommendations = recommend_compact_all(conn, days=30)
    except Exception:
        recommendations = {}

    # Efficiency score
    try:
        efficiency = compute_efficiency_score(conn, account)
    except Exception:
        efficiency = {"score": 0, "grade": "-", "dimensions": [], "top_improvement": "unknown", "top_improvement_detail": ""}

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
        "subagent_intelligence": sub_intel,
        "daily_budget": budget_metrics,
        "waste_summary": waste_summary,
        "lifecycle": lifecycle,
        "context_rot": context_rot,
        "recommendations": recommendations,
        "efficiency": efficiency,
        "generated_at": _now(),
    }
