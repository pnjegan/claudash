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
