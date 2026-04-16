#!/bin/bash
# Claudash v2-F6 — PostToolUse hook.
# Fire-and-forget POST to the local dashboard. If Claudash is not
# running, curl fails silently and Claude Code continues normally.
curl -sf -X POST http://localhost:8080/api/hooks/cost-event \
  -H "Content-Type: application/json" \
  -d "{\"project\":\"${CLAUDE_PROJECT:-unknown}\",\"session_id\":\"${CLAUDE_SESSION_ID:-unknown}\",\"tool_name\":\"${CLAUDE_TOOL_NAME:-unknown}\",\"phase\":\"post\",\"actual_tokens\":${CLAUDE_OUTPUT_TOKENS:-0},\"exit_code\":${CLAUDE_TOOL_EXIT_CODE:-0}}" \
  > /dev/null 2>&1 || true
