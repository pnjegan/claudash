"""Claudash v2-F4 — agentic fix generator (multi-provider).

Given a waste_event row, produces a targeted CLAUDE.md rule using a
pattern-specific prompt template. Dispatches to one of three back-end
providers chosen by the user:

  - anthropic       direct Anthropic Messages API (urllib, stdlib only)
  - bedrock         AWS Bedrock Runtime (optional boto3 dependency)
  - openai_compat   any OpenAI-compatible /chat/completions endpoint
                    (urllib, stdlib only) — OpenRouter, Azure OpenAI,
                    LM Studio, Ollama, vLLM, etc.

All public entry points return a dict — they never raise. Error cases
set the "error" field; callers inspect it.
"""

import json
import os
import sqlite3
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from db import get_conn, get_setting


# ─── Constants ───────────────────────────────────────────────────

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_BEDROCK_MODEL = "anthropic.claude-sonnet-4-5-20251001"
BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"
MAX_TOKENS = 1024
HTTP_TIMEOUT = 30  # seconds


# ─── Provider catalogue ─────────────────────────────────────────

SUPPORTED_PROVIDERS = {
    "anthropic": {
        "label": "Anthropic API (direct)",
        "model_default": DEFAULT_MODEL,
        "requires": "anthropic_api_key",
        "cost_note": "~$0.003 per fix generation (~$0.30/100 fixes)",
        "setup": "Get key at console.anthropic.com \u2192 API Keys",
    },
    "bedrock": {
        "label": "AWS Bedrock",
        "model_default": DEFAULT_BEDROCK_MODEL,
        "requires": "aws_region",
        "cost_note": "Bedrock pricing varies by region. Check AWS console.",
        "setup": "Needs ~/.aws/credentials + bedrock:InvokeModel IAM permission",
    },
    "openai_compat": {
        "label": "OpenAI-compatible endpoint (OpenRouter, Azure, local)",
        "model_default": "",
        "requires": "openai_compat_url,openai_compat_key",
        "cost_note": "Depends on your provider/model choice",
        "setup": "Any OpenAI-compatible endpoint works (OpenRouter, Azure, LM Studio)",
    },
}

SYSTEM_PROMPT = (
    "You are a Claude Code optimization expert. Your job is to write a "
    "single targeted CLAUDE.md rule that will reduce a specific observed "
    "waste pattern. You will receive telemetry from Claudash (a dashboard "
    "that scans Claude Code JSONL transcripts) and the project's current "
    "CLAUDE.md content.\n"
    "Respond ONLY with valid JSON matching the schema provided.\n"
    "Do not explain outside the JSON. Rules must be concrete and "
    "actionable. Avoid platitudes like \"be efficient\" or \"use cache\"."
)


# ─── Prompt templates (PRD §8 + local §8.5 / §8.6) ──────────────

