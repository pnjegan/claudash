# Security

## Current security posture (personal use)

Claudash is designed for single-user personal deployment.

| Control | Status | Notes |
|---|---|---|
| Dashboard authentication | ✅ Done | HMAC timing-safe key comparison |
| CSRF protection | ✅ Done | Origin checks on all write endpoints |
| Sensitive data scrubbing | ✅ Done | raw_response stripped before API responses |
| Auto-update on launch | ✅ Removed | No silent code updates |
| Process isolation | ✅ Done | PID lock prevents duplicate processes |
| DB file permissions | ✅ Done | 0600 on Unix (owner-only read) |
| Network exposure | ✅ Localhost only | Binds to 127.0.0.1, not 0.0.0.0 |
| HTTPS | ❌ Not implemented | Localhost only — SSH tunnel for remote |
| Secrets encryption at rest | ❌ Not implemented | API keys in plaintext SQLite |
| Multi-user auth | ❌ Not implemented | Single shared dashboard key |
| Audit trail | ❌ Not implemented | No per-action logging |

## Known limitations

**For personal use on a developer machine:** the current security posture is acceptable.

**Not recommended for:**
- Team deployments without additional controls
- Cloud/VPS exposure without HTTPS and proper auth
- Storing credentials you cannot rotate

## Reporting a vulnerability

Open a GitHub issue with label `security`.
For sensitive reports, email the repository owner directly via GitHub.

## What data Claudash stores

- Session token counts (not conversation content)
- Tool call types and counts per session
- Cost calculations
- Dashboard authentication key (random, generated on init)
- API key for fix generation (only if configured)
- claude.ai session cookie (only if browser tracking enabled)

## What Claudash does NOT store

- Conversation content or message text
- File contents from your projects
- Personal identification information
- Any data from outside your local machine
