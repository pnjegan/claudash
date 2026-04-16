#!/bin/bash
# Claudash v2-F6 — PreToolUse hook.
# Fire-and-forget POST to the local dashboard. If Claudash is not
# running, curl fails silently and Claude Code continues normally.
curl -sf -X POST http://localhost:8080/api/hooks/cost-event \
  -H "Content-Type: application/json" \
  -d "{\"project\":\"${CLAUDE_PROJECT:-unknown}\",\"session_id\":\"${CLAUDE_SESSION_ID:-unknown}\",\"tool_name\":\"${CLAUDE_TOOL_NAME:-unknown}\",\"phase\":\"pre\",\"estimated_tokens\":500}" \
  > /dev/null 2>&1 || true
