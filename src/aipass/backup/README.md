# BACKUP

**Purpose:** Standalone backup system — project-owned, local-first backups for any directory
**Module:** `aipass.backup`
**Version:** 1.0.0
**Created:** 2026-04-16
**Last Updated:** 2026-08-13

---

## Overview

### What I Do

- Back up any project directory on the system (not just AIPass projects)
- Each project owns its backup config (`.backup/`) and ignore patterns (`.backupignore`)
- Snapshot mode: full mirror copy
- Versioned mode: incremental timestamped backups with automatic pruning
- Project registry for name-based lookups (`backup snapshot @AIPass`)

### How I Work
- **Entry Point:** `apps/backup.py`
- **Pattern:** Auto-discovers and routes to modules

---

## Architecture

```
apps/
├── backup.py              # Entry point (auto-discovery router)
├── modules/
│   ├── all.py             # Snapshot + versioned orchestration
│   ├── display.py         # Rich CLI rendering (used by snapshot/versioned/all)
│   ├── drive_clear.py     # Clears the LOCAL Drive sync tracker
│   ├── drive_stats.py     # Drive tracker statistics
│   ├── drive_sync.py      # Uploads the backup store to Google Drive
│   ├── drive_check.py     # Drive connectivity check via @api gateway
│   ├── register.py        # Project registration + @name resolution
│   ├── restore.py         # Version discovery + file restoration
│   ├── settings.py        # Settings UI (stub)
│   ├── share.py           # Single-file Drive upload + share link
│   ├── snapshot.py        # Full mirror backup
│   ├── status.py          # Backup status display
│   └── versioned.py       # Incremental timestamped backup
└── handlers/
    ├── copy/              # File copying (snapshot + versioned)
    ├── diff/              # Diff generation + restore from the versioned store
    ├── drive/             # Google Drive handlers (auth, upload, tracker, share)
    ├── ignore/            # .backupignore patterns + whitelist
    ├── json/              # JSON persistence, atomic writes, ops log
    ├── path/              # Backup path building + caller-CWD resolution
    ├── project/           # Config, registry, setup (.backup/)
    ├── report/            # Result formatting
    ├── scan/              # Directory walking + filtering
    ├── state/             # Changelog, metadata, timestamps
    └── ui/                # Settings window (archived — see ui/.archive/)
```

---

## Commands

```
backup register <path> [--name <name>]   # Register a project for backup
backup snapshot <path|@name>             # Full mirror backup
backup versioned <path|@name>            # Incremental timestamped backup
backup all <path|@name>                  # Snapshot + versioned + drive
backup status <path|@name>              # Show backup info and history
backup restore <path|@name> list <file>  # List available versions of a file
backup restore <path|@name> file <f> <o> # Restore a file version to output path
backup settings <path|@name>             # NOT IMPLEMENTED — settings UI deferred
backup drive_sync <path|@name>           # Upload the backup store to Google Drive
backup drive_check <path|@name>          # Drive connectivity check
backup drive_stats <path|@name>          # Drive tracker statistics
backup drive_clear <path|@name> --force  # Clear the LOCAL tracker (remote files untouched)
backup share <file> [--public]           # Upload one file to Drive, return share link
```

All 12 commands are auto-discovered by the entry point router.

**A `--help` anywhere in the arguments prints help and runs nothing** — `drone
@backup snapshot @myapp --help` is a safe probe, not a backup.

**Drive commands need credentials.** They authenticate through the @api gateway;
without Google API libraries or credentials they fail loudly rather than
pretending to sync. `drive_clear` only clears the local dedup tracker — it never
deletes anything already uploaded to Drive.

**Relative paths resolve where you are.** Backup runs as an installed entry
point, so its process CWD is its own branch directory. Drone exports
`AIPASS_CALLER_CWD`; `handlers/path/caller.py` re-anchors every user-supplied
relative path to it, so `drone @backup share docs/notes.md` means the caller's
`docs/notes.md`. Absolute paths are untouched.

---

## Quick Start

```bash
# Register a project for backup
drone @backup register /path/to/project --name myapp

# Full mirror snapshot
drone @backup snapshot @myapp

# Incremental timestamped backup
drone @backup versioned @myapp

# Check backup status
drone @backup status @myapp

# List available versions of a file
drone @backup restore @myapp list src/main.py
```

---

## `.backup/` Store Structure

Each registered project gets a `.backup/` directory at its root:

