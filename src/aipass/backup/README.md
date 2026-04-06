[< Back to AIPass](../../../README.md)

# BACKUP

**Purpose:** Multi-mode backup with Google Drive integration
**Module:** `aipass.backup`
**Created:** 2026-03-07
**Citizen Class:** builder
**Last Updated:** 2026-03-28

---

## Overview

Builder citizen — full 3-layer architecture with identity and memory.

Provides automated file protection through snapshot backups, versioned backups,
and Google Drive synchronization. The entry point routes commands to two
specialized modules: `backup_core` and `google_drive_sync`.

---

## Architecture

```
backup/
├── __init__.py
├── README.md
├── apps/
│   ├── backup.py                # Entry point (CLI) — drone @backup
│   ├── modules/
│   │   ├── backup_core.py       # Core backup operations (snapshot, versioned)
│   │   └── google_drive_sync.py # Google Drive sync orchestration
│   ├── handlers/
│   │   ├── config/
│   │   │   └── config_handler.py        # Configuration management
│   │   ├── diff/
│   │   │   └── diff_generator.py        # Diff generation between backups
│   │   ├── json/
│   │   │   ├── backup_info_handler.py   # Backup info JSON read/write
│   │   │   ├── backup_metadata_builder.py # Metadata construction
│   │   │   ├── changelog_handler.py     # Changelog JSON management
│   │   │   ├── drive_sync_json.py       # Drive sync state tracking
│   │   │   ├── json_handler.py          # Generic JSON utilities
│   │   │   └── statistics_handler.py    # Backup statistics
│   │   ├── models/
│   │   │   └── backup_models.py         # Data models for backup objects
│   │   ├── operations/
│   │   │   ├── drive_sync_client.py     # Google Drive API client
│   │   │   ├── drive_sync_ops.py        # Drive sync implementation
│   │   │   ├── file_cleanup.py          # Old backup cleanup
│   │   │   ├── file_operations.py       # File copy/move operations
│   │   │   ├── file_scanner.py          # File discovery and filtering
│   │   │   └── path_builder.py          # Backup path construction
│   │   ├── reporting/
│   │   │   └── report_formatter.py      # Backup report formatting
│   │   └── utils/
│   │       ├── backup_timestamps.py     # Timestamp utilities
│   │       └── system_utils.py          # System-level utilities
│   └── json_templates/          # JSON template files
├── backup_json/                 # JSON tracking data
├── artifacts/                   # Backup artifacts
├── docs/                        # Documentation
├── tests/                       # Test suite
└── tools/                       # Branch verification utilities
```

---

## Commands / Usage

```bash
drone @backup                              # Introspection — list discovered modules
drone @backup --help                       # Show full help
drone @backup --version                    # Show version
drone @backup --all                        # Full backup cycle: snapshot -> versioned -> drive-sync
drone @backup snapshot                     # Create a system snapshot backup
drone @backup versioned                    # Create a versioned backup
drone @backup drive-test                   # Test Google Drive connectivity
drone @backup drive-sync                   # Sync backups to Google Drive
drone @backup drive-sync --test            # Run a small test sync to verify integration
drone @backup drive-stats                  # Show Drive file tracker statistics
drone @backup drive-clear-tracker          # Clear Drive file tracker cache
```

**Options:**

| Flag | Description |
|------|-------------|
| `--verbose`, `-v` | Extra diagnostic output |
| `--dry-run` | Preview what would happen, execute nothing |
| `--note NOTE` | Add a backup note/description |
| `--project NAME` | Project name for Drive sync (default: AIPass) |
| `--force` | Force sync all files (ignore change tracker) |
| `--limit N` | Limit drive-sync to first N files |

---

## Integration Points

### Depends On
- `rich` — Console output and formatting
- Python stdlib (`sys`, `argparse`, `logging`, `pathlib`)

### Provides To
- All modules — automated file protection, snapshot and versioned backups
- Google Drive — cloud backup synchronization
- Other branches — backup artifacts via `backup_json/` and `artifacts/`

---

## Modules

| Module | Purpose |
|--------|---------|
| `backup_core` | Core backup operations — snapshot and versioned backup creation |
| `google_drive_sync` | Google Drive synchronization — upload, track, and manage cloud backups |

---

## Identity

- **Passport:** `.trinity/passport.json`
- **Session History:** `.trinity/local.json`
- **Observations:** `.trinity/observations.json`
- **Branch Prompt:** `.aipass/branch_system_prompt.md`

---
[< Back to AIPass](../../../README.md)