PROMPTS = {
    "repeated_reads": (
        "Pattern: REPEATED_READS\n"
        "Project: {project}\n"
        "Account: {account}\n"
        "Event count: {count} sessions in last 30 days\n"
        "Most re-read files (basename only — full paths intentionally stripped):\n"
        "{file_list}\n"
        "Estimated recoverable cost: ${token_cost}\n\n"
        "Current CLAUDE.md:\n"
        "<<<{claude_md}>>>\n\n"
        "Previous fixes tried on this project (chronological):\n"
        "{fix_history}\n\n"
        "Write one CLAUDE.md rule that prevents these specific re-reads.\n"
        "Return JSON:\n"
        "{{\n"
        '  "rule_text": "<markdown to append to CLAUDE.md>",\n'
        '  "reasoning": "<2-3 sentences>",\n'
        '  "expected_impact_pct": <0-100>,\n'
        '  "risk_level": "low"|"medium"|"high"\n'
        "}}"
    ),
    "floundering": (
        "Pattern: FLOUNDERING\n"
        "Project: {project}\n"
        "Sessions affected: {session_count}\n"
        "Dominant stuck tool: {tool_name}\n"
        "Retry run length (consecutive identical calls): {retry_count}\n"
        "Estimated cost at risk: ${token_cost}\n\n"
        "Current CLAUDE.md:\n"
        "<<<{claude_md}>>>\n\n"
        "Previous fixes tried:\n"
        "{fix_history}\n\n"
        "Write a CLAUDE.md rule with an explicit retry ceiling and fallback.\n"
        "Return JSON: {{\"rule_text\": ..., \"reasoning\": ..., "
        "\"expected_impact_pct\": ..., \"risk_level\": ...}}"
    ),
    "deep_no_compact": (
        "Pattern: DEEP_NO_COMPACT\n"
        "Project: {project}\n"
        "Sessions affected: {session_count}\n"
        "Average window utilization: {avg_pct}%\n"
        "Compaction events observed: {compaction_count}\n"
        "Estimated waste: ${token_cost}\n\n"
        "Current CLAUDE.md:\n"
        "<<<{claude_md}>>>\n\n"
        "Return JSON with BOTH:\n"
        "- rule_text  (CLAUDE.md instruction to compact proactively)\n"
        "- settings_change  {{\"autoCompactThreshold\": <0-1>}}\n"
        "- reasoning, expected_impact_pct, risk_level"
    ),
    "cost_outlier": (
        "Pattern: COST_OUTLIER\n"
        "Session: {session_id}\n"
        "Project: {project}\n"
        "Session cost: ${cost}  ({multiplier}x project 30-day average)\n"
        "Token breakdown: input={input}, output={output}, cache_read={cr}, cache_write={cw}\n\n"
        "Current CLAUDE.md:\n"
        "<<<{claude_md}>>>\n\n"
        "Return JSON: {{\"diagnosis\": ..., \"rule_text\": ..., "
        "\"reasoning\": ..., \"expected_impact_pct\": ..., \"risk_level\": ...}}"
    ),
    # §8.5 — local addition (not yet in PRD file)
    "bad_compact": (
        "Pattern: BAD_COMPACT\n"
        "Project: {project}\n"
        "Session: {session_id}\n"
        "Context percentage at compact: {context_pct}%\n"
        "Referential signals in next 3 user messages: {signals_found}\n"
        "Sample user message after compact: \"{sample_message}\"\n\n"
        "Current CLAUDE.md:\n"
        "<<<{claude_md}>>>\n\n"
        "Previous fixes tried:\n"
        "{fix_history}\n\n"
        "The /compact summary dropped context the user still needed. Write a "
        "CLAUDE.md rule that instructs Claude (and the user) to invoke /compact "
        "with explicit focus directives (files in scope, active task, key "
        "decisions made) rather than a bare /compact. Also return a "
        "compact_instruction the user can paste on next invocation.\n"
        "Return JSON: {{\"rule_text\": ..., \"compact_instruction\": \"<the "
        "full /compact line with focus directives>\", \"reasoning\": ..., "
        "\"expected_impact_pct\": ..., \"risk_level\": ...}}"
    ),
    "rewind_heavy": (
        "Pattern: REWIND_HEAVY\n"
        "Project: {project}\n"
        "Rewind events: {count} in last 30 days\n"
        "Avg rewinding per session: {avg_per_session}\n"
        "Estimated wasted tokens: {wasted_tokens}\n\n"
        "Current CLAUDE.md:\n"
        "<<<{claude_md}>>>\n\n"
        "Previous fixes tried:\n"
        "{fix_history}\n\n"
        "Write a CLAUDE.md rule that reduces rewind frequency by encouraging "
        "better upfront spec and constraint declaration before Claude starts work.\n"
        "Return JSON: {{\"rule_text\": ..., \"reasoning\": ..., "
        "\"expected_impact_pct\": ..., \"risk_level\": ...}}"
    ),
}


# ─── Error helper ────────────────────────────────────────────────

def _err(msg, **extra):
    """Build the uniform error-return dict. All fields required by callers
    are always present so downstream code can destructure without guards."""
    base = {
        "rule_text": "",
        "reasoning": "",
        "expected_impact_pct": 0,
        "risk_level": "low",
        "settings_change": None,
        "compact_instruction": None,
        "pattern_type": "",
        "project": "",
        "model_used": "",
        "prompt_tokens": 0,
        "output_tokens": 0,
        "error": msg,
    }
    base.update(extra)
    return base


# ─── CLAUDE.md discovery ─────────────────────────────────────────

