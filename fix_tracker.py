"""Fix Tracker — record a fix, measure whether it worked.

Workflow:
  1. User records a fix for a project + waste pattern via `POST /api/fixes`
     or `cli.py fix add`. Claudash snapshots the project's current metrics
     into `fixes.baseline_json`.
  2. User applies the fix to their CLAUDE.md / settings.json / prompts /
     architecture and uses Claude Code normally for a week.
  3. User runs `POST /api/fixes/{id}/measure` (or `cli.py measure {id}`).
     Claudash captures a fresh snapshot, diffs it against the baseline,
     assigns a plan-aware verdict, and stores the measurement.
  4. The dashboard shows the before/after delta; a share-card endpoint
     produces a plain-text receipt the user can paste anywhere.

Plan-aware framing — the module's most important contract:

  * Max / Pro (flat subscription):
      Primary metric = **window efficiency** (useful tokens / total tokens).
      Savings are reported as "API-equivalent waste eliminated", never as
      "you saved $X". The story is "same $100/mo plan, 2.5× more output".
  * API (pay-per-token):
      Primary metric = **cost_usd**. Savings are real dollars. The story
      is "spent $X less this month".

This module never conflates the two. The verdict logic, the delta JSON,
the share card, and the CLI output all branch on `plan_type`.
"""

import json
import os
import sqlite3
import time
from collections import defaultdict

from db import (
    get_conn, get_accounts_config, insert_fix, get_fix, get_all_fixes,
    update_fix_status, insert_fix_measurement, get_fix_measurements,
    get_latest_fix_measurement,
)


# ─── Constants ───────────────────────────────────────────────────

WASTE_PATTERNS = [
    "floundering",
    "repeated_reads",
    "deep_no_compact",
    "cost_outlier",
    "cache_spike",
    "model_waste",
    "compaction_late",
    "custom",
]

FIX_TYPES = [
    "claude_md",
    "settings_json",
    "prompt",
    "architecture",
    "other",
]

WASTE_PATTERN_LABELS = {
    "floundering":       "Floundering (tool retry loops)",
    "repeated_reads":    "Repeated file reads",
    "deep_no_compact":   "Deep session without compaction",
    "cost_outlier":      "Cost outlier session",
    "cache_spike":       "Cache creation spike",
    "model_waste":       "Model waste (Opus for small outputs)",
    "compaction_late":   "Compaction fired too late",
    "custom":            "Custom pattern",
}

# Plan-aware thresholds. Applied to the delta computation in
# `determine_verdict` — see the body of that function for how they're used.
MIN_SESSIONS_FOR_VERDICT = 3
WASTE_IMPROVING_PCT = 20
WASTE_WORSENED_PCT = 10
WINDOW_IMPROVING_PCT = 15
WINDOW_WORSENED_PCT = 10
COST_IMPROVING_PCT = 10
COST_WORSENED_PCT = 10
CONFIRM_MIN_DAYS = 7


# ─── Plan lookup ─────────────────────────────────────────────────

def get_project_plan_info(conn, project):
    """Return (account_id, plan_type, monthly_cost_usd) for a project.

    We look up the first session row for the project to find its account,
    then read plan + monthly cost from the accounts table. Returns
    ('all', 'max', 0.0) if the project has no data yet (new install path).
    """
    row = conn.execute(
        "SELECT account FROM sessions WHERE project = ? LIMIT 1",
        (project,),
    ).fetchone()
    acct_id = (row["account"] if row else None) or "all"
    accounts = get_accounts_config(conn)
    info = accounts.get(acct_id) or {}
    plan = info.get("plan") or "max"
    cost = float(info.get("monthly_cost_usd") or 0)
    return acct_id, plan, cost


# ─── Baseline capture ────────────────────────────────────────────

