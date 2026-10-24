[<- Back to BACKUP](../README.md)

# The .backup/ store

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
├── running/             # One <lane>.json per lane in flight, removed when it ends (lazy)
└── drive_tracker.json   # Drive sync dedup tracker (lazy)
```

On `register`, only `snapshots/` and `logs/` are created eagerly (plus
`config.json` and the project's `.backupignore`). The rest are created lazily on
first use (`handlers/project/setup.py`): `timestamps.json`, `changelog.json`
and `versioned/` appear with the first `versioned` run.

**`timestamps.json` is not a record of when backups ran.** It maps each relative
path to the mtime the snapshot lane last copied (`handlers/state/timestamps.py`),
which is how the snapshot quick-check decides "nothing changed". A run with a
failed copy leaves the map as it was. When a lane last ran is read from
`changelog.json`.

**Shared namespace:** `.backup/` is NOT exclusive to @backup. Other writers use it too:
- **@backup** — snapshot/versioned stores at a registered project root
- **@flow** — closed plans archived to `<repo-root>/.backup/processed_plans/` for vectorization by @memory

The root `.gitignore` covers them all with a single `.backup/` entry.

---

[<- Back to BACKUP](../README.md)
