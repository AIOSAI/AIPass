# BACKUP

**Purpose:** Standalone backup system — project-owned, local-first backups for any directory
**Module:** `aipass.backup`
**Version:** 1.0.0
**Created:** 2026-04-16
**Last Updated:** 2026-08-25

---

## Overview

### What I Do

- Back up any project directory on the system (not just AIPass projects)
- Each project owns its backup config (`.backup/`) and ignore patterns (`.backupignore`)
- Snapshot mode: full mirror copy
- Versioned mode: incremental timestamped backups (append-only — there is no pruning; see "Store Cleanup")
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
    ├── cleanup/           # Mirror cleanup — removes snapshot files whose source is gone
    ├── copy/              # File copying (snapshot + versioned)
    ├── diff/              # Diff generation + restore from the versioned store
    ├── drive/             # Google Drive handlers (auth, upload, tracker, share)
    ├── ignore/            # .backupignore patterns + whitelist
    ├── json/              # JSON persistence, atomic writes, ops log
    ├── path/              # Backup path building, caller-CWD resolution,
    │                      #   and module_paths.py (the safe-resolve helper)
    ├── project/           # Config, registry, setup (.backup/)
    ├── report/            # Result formatting
    ├── scan/              # Directory walking + filtering + the run ceiling
    ├── state/             # Changelog, metadata, timestamps
    └── ui/                # Settings window (archived — see ui/.archive/)
```

`apps/integrations/` and `apps/plugins/` also exist on disk but are empty
scaffolds (a README and an `__init__.py`, no code) — they are left out of the
tree above deliberately, not by oversight.

---

## Commands

```
backup register <path> [--name <name>]   # Register a project for backup
backup snapshot <path|@name>             # Full mirror backup
backup versioned <path|@name>            # Incremental timestamped backup
backup all <path|@name>                  # Snapshot + versioned + drive sync
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

The router auto-discovers every file in `apps/modules/` that exposes a
`handle_command()`. That is 13 modules: the 12 verbs above, plus `display`,
which is a rendering helper rather than a backup verb — it answers only to its
own name (`drone @backup display` prints its introspection and does nothing
else) and is intentionally undocumented as a command.

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
It is hand-maintained, not generated from the seed, and it has **drifted**: as of
2026-08-25 it is missing `target/` and `logs/`, and its header still cites the
old source (`handlers/ignore/patterns.py`) instead of
`templates/backupignore.template`. AIPass's own tree is therefore not covered
against the exact runaway class the `target/` pattern was added for.

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
- `versioned/` — has no cleanup path at all. The store is append-only, and holds two copies of every new file (current + baseline), so it grows to roughly 2× the source.

**`max_versions` does nothing.** `.backup/config.json` carries a `max_versions`
key (default `10`), `register` writes it, and `status` prints it as "Max
versions" — but no code reads it. Nothing prunes old versions. The only file
deletion anywhere in this branch is `mirror.py:59`, the vanished-source snapshot
sweep above. Treat the key as advertised-but-unimplemented until a pruning lane
exists.

Removing a now-ignored tree from a store is currently a manual `rm -rf` of the corresponding path under `.backup/`.

---

### Fabricated filenames never name the real tree (round 12)

The fence pins drive the guard by compiling `check()` under a made-up caller
filename. coverage.py records every executed code object BY FILENAME, existing
file or not -- so a fabrication that looks like a real tree file makes the
coverage *report* step exit 1 with `No source for code` while every test passes.
That is what reddened the coverage CI leg on `5bfd5b63`.

Two rules, both pinned:

- Every fabricated filename lives under `tmp_path`, outside coverage's `source`
  filter. Real-tree adjacency (is `src/aipass/memory` foreign? is a real backup
  file kin?) is asserted on `_is_kin`, which is pure and compiles nothing.
- There is exactly ONE `compile()` in the test file, and it refuses a filename
  that `abspath`s inside the source tree. `abspath`, not the literal: coverage
  resolves a relative name against the cwd at trace time, so a Windows-spelled
  literal is inert from the repo root and a minter from the branch directory.

### Kinship is spelled, not compared raw (round 5)

The handlers fence asks one question -- is this caller inside my branch? -- and
until 2026-08-31 it asked it with a raw substring test that normalised only ONE
side. On Windows `_BRANCH_ROOT` arrives from `Path` with backslashes while the
caller had just had its backslashes replaced with forward slashes, so the test
could never match: every file in this branch read as FOREIGN and the whole tree
died at the door with backup's own ACCESS DENIED message.

Both sides now go through `_spell_for_kinship()`. Case is folded only when
`os.name == "nt"` -- folding everywhere would ADMIT a foreign `/tmp/BACKUP` on a
case-sensitive filesystem, which is a wider fence, not a safer one. The guard's
own-frame skip uses the same rule for a sharper reason: if that skip misses,
`__init__.py` becomes the reported caller, is trivially kin, and the real
foreign frame beneath it is never examined.

## Path Resolution — why nothing here calls `resolve()` at import

`ntpath.realpath` reads `os.getcwd()` **unconditionally** (posixpath only does so
for relative paths), and `Path.resolve()` routes through it. So on Windows every
`resolve()` *reached at import time* is an import-time crash for a process whose
cwd has been deleted: the module cannot be imported at all. The discriminator is
**reached-at-import**, not written-at-module-scope — a `resolve()` inside a
function that the module calls while importing is just as fatal.

Every module-level path in this branch therefore goes through one helper,
`handlers/path/module_paths.py`:

- `module_file(__file__)` — `resolve()` first, so symlinks still collapse
  normally; on `OSError` it degrades to `os.path.abspath`, which is the identity
  for an already-absolute path and needs no cwd.
- `branch_root(__file__, n)` — the same, then climbs `n` levels.

The helper is **stdlib-only on purpose**. Importing `@prax` here would put the
logger's own cwd-reading construction onto the path this module exists to
protect, so its diagnostics go to `sys.stderr` — reported once per path, because
in a dead-cwd world *every* resolve fails and one line per call would bury the
real traceback.

The handlers package guard walks `sys._getframe` rather than `inspect.stack()`.
`inspect.stack()` calls `getmodule` → `getabsfile` → `os.path.realpath` on every
frame with no guard (inspect.py:1009), so it dies before the guard's own
skip-the-pseudo-frame logic is ever consulted. Reading `f_code.co_filename` off
the frame touches no filesystem at all.

Measured on 2026-08-31 by importing all 57 modules in a child interpreter under
two injections: **57/57 failed to import before the cure, 0/57 after**.
See `tests/test_dead_cwd_imports.py`, which carries an AST ban on
`inspect.stack()` — a behavioural test cannot catch its return, because the
branch that used it is unreachable from any import-shaped pin.

**Backup destinations are unaffected by all of this.** Every path under
`.backup/` is derived from the caller-supplied `project_root` (see
`handlers/path/builder.py`), never from a module-level resolve and never from
the cwd — so no backup or archive has ever been written to a location derived
from where the caller's shell happened to be standing.

---

## Integration Points

### Depends On
- @prax — logging (`logger`, `append_jsonl`)
- @cli — Rich console output (`console`, `error`, `header`, `success`, `warning`)
- @api — Google Drive auth + retry, via `google_client` (Drive commands only)

### Provides To
- Any project on the PC — backups are project-owned (`.backup/` in target root)