def find_claude_md(project, conn=None):
    """Return (path, contents) or (None, '') if nothing found. Never raises.
    Discovery order:
      1. ~/.claude/projects/ — any dir case-insensitively matching project,
         then check for CLAUDE.md in that dir
      2. ~/projects/<project_lower>/CLAUDE.md
      3. ~/projects/<project>/.claude/CLAUDE.md
    """
    if not project:
        return None, ""
    home = os.path.expanduser("~")
    proj_lower = project.lower()

    # (1) walk ~/.claude/projects/
    claude_projects = os.path.join(home, ".claude", "projects")
    if os.path.isdir(claude_projects):
        try:
            for entry in os.listdir(claude_projects):
                if proj_lower in entry.lower():
                    candidate = os.path.join(claude_projects, entry, "CLAUDE.md")
                    if os.path.isfile(candidate):
                        return _safe_read(candidate)
        except OSError:
            pass

    # (2) ~/projects/<project_lower>/CLAUDE.md
    p2 = os.path.join(home, "projects", proj_lower, "CLAUDE.md")
    if os.path.isfile(p2):
        return _safe_read(p2)

    # (3) ~/projects/<project>/.claude/CLAUDE.md
    p3 = os.path.join(home, "projects", project, ".claude", "CLAUDE.md")
    if os.path.isfile(p3):
        return _safe_read(p3)

    # also try exact-case alternate
    p4 = os.path.join(home, "projects", project, "CLAUDE.md")
    if os.path.isfile(p4):
        return _safe_read(p4)

    return None, ""


def _safe_read(path, max_bytes=60_000):
    """Read up to max_bytes of a file. Returns (path, contents) or (None, '')."""
    try:
        with open(path, "r", errors="replace") as f:
            return path, f.read(max_bytes)
    except OSError:
        return None, ""


# ─── Prompt building ─────────────────────────────────────────────

