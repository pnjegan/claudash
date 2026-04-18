# Claudash — Session 23 State

## Current version: 3.3.0

## What's live (as of 2026-04-18)
- v3.0.0: compliance_events table, 4 insight rules
- v3.0.1: row_factory bug fix
- v3.1.0: sub-agent work classification + PID lock
- v3.2.0: truth-first sub-agent intelligence
  - Classifier hallucination fix (turns_per_tool guard)
  - prompt_quality column + rule 21 unbounded_subagent_prompt
  - detect_subagent_file_redundancy() (rule deferred)
- v3.3.0: backup/restore CLI + bug-hunt fixes
  - cli.py backup: hot DB backup + JSON export, 24-slot retention
  - cli.py restore: safe stop/verify/restart cycle
  - README: Backup and Recovery section
  - M04 fix: backup default = /root/backups/claudash/ (rclone-synced)
  - M05 fix: SIGTERM handler cleans pidfile
  - M06 fix: PM2 docs removed, PID lock docs added

## Real data (snapshot 2026-04-18)
- 74 distinct main sessions / 23,023 turn-rows
- 35 sub-agent session_ids (147 JSONL files — collapse deferred)
- Active insights: 53 (7 are unbounded_subagent_prompt from v3.2)
- 9 fixes tracked: 4 measuring-improving, 2 worsened (#11, #14), 1 just-measured (#12, insufficient_data but trending worse)

## Open bugs from v3.2 hunt (deferred to later sessions)

### Needs manual review (not auto-fixable)
- **M01 fix#11** (Tidify repeated_reads, verdict=worsened) — CLAUDE.md trim+split is degrading the metric. Review the diff before revert.
- **M02 fix#14** (Tidify cost_outlier, verdict=worsened) — AI-generated rule is degrading the metric. Read the generated text.
- **M03 fix#12** (WikiLoop repeated_reads) — just measured, verdict=insufficient_data (1 day / 0 post-fix sessions), raw trend +40% events. Revisit after 7 days.

### Deferred design / future schema
- **H01 sub-agent session_id collapse** — 147 JSONL files → 35 DB rows. Fix requires using `agent-<hash>` from filename as session_id. `detect_subagent_file_redundancy()` is pre-wired and will light up when this lands.
- **L01 insights.severity** — currently in detail_json. Future column addition.
- **L02 ~30 genuinely dead functions** (after filtering test_* false positives). Per-function review needed.

## Known fragile areas
- SIGKILL of dashboard leaves stale /tmp/claudash.pid content (harmless — kernel releases flock; next start overwrites). Only SIGTERM is handled (v3.3 fix).
- Pre-existing cron writes `claudash-db-{hourly,daily}-*.db` + `latest.json` symlinks to /root/backups/claudash/. Our cli.py backup uses different filename pattern (`claudash-YYYYMMDD_HH.db`). They cohabit; retention regex only touches our pattern.

## Next session priorities
1. **Manual review of fix#11 and fix#14** — what went wrong? Revert criteria?
2. **JIT skill loading** — highest-value leak pattern not yet implemented (noted in v3.2 audit).
3. **VPS system updates** — 36 apt packages upgradable, security patches.
4. **cli.py compliance --score** command (deferred from v3.0).
5. After 7 days: re-measure fix#12 WikiLoop; decide revert/keep based on verdict.
6. Sub-agent session_id redesign (H01) — if per-sub-agent tracking becomes high-value.

## Startup command
```
nohup python3 cli.py dashboard --no-browser --skip-init > logs/server.log 2>&1 &
```

## PID file
`/tmp/claudash.pid` — flock-guarded. atexit + SIGTERM both clean it (v3.3).
SIGKILL still leaks (kernel-limited — file content stale but flock released).

## Backup path
`/root/backups/claudash/` — shared with pre-existing cron + rclone-to-Drive.
Override via `CLAUDASH_BACKUP_DIR` env var or `--output DIR` flag.