```
.backup/
├── config.json          # Project backup configuration
├── snapshots/           # Full mirror copies (eager — created on register)
├── versioned/           # Incremental timestamped backups (lazy)
├── logs/                # Operation logs (eager — created on register)
├── timestamps.json      # Backup timing metadata (lazy)
├── changelog.json       # Change history (lazy)
└── drive_tracker.json   # Drive sync dedup tracker (lazy)
```

On `register`, only `snapshots/` and `logs/` are created eagerly (plus `config.json`). The rest are created lazily on first use.

**Shared namespace:** `.backup/` is NOT exclusive to @backup. Three writers use it:
- **@backup** — snapshot/versioned stores at a registered project root
- **@memory** — rollover safety copies (`rollover_backup_*.json`) written to `<branch>/.backup/` during memory overflow
- **@flow** — closed plans archived to `<repo-root>/.backup/processed_plans/` for vectorization by @memory

The root `.gitignore` covers all three with a single `.backup/` entry.

---

## How Ignores Work

Two layers — seed and runtime:

1. **`templates/backupignore.template`** — the **seed**. Read by `setup._build_backupignore()` and written into a new project's `.backupignore` at `register` time. Never consulted at backup time. If this file is missing, registration raises — an empty seed would back up everything and crash the machine.
2. **`.backupignore`** — the **runtime source of truth**. `load_spec()` reads it on every backup; the seed template is not applied. True pathspec/gitwildmatch semantics: `#` comments, `!` negation, trailing `/` for dirs, last-match-wins.

There is no static fallback. The seed IS the safety mechanism — an empty or missing `.backupignore` means back up everything (`.venv`, `node_modules`, `.git`), which can crash the machine. Keep the template sane.

- To change defaults for **new** projects → edit `templates/backupignore.template`
- To change ignores for an **existing** project → edit its `.backupignore`

The repo-root `/.backupignore` ships intentionally as the curated default so users don't snapshot junk.

**A miss in the seed is expensive.** The template covers `build/`, `dist/`, `target/`, `node_modules/`, `.venv/` and friends precisely because an uncovered build-artifact tree is indistinguishable from real source to the walker. `target/` was added on 2026-08-20 after a Rust `src-tauri/target` tree (33,093 files / 18GB) was walked and copied for 7.5h, writing 50GB into the stores. Patterns are unanchored on purpose: baud's tree was `app/src-tauri/target`, so an anchored `/target/` would have missed it.

---

## Run Ceiling — the runaway guard

An ignore miss cannot be caught by better ignore patterns alone; the next unfamiliar build system will have a directory nobody has listed yet. So every run **measures the filtered set before copying anything** and refuses loudly when it breaches a ceiling:

| Config key | Default | Meaning |
|---|---|---|
| `max_backup_files` | `25000` | Maximum files in one run |
| `max_backup_size_gb` | `10` | Maximum total source bytes in one run |

Set either to `0` to disable it for a project that genuinely is that large.

A refusal names the directories that caused it, at a depth you can paste straight into `.backupignore`:

```
✗ Backup refused — 33,093 files exceeds the 25,000-file ceiling
  Largest directories in this run:
    app/src-tauri/target  —  33,093 files
  Add the build-artifact directories above to .backupignore, then re-run.
  If the project really is this large, raise 'max_backup_files' in .backup/config.json (0 disables).
```

The guard sits in `snapshot`, `versioned` **and** `all`. It is in `all` as well as the sub-modules because `run_snapshot` does its own full walk — letting a breach fall through means walking a runaway tree twice before refusing it.

**Known gap:** the ceiling stops a runaway *before* it happens. It does not clean up a store that a previous run already filled — see "Store Cleanup" below.

---

## Store Cleanup — what exists and what does not

Mirror cleanup (`handlers/cleanup/mirror.py`) removes snapshot files **whose source no longer exists**. That is its only trigger.

There is **no lane** that removes files which are now *ignored* but still present in the source tree. A directory added to `.backupignore` after a backup stays in `snapshots/` and `versioned/` indefinitely:

- `snapshots/` — `_should_delete()` keeps any file whose source still exists, and an ignored-but-present `target/` still exists. `cleanup_deleted_files()` accepts a `should_ignore` callback and **never calls it** — the ignore-aware sweep is unimplemented, not merely unused.
- `versioned/` — has no cleanup path at all. The store is append-only by design, and holds two copies of every new file (current + baseline), so it grows to roughly 2× the source.

Removing a now-ignored tree from a store is currently a manual `rm -rf` of the corresponding path under `.backup/`.

---

## Integration Points

### Depends On
- @prax — logging
- @cli — Rich console output

### Provides To
- Any project on the PC — backups are project-owned (`.backup/` in target root)
