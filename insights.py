"""Insights engine — runs after every scan, generates actionable insights."""

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from config import MODEL_PRICING, COST_TARGETS
from db import get_conn, insert_insight, get_insights, get_accounts_config, get_project_map_config
from analyzer import (
    account_metrics, window_metrics, project_metrics,
    compaction_metrics, model_rightsizing,
)


def _now():
    return int(time.time())


def _days_ago(n):
    return _now() - (n * 86400)


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


def _clear_stale_insights(conn, max_age_hours=24):
    cutoff = _now() - (max_age_hours * 3600)
    conn.execute("DELETE FROM insights WHERE dismissed = 0 AND created_at < ?", (cutoff,))
    conn.commit()


def _insight_exists_recent(conn, insight_type, project, hours=12):
    cutoff = _now() - (hours * 3600)
    row = conn.execute(
        "SELECT COUNT(*) FROM insights WHERE insight_type = ? AND project = ? AND created_at > ? AND dismissed = 0",
        (insight_type, project, cutoff),
    ).fetchone()
    return row[0] > 0


def generate_insights(conn=None):
    """Run all insight rules. Returns count of new insights generated."""
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row

    ACCOUNTS = get_accounts_config(conn)
    PROJECT_MAP = get_project_map_config(conn)

    _clear_stale_insights(conn)
    generated = 0

    # ── 1. MODEL_WASTE ──
    for acct_key in ACCOUNTS:
        rs = model_rightsizing(conn, acct_key)
        for s in rs:
            if _insight_exists_recent(conn, "model_waste", s["project"]):
                continue
            msg = (
                f"{s['project']} uses Opus but avg response is {s['avg_output_tokens']} tokens "
                f"— Sonnet saves ~${s['monthly_savings']:.2f}/mo"
            )
            detail = json.dumps({"avg_output": s["avg_output_tokens"], "savings": s["monthly_savings"]})
            insert_insight(conn, acct_key, s["project"], "model_waste", msg, detail)
            generated += 1

    # ── 2. CACHE_SPIKE ──
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
            if _insight_exists_recent(conn, "cache_spike", p):
                continue
            ratio = round(cache_24h / avg_daily, 1)
            acct = "personal_max"
            for proj_name, info in PROJECT_MAP.items():
                if proj_name == p:
                    acct = info["account"]
                    break
            msg = f"{p} cache creation spiked {ratio}x — possible CLAUDE.md reload bug"
            detail = json.dumps({"ratio": ratio, "cache_24h": cache_24h, "avg_daily": round(avg_daily)})
            insert_insight(conn, acct, p, "cache_spike", msg, detail)
            generated += 1

    # ── 3. COMPACTION_GAP ──
    for acct_key in ACCOUNTS:
        comp = compaction_metrics(conn, acct_key)
        if comp["sessions_needing_compact"] > 0:
            if _insight_exists_recent(conn, "compaction_gap", acct_key):
                continue
            n = comp["sessions_needing_compact"]
            msg = f"{n} sessions this week hit 80% context with no /compact — risk of context rot"
            detail = json.dumps({"sessions_needing_compact": n})
            insert_insight(conn, acct_key, acct_key, "compaction_gap", msg, detail)
            generated += 1

    # ── 4. COST_TARGET_HIT ──
    projs = project_metrics(conn)
    for pm in projs:
        target = COST_TARGETS.get(pm["name"])
        if target and pm["avg_cost_per_session"] <= target and pm["avg_cost_per_session"] > 0:
            if _insight_exists_recent(conn, "cost_target", pm["name"]):
                continue
            msg = f"{pm['name']} hit ${target:.2f}/file target — avg ${pm['avg_cost_per_session']:.4f}/session"
            detail = json.dumps({"target": target, "actual": pm["avg_cost_per_session"]})
            insert_insight(conn, pm["account"], pm["name"], "cost_target", msg, detail)
            generated += 1

    # ── 5. WINDOW_RISK ──
    for acct_key in ACCOUNTS:
        wm = window_metrics(conn, acct_key)
        if wm["minutes_to_limit"] is not None and wm["minutes_to_limit"] < 60:
            if _insight_exists_recent(conn, "window_risk", acct_key):
                continue
            label = ACCOUNTS[acct_key]["label"]
            pct = wm["window_pct"]
            predicted = ""
            if wm["predicted_limit_time"]:
                predicted = datetime.fromtimestamp(
                    wm["predicted_limit_time"], tz=timezone.utc
                ).strftime("%H:%M UTC")
            msg = f"{label} window at {pct:.0f}% — exhaust predicted at {predicted}"
            detail = json.dumps({"pct": pct, "minutes_left": wm["minutes_to_limit"]})
            insert_insight(conn, acct_key, acct_key, "window_risk", msg, detail)
            generated += 1

    # ── 6. ROI_MILESTONE ──
    for acct_key, acct_info in ACCOUNTS.items():
        am = account_metrics(conn, acct_key)
        roi = am.get("subscription_roi", 0)
        for threshold in [10, 5, 2]:
            if roi >= threshold:
                milestone_key = f"roi_{threshold}x"
                if _insight_exists_recent(conn, "roi_milestone", f"{acct_key}_{milestone_key}", hours=168):
                    break
                label = acct_info["label"]
                plan_cost = acct_info.get("monthly_cost_usd", 0)
                api_equiv = round(roi * plan_cost, 0)
                msg = f"{label} ROI crossed {threshold}x this month — ${api_equiv:.0f} API equiv on ${plan_cost} plan"
                detail = json.dumps({"roi": roi, "threshold": threshold, "api_equiv": api_equiv})
                insert_insight(conn, acct_key, f"{acct_key}_{milestone_key}", "roi_milestone", msg, detail)
                generated += 1
                break

    # ── 7. HEAVY_DAY_PATTERN ──
    for acct_key in ACCOUNTS:
        rows_30d_acct = _fetch_rows(conn, acct_key, _days_ago(30))
        day_sessions = defaultdict(lambda: defaultdict(int))
        for r in rows_30d_acct:
            dow = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).strftime("%A")
            day_sessions[dow][r["project"]] += 1

        if day_sessions:
            heaviest = max(day_sessions.items(), key=lambda x: sum(x[1].values()))
            day_name = heaviest[0]
            total = sum(heaviest[1].values())
            avg_day = sum(sum(v.values()) for v in day_sessions.values()) / len(day_sessions)
            if total > avg_day * 1.5:
                top_project = max(heaviest[1].items(), key=lambda x: x[1])[0]
                if not _insight_exists_recent(conn, "heavy_day", f"{acct_key}_{day_name}", hours=168):
                    label = ACCOUNTS[acct_key]["label"]
                    msg = f"{day_name}s are your heaviest Claude day — {top_project} pattern"
                    detail = json.dumps({"day": day_name, "sessions": total, "top_project": top_project})
                    insert_insight(conn, acct_key, f"{acct_key}_{day_name}", "heavy_day", msg, detail)
                    generated += 1

    # ── 8. BEST_WINDOW ──
    for acct_key in ACCOUNTS:
        rows_7d_acct = _fetch_rows(conn, acct_key, _days_ago(7))
        hour_tokens = defaultdict(int)
        for r in rows_7d_acct:
            h = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).hour
            hour_tokens[h] += r["input_tokens"] + r["output_tokens"]

        if hour_tokens:
            best_start = 0
            min_usage = float("inf")
            for start_h in range(24):
                block = sum(hour_tokens.get((start_h + i) % 24, 0) for i in range(5))
                if block < min_usage:
                    min_usage = block
                    best_start = start_h

            if not _insight_exists_recent(conn, "best_window", acct_key, hours=168):
                end_h = (best_start + 5) % 24
                msg = f"Your quietest window is {best_start}:00-{end_h}:00 UTC — ideal for autonomous runs"
                detail = json.dumps({"start_hour": best_start, "end_hour": end_h, "tokens_in_block": min_usage})
                insert_insight(conn, acct_key, acct_key, "best_window", msg, detail)
                generated += 1

    # ── 9. WINDOW_COMBINED_RISK (Code + Browser combined > 80%) ──
    try:
        from db import get_claude_ai_accounts_all, get_latest_claude_ai_snapshot
        browser_accts = get_claude_ai_accounts_all(conn)
        for ba in browser_accts:
            aid = ba["account_id"]
            if ba.get("status") != "active":
                continue
            snap = get_latest_claude_ai_snapshot(conn, aid)
            if not snap:
                continue
            # Get Code window pct
            code_wm = window_metrics(conn, aid)
            code_pct = code_wm.get("window_pct", 0)
            browser_pct = snap.get("pct_used", 0)
            acct_info = ACCOUNTS.get(aid, {})
            limit = acct_info.get("window_token_limit", 1_000_000)
            # Combined estimate (both eat from same window)
            combined_pct = code_pct + browser_pct
            if combined_pct > 80:
                if not _insight_exists_recent(conn, "window_combined_risk", aid):
                    label = acct_info.get("label", aid)
                    msg = f"Combined window (Code + browser) at {combined_pct:.0f}% for {label} — slow down"
                    detail = json.dumps({"code_pct": code_pct, "browser_pct": browser_pct, "combined": combined_pct})
                    insert_insight(conn, aid, aid, "window_combined_risk", msg, detail)
                    generated += 1
    except Exception:
        pass

    # ── 10. SESSION_EXPIRY_WARNING ──
    try:
        for ba in browser_accts:
            aid = ba["account_id"]
            if ba.get("status") == "expired":
                last_polled = ba.get("last_polled", 0) or 0
                if _now() - last_polled > 1800:  # > 30 min stale
                    if not _insight_exists_recent(conn, "session_expiry", aid):
                        label = ACCOUNTS.get(aid, {}).get("label", aid)
                        msg = f"{label} claude.ai session expired — update key in Accounts"
                        insert_insight(conn, aid, aid, "session_expiry", msg, "{}")
                        generated += 1
    except Exception:
        pass

    # ── 11. PRO_MESSAGES_LOW ──
    try:
        for ba in browser_accts:
            aid = ba["account_id"]
            if ba.get("status") != "active" or ba.get("plan") != "pro":
                continue
            snap = get_latest_claude_ai_snapshot(conn, aid)
            if not snap:
                continue
            msgs_used = snap.get("messages_used", 0)
            msgs_limit = snap.get("messages_limit", 0)
            if msgs_limit > 0 and msgs_used / msgs_limit > 0.7:
                if not _insight_exists_recent(conn, "pro_messages_low", aid):
                    label = ACCOUNTS.get(aid, {}).get("label", aid)
                    msg = f"{label} at {msgs_used}/{msgs_limit} messages — consider spacing out conversations"
                    detail = json.dumps({"used": msgs_used, "limit": msgs_limit})
                    insert_insight(conn, aid, aid, "pro_messages_low", msg, detail)
                    generated += 1
    except Exception:
        pass

    # ── 12. SUBAGENT_COST_SPIKE ──
    try:
        from analyzer import subagent_metrics as _subagent_metrics
        sm = _subagent_metrics(conn, "all")
        for proj, s in sm.items():
            if s["subagent_pct_of_total"] > 30 and s["subagent_session_count"] > 0:
                if _insight_exists_recent(conn, "subagent_cost_spike", proj):
                    continue
                pct = s["subagent_pct_of_total"]
                cost = s["subagent_cost_usd"]
                msg = (f"{proj} sub-agents consumed {pct:.0f}% of project cost "
                       f"(${cost:.2f}) — check if orchestration is efficient")
                detail = json.dumps({"pct": pct, "cost": cost,
                                     "sessions": s["subagent_session_count"]})
                # Pick any account for this project (first match)
                acct_row = conn.execute(
                    "SELECT account FROM sessions WHERE project=? LIMIT 1", (proj,)
                ).fetchone()
                acct_key = acct_row["account"] if acct_row else "all"
                insert_insight(conn, acct_key, proj, "subagent_cost_spike", msg, detail)
                generated += 1
    except Exception:
        pass

    # ── 13. FLOUNDERING_DETECTED ──
    try:
        floundering_rows = conn.execute(
            "SELECT project, account, COUNT(*) AS n, SUM(token_cost) AS wasted "
            "FROM waste_events WHERE pattern_type='floundering' "
            "  AND detected_at >= ? "
            "GROUP BY project, account",
            (_days_ago(7),),
        ).fetchall()
        for r in floundering_rows:
            proj = r["project"] or "Other"
            if _insight_exists_recent(conn, "floundering_detected", proj):
                continue
            n = r["n"] or 0
            wasted = r["wasted"] or 0
            msg = (f"{proj} has {n} floundering session{'s' if n != 1 else ''} — "
                   f"Claude stuck retrying the same tool (~${wasted:.2f} at risk)")
            detail = json.dumps({"count": n, "estimated_waste_usd": round(wasted, 4)})
            insert_insight(conn, r["account"] or "all", proj,
                           "floundering_detected", msg, detail)
            generated += 1
    except Exception:
        pass

    # ── 13b. BAD_COMPACT_DETECTED (v2-F3) ──
    try:
        bad_rows = conn.execute(
            "SELECT project, account, COUNT(*) AS n "
            "FROM waste_events WHERE pattern_type='bad_compact' "
            "  AND detected_at >= ? "
            "GROUP BY project, account",
            (_days_ago(7),),
        ).fetchall()
        # Deferred import of compact-instruction templates
        try:
            from config import COMPACT_INSTRUCTIONS as _COMPACT_INST
        except Exception:
            _COMPACT_INST = {}
        for r in bad_rows:
            proj = r["project"] or "Other"
            if _insight_exists_recent(conn, "bad_compact_detected", proj, hours=24):
                continue
            n = r["n"] or 0
            instr = _COMPACT_INST.get(proj) or _COMPACT_INST.get(
                "default",
                "/compact Focus on: [current task] [key decisions made] [files in scope]",
            )
            msg = (
                f"{proj} has {n} bad compact{'s' if n != 1 else ''} — "
                f"summaries dropped context. Use: {instr}"
            )
            detail = json.dumps({"count": n, "compact_instruction": instr})
            insert_insight(conn, r["account"] or "all", proj,
                           "bad_compact_detected", msg, detail)
            generated += 1
    except Exception:
        pass

    # ── 14. DAILY_BUDGET alerts (exceeded + warning) ──
    try:
        from analyzer import daily_budget_metrics as _daily_budget_metrics
        dbm = _daily_budget_metrics(conn, "all")
        for acct_id, b in dbm.items():
            if not b.get("has_budget"):
                continue
            label = ACCOUNTS.get(acct_id, {}).get("label", acct_id)
            cost = b["today_cost"]
            limit = b["budget_usd"]
            pct = b["budget_pct"]
            if cost > limit:
                if not _insight_exists_recent(conn, "budget_exceeded", acct_id, hours=6):
                    over = cost - limit
                    msg = (f"{label} exceeded daily budget — ${cost:.2f} spent vs "
                           f"${limit:.2f} limit (${over:.2f} over). Slow down or switch to Sonnet.")
                    detail = json.dumps({"today_cost": cost, "budget": limit, "over": over})
                    insert_insight(conn, acct_id, acct_id, "budget_exceeded", msg, detail)
                    generated += 1
            elif pct > 80:
                if not _insight_exists_recent(conn, "budget_warning", acct_id, hours=6):
                    proj_daily = b["projected_daily"]
                    msg = (f"{label} at {pct:.0f}% of daily budget — projected "
                           f"${proj_daily:.2f} vs ${limit:.2f} limit")
                    detail = json.dumps({"pct": pct, "projected": proj_daily, "budget": limit})
                    insert_insight(conn, acct_id, acct_id, "budget_warning", msg, detail)
                    generated += 1
    except Exception:
        pass

    # ── 15. REPEATED_READS_PROJECT (v3) ──
    # Surfaces the dominant waste pattern at project level. waste_events has
    # repeated_reads rows but insights.py had no rule reading them.
    try:
        rows = conn.execute(
            "SELECT project, account, "
            "       SUM(CASE WHEN detected_at > ? THEN 1 ELSE 0 END) AS last_7d, "
            "       COUNT(*) AS last_30d, "
            "       SUM(token_cost) AS cost_usd "
            "FROM waste_events "
            "WHERE pattern_type='repeated_reads' AND detected_at > ? "
            "GROUP BY project, account "
            "HAVING last_7d >= 3 OR last_30d >= 5",
            (_days_ago(7), _days_ago(30)),
        ).fetchall()
        for r in rows:
            proj = r["project"] or "Other"
            if _insight_exists_recent(conn, "repeated_reads_project", proj):
                continue
            n = r["last_7d"] or 0
            cost = r["cost_usd"] or 0
            msg = (f"{proj} re-read the same files {n} times in 7d — "
                   f"${cost:.2f} wasted. Add 'never re-read' rule to CLAUDE.md")
            detail = json.dumps({"last_7d": n, "last_30d": r["last_30d"],
                                 "cost_usd": round(cost, 2)})
            insert_insight(conn, r["account"] or "all", proj,
                           "repeated_reads_project", msg, detail)
            generated += 1
    except Exception:
        pass

    # ── 16. MULTI_COMPACT_CHURN (v3) ──
    # Orthogonal to compaction_gap (didn't compact) and bad_compact_detected
    # (single compact lost context). This one fires when a session compacted
    # multiple times — context thrashing, split work into smaller tasks.
    try:
        rows = conn.execute(
            "WITH c AS ("
            "  SELECT session_id, project, COUNT(*) AS n_compacts, "
            "         MIN(timestamp) AS first_ts "
            "  FROM lifecycle_events WHERE event_type='compact' "
            "  GROUP BY session_id, project "
            "  HAVING n_compacts >= 2"
            ") "
            "SELECT project, COUNT(*) AS churn_sessions, "
            "       MAX(n_compacts) AS worst, "
            "       SUM(CASE WHEN first_ts > ? THEN 1 ELSE 0 END) AS last_7d "
            "FROM c GROUP BY project "
            "HAVING last_7d >= 2 OR churn_sessions >= 3",
            (_days_ago(7),),
        ).fetchall()
        for r in rows:
            proj = r["project"] or "Other"
            if _insight_exists_recent(conn, "multi_compact_churn", proj):
                continue
            worst = r["worst"] or 0
            sessions = r["churn_sessions"] or 0
            msg = (f"{proj} compacted {worst} times in a single session "
                   f"({sessions} churn sessions in 30d) — "
                   f"split work into smaller tasks instead of re-compacting")
            detail = json.dumps({"worst_compacts": worst,
                                 "churn_sessions": sessions,
                                 "last_7d": r["last_7d"]})
            acct_row = conn.execute(
                "SELECT account FROM sessions WHERE project=? LIMIT 1", (proj,)
            ).fetchone()
            acct = acct_row["account"] if acct_row else "all"
            insert_insight(conn, acct, proj, "multi_compact_churn", msg, detail)
            generated += 1
    except Exception:
        pass

    # ── 17. COST_OUTLIER_SESSION (v3) ──
    # Per-session surface for waste_events.pattern_type='cost_outlier'. The
    # data is populated by waste_patterns.py but no insight surfaced it.
    try:
        rows = conn.execute(
            "SELECT session_id, project, account, detected_at, token_cost "
            "FROM waste_events "
            "WHERE pattern_type='cost_outlier' AND detected_at > ? "
            "ORDER BY token_cost DESC",
            (_days_ago(7),),
        ).fetchall()
        for r in rows:
            proj = r["project"] or "Other"
            sid_short = (r["session_id"] or "")[:12]
            # Debounce per-session (not per-project) — key is sid_short
            if _insight_exists_recent(conn, "cost_outlier_session",
                                      f"{proj}_{sid_short}", hours=168):
                continue
            cost = r["token_cost"] or 0
            date_str = datetime.fromtimestamp(
                r["detected_at"], tz=timezone.utc
            ).strftime("%Y-%m-%d")
            msg = (f"{proj} spike — session {sid_short} on {date_str} "
                   f"cost ${cost:.2f}. Check for runaway loop or subagent chain")
            detail = json.dumps({"session_id": r["session_id"],
                                 "cost_usd": round(cost, 2),
                                 "date": date_str})
            insert_insight(conn, r["account"] or "all",
                           f"{proj}_{sid_short}",
                           "cost_outlier_session", msg, detail)
            generated += 1
    except Exception:
        pass

    # ── 18. FIX_NEVER_MEASURED (v3) ──
    # Applied fix with zero fix_measurements after 24h — agentic-loop QA gap.
    # Fires BEFORE fix_regressing (which requires a verdict to exist).
    try:
        rows = conn.execute(
            "SELECT f.id, f.project, f.waste_pattern, f.created_at, "
            "       COUNT(m.id) AS meas_count "
            "FROM fixes f LEFT JOIN fix_measurements m ON f.id=m.fix_id "
            "WHERE f.status='applied' "
            "GROUP BY f.id "
            "HAVING meas_count = 0 "
            "  AND (strftime('%s','now') - f.created_at) > 24*3600"
        ).fetchall()
        for r in rows:
            proj = r["project"] or "Other"
            fid = r["id"]
            key = f"{proj}_fix{fid}"
            if _insight_exists_recent(conn, "fix_never_measured", key, hours=24):
                continue
            hours = (_now() - (r["created_at"] or _now())) / 3600.0
            msg = (f"Fix #{fid} ({r['waste_pattern']}) applied {hours:.0f}h ago "
                   f"but never measured — run: cli.py measure {fid}")
            detail = json.dumps({"fix_id": fid, "hours_since_applied": round(hours, 1),
                                 "waste_pattern": r["waste_pattern"]})
            acct_row = conn.execute(
                "SELECT account FROM sessions WHERE project=? LIMIT 1", (proj,)
            ).fetchone()
            acct = acct_row["account"] if acct_row else "all"
            insert_insight(conn, acct, key, "fix_never_measured", msg, detail)
            generated += 1
    except Exception:
        pass

    conn.commit()
    if should_close:
        conn.close()

    return generated