def _previous_fixes(conn, project, limit=5):
    """Return newest-first list of titles + waste patterns for the project."""
    try:
        rows = conn.execute(
            "SELECT title, waste_pattern, created_at FROM fixes "
            "WHERE project = ? ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()
    except sqlite3.Error:
        return "(none)"
    if not rows:
        return "(none)"
    lines = []
    for r in rows:
        title = r["title"] if hasattr(r, "keys") else r[0]
        pattern = r["waste_pattern"] if hasattr(r, "keys") else r[1]
        lines.append(f"- [{pattern}] {title}")
    return "\n".join(lines)


def _format_file_list(detail):
    """Extract a compact file list from repeated_reads detail_json."""
    files = detail.get("files") or []
    if not isinstance(files, list):
        return "(no files)"
    lines = []
    for f in files[:10]:
        if isinstance(f, dict):
            p = f.get("path", "?")
            n = f.get("reads", "?")
            lines.append(f"  - {p} ({n} reads)")
    return "\n".join(lines) if lines else "(no files)"


def _format_runs(detail):
    """Extract floundering run info."""
    runs = detail.get("runs") or []
    if not isinstance(runs, list) or not runs:
        return ("?", 0)
    top = max(runs, key=lambda r: r.get("length", 0) if isinstance(r, dict) else 0)
    if isinstance(top, dict):
        return (top.get("tool", "?"), top.get("length", 0))
    return ("?", 0)


def _build_prompt(pattern_type, waste_event, claude_md, fix_history):
    """Fill the pattern template with values from the waste_event row."""
    tmpl = PROMPTS.get(pattern_type)
    if not tmpl:
        return None

    detail_raw = waste_event["detail_json"] if hasattr(waste_event, "keys") else waste_event[-1]
    try:
        detail = json.loads(detail_raw or "{}")
    except (json.JSONDecodeError, TypeError):
        detail = {}

    project = waste_event["project"] if hasattr(waste_event, "keys") else ""
    account = waste_event["account"] if hasattr(waste_event, "keys") else ""
    session_id = waste_event["session_id"] if hasattr(waste_event, "keys") else ""
    turn_count = waste_event["turn_count"] if hasattr(waste_event, "keys") else 0
    token_cost = waste_event["token_cost"] if hasattr(waste_event, "keys") else 0

    # Pattern-specific field assembly
    fields = {
        "project": project,
        "account": account,
        "session_id": session_id,
        "claude_md": claude_md or "(no CLAUDE.md found for this project)",
        "fix_history": fix_history,
        "token_cost": f"{float(token_cost or 0):.2f}",
    }

    if pattern_type == "repeated_reads":
        fields["count"] = len(detail.get("files") or [])
        fields["file_list"] = _format_file_list(detail)
    elif pattern_type == "floundering":
        tool, length = _format_runs(detail)
        fields["session_count"] = 1  # per-session event
        fields["tool_name"] = tool
        fields["retry_count"] = length
    elif pattern_type == "deep_no_compact":
        fields["session_count"] = 1
        fields["avg_pct"] = "unknown"
        fields["compaction_count"] = 0
    elif pattern_type == "cost_outlier":
        fields["cost"] = f"{float(detail.get('session_cost', 0) or 0):.2f}"
        fields["multiplier"] = detail.get("multiplier", "?")
        # We don't have per-session token breakdown in detail_json; best-effort
        fields["input"] = detail.get("input_tokens", "?")
        fields["output"] = detail.get("output_tokens", "?")
        fields["cr"] = detail.get("cache_read_tokens", "?")
        fields["cw"] = detail.get("cache_creation_tokens", "?")
    elif pattern_type == "bad_compact":
        fields["context_pct"] = detail.get("context_pct_at_compact", "?")
        sigs = detail.get("signals_found") or []
        fields["signals_found"] = ", ".join(sigs) if isinstance(sigs, list) else str(sigs)
        sample = (detail.get("sample_message") or "").replace('"', "'")[:200]
        fields["sample_message"] = sample
    elif pattern_type == "rewind_heavy":
        fields["count"] = detail.get("count", "?")
        fields["avg_per_session"] = detail.get("avg_per_session", "?")
        fields["wasted_tokens"] = detail.get("wasted_tokens", "?")

    try:
        return tmpl.format(**fields)
    except KeyError as e:
        # Missing placeholder — return None so caller surfaces a clean error
        return None


# ─── Provider transports ────────────────────────────────────────
#
# Each _call_* function takes a USER prompt string plus the provider-
# specific auth/model args, makes one HTTP (or boto3) call, and returns
# the raw assistant text (str). On ANY failure they raise ValueError
# with a human-readable message — the top-level dispatcher catches.
# System prompt is the module-level SYSTEM_PROMPT constant.


def _extract_anthropic_text(resp_dict):
    """Pull first text block from Anthropic Messages API response."""
    if not isinstance(resp_dict, dict):
        return ""
    content = resp_dict.get("content") or []
    if not isinstance(content, list):
        return ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "") or ""
    return ""