def capture_baseline(conn, project, days_window=7, since_override=None):
    """Snapshot the project's key metrics. Safe to call repeatedly — the
    snapshot is self-contained and travels inside `fixes.baseline_json`.

    `since_override`: when provided (unix ts), overrides the default
    "last N days" window. Used at measure time to scope the current
    snapshot to sessions AFTER the fix was applied — without it, every
    fix for the same project gets an identical current snapshot."""
    acct_id, plan, plan_cost = get_project_plan_info(conn, project)
    if since_override is not None:
        since = int(since_override)
    else:
        since = int(time.time()) - (days_window * 86400)

    # Aggregate session rows for this project in the window
    agg = conn.execute(
        """SELECT
             COUNT(DISTINCT session_id) AS sessions,
             COALESCE(SUM(cost_usd), 0) AS total_cost,
             COALESCE(SUM(cache_read_tokens), 0) AS cache_read,
             COALESCE(SUM(cache_creation_tokens), 0) AS cache_create,
             COALESCE(SUM(input_tokens), 0) AS input_tok,
             COALESCE(SUM(output_tokens), 0) AS output_tok,
             COUNT(*) AS total_rows,
             COALESCE(SUM(CASE WHEN compaction_detected=1 THEN 1 ELSE 0 END), 0) AS compactions,
             COALESCE(SUM(CASE WHEN is_subagent=1 THEN cost_usd ELSE 0 END), 0) AS subagent_cost
           FROM sessions
           WHERE project = ? AND timestamp >= ?""",
        (project, since),
    ).fetchone()

    sessions_count = agg["sessions"] or 0
    total_cost = float(agg["total_cost"] or 0)
    cache_read = int(agg["cache_read"] or 0)
    cache_create = int(agg["cache_create"] or 0)
    input_tok = int(agg["input_tok"] or 0)
    output_tok = int(agg["output_tok"] or 0)
    total_rows = int(agg["total_rows"] or 0)
    compactions = int(agg["compactions"] or 0)
    subagent_cost = float(agg["subagent_cost"] or 0)

    avg_cost_per_session = (total_cost / sessions_count) if sessions_count > 0 else 0.0

    total_cache_activity = cache_read + cache_create
    cache_hit_rate = (cache_read / total_cache_activity * 100) if total_cache_activity > 0 else 0.0

    total_tokens = input_tok + cache_read  # inbound context size
    avg_tokens_per_turn = (total_tokens / total_rows) if total_rows > 0 else 0.0
    avg_cache_read_per_turn = (cache_read / total_rows) if total_rows > 0 else 0.0

    avg_turns_per_session = (total_rows / sessions_count) if sessions_count > 0 else 0.0
    compaction_rate = (compactions / sessions_count) if sessions_count > 0 else 0.0

    # Waste events within the same window
    waste_rows = conn.execute(
        """SELECT pattern_type, COUNT(*) AS n
           FROM waste_events
           WHERE project = ? AND detected_at >= ?
           GROUP BY pattern_type""",
        (project, since),
    ).fetchall()
    waste = {
        "floundering": 0,
        "repeated_reads": 0,
        "deep_no_compact": 0,
        "cost_outliers": 0,
        "total": 0,
    }
    for r in waste_rows:
        pt = r["pattern_type"]
        n = r["n"] or 0
        if pt == "floundering":
            waste["floundering"] = n
        elif pt == "repeated_reads":
            waste["repeated_reads"] = n
        elif pt == "deep_no_compact":
            waste["deep_no_compact"] = n
        elif pt == "cost_outlier":
            waste["cost_outliers"] = n
        waste["total"] += n

    # Token waste attribution — conservative per-turn scaling.
    #
    # Each floundering event represents ~1 wasted turn (Claude retried the
    # same tool without progress). Each repeated_read event represents
    # ~2 extra `Read` calls beyond the first necessary one. Both are scaled
    # by per-turn token averages, NOT per-session. Scaling by per-session
    # values wildly over-counts under prompt caching (cache_read dwarfs
    # everything else) and makes effective_window_pct collapse to 0.
    REPEATED_READ_EXTRA_TURNS = 2
    tokens_wasted_on_floundering = int(waste["floundering"] * avg_tokens_per_turn)
    tokens_wasted_on_repeated_reads = int(
        waste["repeated_reads"] * REPEATED_READ_EXTRA_TURNS * avg_cache_read_per_turn
    )
    wasted_total = tokens_wasted_on_floundering + tokens_wasted_on_repeated_reads

    if total_tokens > 0:
        effective_window_pct = max(0.0, (total_tokens - wasted_total) / total_tokens * 100)
    else:
        effective_window_pct = 0.0

    # Sub-agent cost share
    subagent_cost_pct = (subagent_cost / total_cost * 100) if total_cost > 0 else 0.0

    # Window burn → files_per_window
    # We use window_burns if populated for this account, otherwise derive
    # sessions-per-5-hour-block from session timestamps.
    fpw = _estimate_files_per_window(conn, project, acct_id, since)

    # Window hit rate (0..1) — fraction of rolled-up windows that hit 100%
    hit = conn.execute(
        "SELECT COALESCE(AVG(CASE WHEN hit_limit=1 THEN 1.0 ELSE 0.0 END), 0) "
        "FROM window_burns WHERE account = ?",
        (acct_id,),
    ).fetchone()
    window_hit_rate = float((hit[0] or 0)) if hit else 0.0

    baseline = {
        "project": project,
        "captured_at": int(time.time()),
        "days_window": days_window,
        "plan_type": plan,
        "plan_cost_usd": plan_cost,
        "sessions_count": sessions_count,
        "cost_usd": round(total_cost, 4),
        "avg_cost_per_session": round(avg_cost_per_session, 4),
        "cache_hit_rate": round(cache_hit_rate, 2),
        "avg_turns_per_session": round(avg_turns_per_session, 1),
        "compaction_events": compactions,
        "compaction_rate": round(compaction_rate, 2),
        "waste_events": waste,
        "subagent_cost_pct": round(subagent_cost_pct, 1),
        "window_hit_rate": round(window_hit_rate, 3),
        "tokens_wasted_on_floundering": tokens_wasted_on_floundering,
        "tokens_wasted_on_repeated_reads": tokens_wasted_on_repeated_reads,
        "effective_window_pct": round(effective_window_pct, 2),
        "files_per_window": fpw,
        # Scratch fields used by compute_delta
        "_total_tokens": total_tokens,
        "_avg_tokens_per_turn": round(avg_tokens_per_turn, 2),
        "_avg_cache_read_per_turn": round(avg_cache_read_per_turn, 2),
    }
    return baseline


