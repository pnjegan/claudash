# Claudash Hooks Integration

Add Claudash to your Claude Code hooks so it automatically
scans after every session.

## Setup

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claudash/tools/hooks/post-session.sh"
          }
        ]
      }
    ]
  }
}
```

## What it does

After every tool use, Claudash scans for new sessions.
Your dashboard stays up to date automatically.
No manual scanning needed.

## Configuration

Environment variables the hook reads:

- `CLAUDASH_DIR` — path to Claudash install (default: `$HOME/.claudash`)
- `CLAUDASH_URL` — dashboard URL (default: `http://localhost:8080`)

---

# Claudash hooks — real-time cost meter (v2-F6)

## What it does

Shows a **live cost ticker** in the Claudash dashboard while Claude Code
is running. Detects floundering in real-time (same tool 3× in a row)
and pushes a red warning into Claudash's MCP warning queue.

## Install

Add to `~/.claude/settings.json` (merge with any existing `hooks` block):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash /root/projects/jk-usage-dashboard/hooks/pre_tool_use.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash /root/projects/jk-usage-dashboard/hooks/post_tool_use.sh"
          }
        ]
      }
    ]
  }
}
```

If installed via `npx claudash`, use `~/.claudash/hooks/pre_tool_use.sh`
and `~/.claudash/hooks/post_tool_use.sh`.

## Cost of the hooks

Zero. Fire-and-forget `curl` — adds <1 ms per tool call. If Claudash
is not running, the hooks silently no-op (`|| true`).

## Security

Hooks POST to `127.0.0.1:8080` only. No API key required —
localhost binding is the security boundary. The endpoint writes only
to an in-memory live-session dict and (on floundering) to
`mcp_warnings`; no sensitive data is read.

## Environment variables the hook reads

- `CLAUDE_PROJECT` — project name (exposed by Claude Code)
- `CLAUDE_SESSION_ID` — current session id
- `CLAUDE_TOOL_NAME` — name of the tool being called
- `CLAUDE_OUTPUT_TOKENS` — actual output tokens from the tool
  (post-hook only; defaults to 0)
- `CLAUDE_TOOL_EXIT_CODE` — tool exit code (post-hook only)
