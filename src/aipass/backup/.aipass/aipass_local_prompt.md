# BACKUP Branch-Local Context

## Role
Automated file protection system. Multi-mode backup with Google Drive integration.

## What Backup Does
Exactly 3 things:
1. **Snapshot** — Full copy backup (overwrites previous). Fast, good for pre-change safety.
2. **Versioned** — Timestamped backup with incremental copies and unified diffs. Tracks file history.
3. **Google Drive sync** — Uploads snapshot to Drive via OAuth2 (auth delegated to @api).

## Key Commands
```
drone @backup snapshot           # Full snapshot backup
drone @backup snapshot --dry-run # Preview what would be copied
drone @backup versioned          # Versioned backup with diffs
drone @backup versioned --dry-run
drone @backup all                # Full cycle: snapshot + versioned + drive-sync
drone @backup all --dry-run      # Preview all phases (skips drive-sync)
drone @backup drive-sync         # Sync snapshot to Google Drive
drone @backup drive-sync --dry-run  # Preview what would upload
drone @backup drive-test         # Test Drive connectivity
drone @backup drive-stats        # File tracker statistics
drone @backup drive-clear-tracker --force  # Clear tracker (requires --force)
```

## Architecture
Clean 3-layer pattern: CLI -> modules -> handlers.

```
apps/
  backup.py              # Entry point, CLI routing, 'all' orchestration
  modules/
    backup_core.py       # Snapshot + versioned engine (BackupEngine class)
    google_drive_sync.py # Drive sync orchestration, CLI for drive commands
  handlers/
    config/              # Ignore patterns, whitelist, config
    json/                # JSON persistence, changelog, metadata, drive tracker
    models/              # BackupResult dataclass
    operations/          # File scanner, copier, cleanup, Drive client, diff generator
    reporting/           # CLI output formatting
    utils/               # System utils, timestamps
```

## Critical Files
- `apps/json_templates/ignore_patterns.json` — Patterns + whitelist. Branch is non-functional without this.
- `backup_json/` — Runtime JSON state (timestamps, tracker, logs). Self-healing on corruption.
- `backups/` — Actual backup data. NOT in git. Can be purged for fresh start.

## Safety Rules
- **NEVER run bulk file operations without Patrick's OK.** Use `--dry-run` first.
- Source is `Path.home()`, controlled by whitelist (Projects, Desktop) + 100MB file cap.
- `tools/pattern_scan.py` — Diagnostic to audit what passes ignore filters. Read-only.
- Versioned backup can be slow (2700+ files). Always test with `--dry-run`.

## Integration Points
- **@api** — Google Drive auth via `aipass.api.apps.modules.google_client`
- **@prax** — Logging via `from aipass.prax import logger`
- **@seedgo** — Compliance auditing: `drone @seedgo audit aipass @backup`
- **@drone** — Command routing. `all`, `snapshot`, `versioned` run in interactive mode (no timeout).

## Current Stats
- 260 tests, 0 failures
- Seedgo 99%
- 2 active modules, ~23 handler files across 6 domains