def _estimate_files_per_window(conn, project, acct_id, since):
    """Approximate 'sessions completed per 5-hour window' for this project.

    Implementation: count distinct session_ids, bucket their first-seen
    timestamps into 5-hour buckets, then average. Returns an integer.
    """
    rows = conn.execute(
        """SELECT session_id, MIN(timestamp) AS first_seen
           FROM sessions
           WHERE project = ? AND timestamp >= ?
           GROUP BY session_id""",
        (project, since),
    ).fetchall()
    if not rows:
        return 0
    buckets = defaultdict(int)
    for r in rows:
        ts = r["first_seen"] or 0
        buckets[ts // 18000] += 1
    if not buckets:
        return 0
    return int(round(sum(buckets.values()) / len(buckets)))


# ─── Delta computation + verdict ─────────────────────────────────

def _pct_change(before, after):
    """Signed percent change. Returns 0 when `before` is 0 to avoid inf."""
    if before == 0:
        return 0.0
    return round(((after - before) / before) * 100.0, 1)


def compute_delta(conn, fix_id):
    """Capture current metrics for the fixed project, diff against baseline,
    assign a verdict, return (delta_json, verdict, current_metrics)."""
    fix = get_fix(conn, fix_id)
    if not fix:
        return None, "not_found", None
    baseline = json.loads(fix["baseline_json"] or "{}")
    project = fix["project"]
    plan_type = baseline.get("plan_type", "max")
    plan_cost = baseline.get("plan_cost_usd", 0)

    # BUG 1 fix: current snapshot must be scoped to sessions AFTER the fix
    # was recorded, not "last 7 days" of the project — otherwise every fix
    # for the same project returns identical numbers.
    current = capture_baseline(
        conn, project,
        days_window=baseline.get("days_window", 7),
        since_override=fix["created_at"] or 0,
    )

    # Sessions since the fix was recorded (ANY row belonging to a session_id
    # with a timestamp after fix.created_at)
    sessions_since = conn.execute(
        """SELECT COUNT(DISTINCT session_id) FROM sessions
           WHERE project = ? AND timestamp > ?""",
        (project, fix["created_at"] or 0),
    ).fetchone()[0] or 0

    now = int(time.time())
    days_elapsed = max(int((now - (fix["created_at"] or now)) / 86400), 0)

    before_waste = baseline.get("waste_events", {}) or {}
    after_waste = current.get("waste_events", {}) or {}

    def _waste_delta(key):
        b = before_waste.get(key, 0) or 0
        a = after_waste.get(key, 0) or 0
        return {"before": b, "after": a, "pct_change": _pct_change(b, a)}

    total_before = before_waste.get("total", 0) or 0
    total_after = after_waste.get("total", 0) or 0

    before_eff = baseline.get("effective_window_pct", 0) or 0
    after_eff = current.get("effective_window_pct", 0) or 0

    before_fpw = baseline.get("files_per_window", 0) or 0
    after_fpw = current.get("files_per_window", 0) or 0

    before_cps = baseline.get("avg_cost_per_session", 0) or 0
    after_cps = current.get("avg_cost_per_session", 0) or 0

    before_total_cost = baseline.get("cost_usd", 0) or 0
    after_total_cost = current.get("cost_usd", 0) or 0

    # Token savings are the reduction in attributed waste tokens
    tokens_saved = max(
        (baseline.get("tokens_wasted_on_floundering", 0)
         + baseline.get("tokens_wasted_on_repeated_reads", 0))
        - (current.get("tokens_wasted_on_floundering", 0)
           + current.get("tokens_wasted_on_repeated_reads", 0)),
        0,
    )

    # API-equivalent monthly savings — per-session efficiency × expected
    # monthly session volume. The old "total_cost / days_window × 30"
    # formulation collapsed to 0 when the current window covered only
    # a fraction of the baseline window (BUG 2).
    baseline_window = max(baseline.get("days_window", 7), 1)
    baseline_sessions = baseline.get("sessions_count", 0) or 0
    sessions_per_month = (baseline_sessions / baseline_window) * 30.0
    per_session_saving = max(before_cps - after_cps, 0)
    api_equivalent_savings_monthly = round(per_session_saving * sessions_per_month, 2)

    # Output multiplier
    if before_fpw > 0 and after_fpw > 0:
        improvement_multiplier = round(after_fpw / before_fpw, 2)
    else:
        improvement_multiplier = 1.0

    primary_metric = "window_efficiency" if plan_type in ("max", "pro") else "cost_usd"

    delta = {
        "plan_type": plan_type,
        "plan_cost_usd": plan_cost,
        "primary_metric": primary_metric,
        "days_elapsed": days_elapsed,
        "sessions_since_fix": sessions_since,
        "waste_events": {"before": total_before, "after": total_after,
                         "pct_change": _pct_change(total_before, total_after)},
        "floundering": _waste_delta("floundering"),
        "repeated_reads": _waste_delta("repeated_reads"),
        "deep_no_compact": _waste_delta("deep_no_compact"),
        "cost_outliers": _waste_delta("cost_outliers"),
        "effective_window_pct": {"before": round(before_eff, 1),
                                 "after": round(after_eff, 1),
                                 "pct_change": _pct_change(before_eff, after_eff)},
        "tokens_saved": tokens_saved,
        "files_per_window": {"before": before_fpw, "after": after_fpw,
                             "pct_change": _pct_change(before_fpw, after_fpw)},
        "avg_cost_per_session": {"before": round(before_cps, 4),
                                 "after": round(after_cps, 4),
                                 "pct_change": _pct_change(before_cps, after_cps)},
        "cost_usd": {"before": round(before_total_cost, 2),
                     "after": round(after_total_cost, 2),
                     "pct_change": _pct_change(before_total_cost, after_total_cost)},
        "avg_turns_per_session": {"before": baseline.get("avg_turns_per_session", 0),
                                  "after": current.get("avg_turns_per_session", 0),
                                  "pct_change": _pct_change(
                                      baseline.get("avg_turns_per_session", 0),
                                      current.get("avg_turns_per_session", 0))},
        "api_equivalent_savings_monthly": api_equivalent_savings_monthly,
        "improvement_multiplier": improvement_multiplier,
    }

    verdict = determine_verdict(delta, plan_type, sessions_since)
    return delta, verdict, current


def determine_verdict(delta, plan_type, sessions_since):
    """Return 'improving' | 'worsened' | 'neutral' | 'insufficient_data'.

    Plan-aware: max/pro use window efficiency as the primary signal; api
    uses raw cost. Waste events are always a valid trigger in both modes
    because reducing waste should help either metric.
    """
    if sessions_since < MIN_SESSIONS_FOR_VERDICT:
        return "insufficient_data"

    waste_pct = delta["waste_events"]["pct_change"]
    if waste_pct <= -WASTE_IMPROVING_PCT:
        return "improving"
    if waste_pct >= WASTE_WORSENED_PCT:
        return "worsened"

    if plan_type in ("max", "pro"):
        # Cost+turns override: effective_window_pct is a ratio
        # (waste_tokens / total_tokens). When a fix shrinks total_tokens
        # faster than waste_tokens (e.g. trimmed CLAUDE.md), the ratio
        # can degrade even though cost and turn count fell. Treat a
        # simultaneous drop in cost and avg_turns_per_session as
        # unambiguous improvement and short-circuit the ratio check.
        cost_pct = delta.get("cost_usd", {}).get("pct_change", 0) or 0
        turns_pct = delta.get("avg_turns_per_session", {}).get("pct_change", 0) or 0
        if cost_pct <= -20 and turns_pct <= -20:
            return "improving"
        eff_pct = delta["effective_window_pct"]["pct_change"]
        if eff_pct >= WINDOW_IMPROVING_PCT:
            return "improving"
        if eff_pct <= -WINDOW_WORSENED_PCT:
            return "worsened"
    else:  # api
        cost_pct = delta["cost_usd"]["pct_change"]
        if cost_pct <= -COST_IMPROVING_PCT:
            return "improving"
        if cost_pct >= COST_WORSENED_PCT:
            return "worsened"

    return "neutral"


def record_fix(conn, project, waste_pattern, title, fix_type, fix_detail):
    """Capture a baseline and persist a new fix row. Return (fix_id, baseline)."""
    if waste_pattern not in WASTE_PATTERNS:
        waste_pattern = "custom"
    if fix_type not in FIX_TYPES:
        fix_type = "other"
    baseline = capture_baseline(conn, project)
    fix_id = insert_fix(conn, project, waste_pattern, title, fix_type, fix_detail, baseline)
    return fix_id, baseline


def measure_fix(conn, fix_id):
    """Run a measurement for a fix and persist it. Returns
    (delta_json, verdict, metrics) or (None, 'not_found', None)."""
    delta, verdict, metrics = compute_delta(conn, fix_id)
    if delta is None:
        return None, verdict, None
    insert_fix_measurement(conn, fix_id, metrics, delta, verdict)
    # Promote to 'confirmed' once we have a durable improvement
    if verdict == "improving" and delta.get("days_elapsed", 0) >= CONFIRM_MIN_DAYS:
        update_fix_status(conn, fix_id, "confirmed")
    elif verdict == "worsened":
        update_fix_status(conn, fix_id, "applied")  # keep 'applied' on regression
    else:
        update_fix_status(conn, fix_id, "measuring")
    return delta, verdict, metrics


# ─── Share card ──────────────────────────────────────────────────

def build_share_card(fix, latest_measurement):
    """Return a plain-text share card, plan-aware. See module docstring for
    the framing rules."""
    baseline = json.loads(fix["baseline_json"] or "{}")
    plan_type = baseline.get("plan_type", "max")
    plan_cost = baseline.get("plan_cost_usd", 0)
    project = fix["project"]
    pattern = fix["waste_pattern"] or ""
    pattern_label = WASTE_PATTERN_LABELS.get(pattern, pattern.replace("_", " "))
    title = fix["title"] or "(no title)"
    border = "─" * 46

    lines = [border, "Fixed a Claude Code waste pattern with Claudash", ""]
    lines.append(f"Project: {project}")
    lines.append(f"Issue: {pattern_label}")
    lines.append(f"Fix: {title}")
    lines.append("")

    if not latest_measurement:
        lines.append("(No measurements yet — run `cli.py measure` after ≥7 days.)")
        lines.append("")
        lines.append("Detected by Claudash — github.com/pnjegan/claudash")
        lines.append(border)
        return "\n".join(lines)

    delta = json.loads(latest_measurement.get("delta_json") or "{}")
    days = delta.get("days_elapsed", 0)
    waste = delta.get("waste_events", {})
    waste_before = waste.get("before", 0)
    waste_after = waste.get("after", 0)
    waste_pct = waste.get("pct_change", 0)

    lines.append(f"Before → After ({days} days):")
    lines.append(f"• {pattern_label} events: {waste_before} → {waste_after} ({_signed(waste_pct)}%)")

    if plan_type in ("max", "pro"):
        eff = delta.get("effective_window_pct", {})
        fpw = delta.get("files_per_window", {})
        lines.append(f"• Window efficiency: {eff.get('before', 0)}% → {eff.get('after', 0)}% useful tokens")
        lines.append(f"• Output per window: {fpw.get('before', 0)} → {fpw.get('after', 0)} files ({_signed(fpw.get('pct_change', 0))}%)")
        lines.append("")
        mult = delta.get("improvement_multiplier", 1.0)
        api_eq = delta.get("api_equivalent_savings_monthly", 0)
        lines.append(f"Same ${plan_cost:.0f}/mo plan. {mult}× more output.")
        lines.append(f"API-equivalent waste eliminated: ~${api_eq:.0f}/mo")
    else:  # api
        cps = delta.get("avg_cost_per_session", {})
        monthly = delta.get("api_equivalent_savings_monthly", 0)
        lines.append(f"• Cost per session: ${cps.get('before', 0):.2f} → ${cps.get('after', 0):.2f} ({_signed(cps.get('pct_change', 0))}%)")
        lines.append(f"• Monthly savings: ~${monthly:.0f}/mo")

    lines.append("")
    lines.append("Detected by Claudash — github.com/pnjegan/claudash")
    lines.append(border)
    return "\n".join(lines)


def _signed(pct):
    """Format a percent change with an explicit sign."""
    return f"+{pct:.0f}" if pct > 0 else f"{pct:.0f}"


# ─── Aggregation helpers used by API/CLI/UI ──────────────────────

def fix_with_latest(conn, fix_id):
    """Return a fix dict with baseline parsed, measurements list, and
    a top-level `latest` measurement shortcut."""
    fix = get_fix(conn, fix_id)
    if not fix:
        return None
    fix["baseline"] = json.loads(fix.pop("baseline_json") or "{}")
    measurements = get_fix_measurements(conn, fix_id)
    for m in measurements:
        m["metrics"] = json.loads(m.pop("metrics_json") or "{}")
        m["delta"] = json.loads(m.pop("delta_json") or "{}")
    fix["measurements"] = measurements
    fix["latest"] = measurements[-1] if measurements else None
    return fix


def all_fixes_with_latest(conn):
    rows = get_all_fixes(conn)
    out = []
    for r in rows:
        r["baseline"] = json.loads(r.pop("baseline_json") or "{}")
        latest = get_latest_fix_measurement(conn, r["id"])
        if latest:
            latest["metrics"] = json.loads(latest.pop("metrics_json") or "{}")
            latest["delta"] = json.loads(latest.pop("delta_json") or "{}")
        r["latest"] = latest
        out.append(r)
    return out
