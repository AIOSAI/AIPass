# The .backup/ store

[<- Back to BACKUP](../README.md)

What a registered project gets, what is created when, and who else writes into the same directory.

Each registered project gets a `.backup/` directory at its root:

```
.backup/
├── config.json          # Project backup configuration
├── snapshots/           # Full mirror copies (eager — created on register)
├── versioned/           # Incremental timestamped backups (lazy)
├── logs/                # Operation logs (eager — created on register)
├── timestamps.json      # Per-file mtime index for change detection (lazy)
├── changelog.json       # Change history (lazy)
└── drive_tracker.json   # Drive sync dedup tracker (lazy)
```

On `register`, only `snapshots/` and `logs/` are created eagerly (plus
`config.json` and the project's `.backupignore`). The rest are created lazily on
first use. Verified live 2026-09-05 by registering a scratch project: the eager
set was exactly `config.json`, `snapshots/`, `logs/`; `timestamps.json`,
`changelog.json` and `versioned/` appeared only after the first `versioned` run.

**`timestamps.json` is not a record of when backups ran.** It maps each relative
path to the mtime the versioned engine last saw (`handlers/state/timestamps.py`),
which is how "changed since last run" is decided. The *when-did-a-backup-run*
clock is a separate, branch-global file.

**Shared namespace:** `.backup/` is NOT exclusive to @backup. Three writers use it:
- **@backup** — snapshot/versioned stores at a registered project root
- **@memory** — rollover safety copies (`rollover_backup_*.json`) written to `<branch>/.backup/` during memory overflow
- **@flow** — closed plans archived to `<repo-root>/.backup/processed_plans/` for vectorization by @memory

The root `.gitignore` covers all three with a single `.backup/` entry.

---

[<- Back to BACKUP](../README.md)