def _call_anthropic(prompt, model, api_key):
    """Direct Anthropic Messages API. Returns raw assistant text."""
    if not api_key:
        raise ValueError("Anthropic API key not set — run: claudash keys --set-provider")
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": prompt}],
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(ANTHROPIC_URL, data=body, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", ANTHROPIC_VERSION)
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code == 401:
            raise ValueError("Invalid Anthropic API key — run: claudash keys --set-provider")
        if e.code == 429:
            raise ValueError("Anthropic rate limited — try again in 60 seconds")
        if 500 <= e.code < 600:
            raise ValueError(f"Anthropic API error {e.code}")
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            err_body = ""
        raise ValueError(f"Anthropic API error {e.code}: {err_body}")
    except (URLError, OSError) as e:
        raise ValueError(f"Network error: {e}")
    try:
        resp_dict = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON from Anthropic: {raw[:200]}")
    text = _extract_anthropic_text(resp_dict)
    if not text:
        raise ValueError("No text block in Anthropic response")
    return text


def _call_bedrock(prompt, model, region):
    """AWS Bedrock Runtime (InvokeModel) using the Anthropic-on-Bedrock
    message shape. Requires boto3 as an optional dependency."""
    try:
        import boto3  # optional — not in requirements.txt
    except ImportError:
        raise ValueError("boto3 required for Bedrock: pip install boto3")

    model_id = model or DEFAULT_BEDROCK_MODEL
    try:
        client = boto3.client("bedrock-runtime", region_name=region or "us-east-1")
    except Exception as e:
        raise ValueError(f"Could not create Bedrock client: {e}")

    body = json.dumps({
        "anthropic_version": BEDROCK_ANTHROPIC_VERSION,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    })
    try:
        resp = client.invoke_model(modelId=model_id, body=body)
        raw = resp["body"].read().decode("utf-8", errors="replace")
    except Exception as e:
        # boto3 raises botocore.exceptions.ClientError etc.; we catch
        # broadly because we can't import botocore exceptions here.
        raise ValueError(f"Bedrock invoke_model failed: {e}")
    try:
        resp_dict = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON from Bedrock: {raw[:200]}")
    text = _extract_anthropic_text(resp_dict)
    if not text:
        raise ValueError("No text block in Bedrock response")
    return text


def _call_openai_compat(prompt, model, url, api_key):
    """Any OpenAI-compatible Chat Completions endpoint. Works for
    OpenRouter, Azure OpenAI, LM Studio, Ollama (openai compat), vLLM."""
    if not url:
        raise ValueError("OpenAI-compatible URL not set — run: claudash keys --set-provider")
    # Accept both "…/v1" base and full "…/chat/completions" URL
    u = url.rstrip("/")
    if not u.endswith("/chat/completions"):
        u = u + "/chat/completions"

    payload = {
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    if model:
        payload["model"] = model

    body = json.dumps(payload).encode("utf-8")
    req = Request(u, data=body, method="POST")
    req.add_header("content-type", "application/json")
    if api_key:
        req.add_header("authorization", f"Bearer {api_key}")
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code == 401:
            raise ValueError("Invalid OpenAI-compatible API key — run: claudash keys --set-provider")
        if e.code == 429:
            raise ValueError("OpenAI-compatible endpoint rate limited — try again in 60 seconds")
        if 500 <= e.code < 600:
            raise ValueError(f"OpenAI-compatible API error {e.code}")
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            err_body = ""
        raise ValueError(f"OpenAI-compatible API error {e.code}: {err_body}")
    except (URLError, OSError) as e:
        raise ValueError(f"Network error: {e}")
    try:
        resp_dict = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON from OpenAI-compatible endpoint: {raw[:200]}")
    choices = resp_dict.get("choices") if isinstance(resp_dict, dict) else None
    if not choices or not isinstance(choices, list):
        raise ValueError("No choices in OpenAI-compatible response")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(msg, dict):
        raise ValueError("Malformed choice in OpenAI-compatible response")
    text = msg.get("content") or ""
    if not text:
        raise ValueError("Empty content in OpenAI-compatible response")
    return text


def _call_provider(prompt, conn):
    """Route to the user-selected provider. Returns (raw_text, model_used).
    Raises ValueError on any configuration or transport failure."""
    provider = (get_setting(conn, "fix_provider") or "anthropic").strip()
    if provider == "anthropic":
        model = get_setting(conn, "fix_autogen_model") or DEFAULT_MODEL
        key = (get_setting(conn, "anthropic_api_key") or "").strip()
        return _call_anthropic(prompt, model, key), model
    if provider == "bedrock":
        model = get_setting(conn, "fix_autogen_model") or DEFAULT_BEDROCK_MODEL
        region = (get_setting(conn, "aws_region") or "us-east-1").strip()
        return _call_bedrock(prompt, model, region), model
    if provider == "openai_compat":
        url = (get_setting(conn, "openai_compat_url") or "").strip()
        key = (get_setting(conn, "openai_compat_key") or "").strip()
        # Provider-specific model slot wins; falls back to fix_autogen_model
        model = (get_setting(conn, "openai_compat_model")
                 or get_setting(conn, "fix_autogen_model") or "").strip()
        return _call_openai_compat(prompt, model, url, key), (model or "(unspecified)")
    raise ValueError(
        f"Unknown fix_provider '{provider}' — run: claudash keys --set-provider"
    )


def _parse_fix_json(text):
    """Strip optional ```json fences, parse, and return (dict, None) or
    (None, error_string)."""
    s = (text or "").strip()
    if s.startswith("```"):
        # Remove opening fence line
        s = s.split("\n", 1)[1] if "\n" in s else s
        # Remove trailing fence
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    try:
        return json.loads(s), None
    except json.JSONDecodeError:
        return None, f"Invalid JSON from API: {s[:200]}"


# ─── Main entry point ────────────────────────────────────────────

_REQUIRED_FIELDS = ("rule_text", "reasoning", "expected_impact_pct", "risk_level")


def generate_fix(waste_event_id, conn=None):
    """Generate a CLAUDE.md rule for the given waste_event. Returns a dict
    with error-field semantics — never raises."""
    should_close = False
    if conn is None:
        conn = get_conn()
        should_close = True
    try:
        try:
            we = conn.execute(
                "SELECT id, session_id, project, account, pattern_type, severity, "
                "       turn_count, token_cost, detail_json "
                "FROM waste_events WHERE id = ?",
                (int(waste_event_id),),
            ).fetchone()
        except (sqlite3.Error, ValueError, TypeError):
            return _err("waste_event_id not found")
        if not we:
            return _err("waste_event_id not found")

        pattern_type = we["pattern_type"]
        project = we["project"] or ""
        if pattern_type not in PROMPTS:
            return _err(
                f"Unknown pattern_type '{pattern_type}' — no prompt template",
                pattern_type=pattern_type, project=project,
            )

        claude_md_path, claude_md_text = find_claude_md(project, conn)
        fix_history = _previous_fixes(conn, project)
        prompt = _build_prompt(pattern_type, we, claude_md_text, fix_history)
        if prompt is None:
            return _err(
                "Failed to build prompt (missing template fields)",
                pattern_type=pattern_type, project=project,
            )

        # Dispatch to whichever provider the user picked. _call_provider
        # raises ValueError on any config or transport failure — catch and
        # surface as a graceful error dict.
        try:
            text, model = _call_provider(prompt, conn)
        except ValueError as e:
            return _err(str(e), pattern_type=pattern_type, project=project)

        parsed, parse_err = _parse_fix_json(text)
        if parse_err:
            return _err(parse_err, pattern_type=pattern_type, project=project, model_used=model)

        missing = [k for k in _REQUIRED_FIELDS if k not in parsed]
        if missing:
            return _err(
                f"Missing fields: {', '.join(missing)}",
                pattern_type=pattern_type, project=project, model_used=model,
            )

        # Token usage is not tracked by the multi-provider dispatcher
        # (each provider returns only str). Left at 0 — Phase 2 can
        # reintroduce usage tracking if needed.
        prompt_tokens = 0
        output_tokens = 0

        risk = (parsed.get("risk_level") or "low").lower()
        if risk not in ("low", "medium", "high"):
            risk = "low"

        try:
            impact = int(parsed.get("expected_impact_pct") or 0)
        except (TypeError, ValueError):
            impact = 0
        impact = max(0, min(100, impact))

        return {
            "rule_text": str(parsed.get("rule_text") or ""),
            "reasoning": str(parsed.get("reasoning") or ""),
            "expected_impact_pct": impact,
            "risk_level": risk,
            "settings_change": parsed.get("settings_change"),
            "compact_instruction": parsed.get("compact_instruction"),
            "pattern_type": pattern_type,
            "project": project,
            "model_used": model,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "claude_md_path": claude_md_path or "",
            "error": None,
            "_raw_prompt": prompt,
            "_raw_response": text,
        }
    finally:
        if should_close:
            conn.close()


def insert_generated_fix(conn, waste_event_id, gen):
    """Persist a generated fix as status='proposed'. Returns fix_id or None."""
    if gen.get("error"):
        return None
    title = f"AI: {gen['pattern_type']} fix for {gen['project']}"
    try:
        cur = conn.execute(
            "INSERT INTO fixes "
            "(created_at, project, waste_pattern, title, fix_type, fix_detail, "
            " baseline_json, status, generated_by, generation_prompt, "
            " generation_response, waste_event_id, applied_to_path) "
            "VALUES (?, ?, ?, ?, 'claude_md_rule', ?, '{}', 'proposed', "
            "        'claudash', ?, ?, ?, ?)",
            (
                int(time.time()),
                gen["project"],
                gen["pattern_type"],
                title,
                gen["rule_text"],
                gen.get("_raw_prompt", ""),
                gen.get("_raw_response", ""),
                int(waste_event_id),
                gen.get("claude_md_path", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.Error:
        return None
