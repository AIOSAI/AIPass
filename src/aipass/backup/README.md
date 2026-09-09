# BACKUP

**Purpose:** Standalone backup system — project-owned, local-first backups for any directory
**Module:** `aipass.backup`
**Version:** 1.0.0
**Created:** 2026-04-16
**Last Updated:** 2026-09-05

> Every number and command in this file was re-measured against the tree on
> **2026-09-05** (FPLAN-0490). Anything that could not be verified tonight is
> marked *unverified* where it is claimed, not left standing green.

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
    ├── audit/             # backup's own operation trail (JSONL -> logs/operations.jsonl)
    ├── cleanup/           # Mirror cleanup — removes snapshot files whose source is gone
    ├── copy/              # File copying (snapshot + versioned)
    ├── diff/              # Diff generation + restore from the versioned store
    ├── drive/             # Google Drive handlers (auth, upload, tracker, share)
    ├── ignore/            # .backupignore patterns + whitelist
    ├── json/              # The fleet's json shim — BINDS @prax's service, identical
    │                      #   in every branch (DPLAN-0325). sha256 3456b766…,
    │                      #   1724 B, mode 664 — re-verified 2026-09-05
    ├── path/              # Backup path building, caller-CWD resolution,
    │                      #   and module_paths.py (the safe-resolve helper)
    ├── project/           # Config, registry, setup (.backup/)
    ├── report/            # Result formatting
    ├── scan/              # Directory walking + filtering + the run ceiling
    ├── state/             # Changelog, metadata, timestamps
    └── ui/                # Settings window (archived — see ui/.archive/)
```

`apps/integrations/` and `apps/plugins/` also exist on disk but are empty
scaffolds with no code — `plugins/` holds a `README.md` and an `__init__.py`,
`integrations/` holds only a `README.md`. They are left out of the tree above
deliberately, not by oversight.

---

## Commands

```
backup register <path> [--name <name>]   # Register a project for backup
backup snapshot <path|@name>             # Full mirror backup
backup versioned <path|@name>            # Incremental timestamped backup
backup all <path|@name>                  # Snapshot + versioned + drive sync
backup status <path|@name>               # Show backup info and history
backup restore <path|@name> list <name>  # List available versions of a file
backup restore <path|@name> file <name> <out>  # Restore current version to <out>
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

**`restore` takes a BARE FILENAME, not a relative path.** `restore @myapp list
main.py` works; `restore @myapp list src/main.py` always answers *No versioned
file found*, because the store is keyed by file-folder name. This is a real
limitation, not a typo in the docs: two files with the same basename in
different directories are indistinguishable to `restore`. Verified live
2026-09-05 — see "Status / Known issues", where the code side is logged as a
defect for its owner.

**Drive commands need credentials.** They authenticate through the @api gateway;
without Google API libraries or credentials they fail loudly rather than
pretending to sync. `drive_clear` only clears the local dedup tracker — it never
deletes anything already uploaded to Drive.

Verified 2026-09-05: `drive_check` authenticated through the gateway and
returned a live backup-folder ID, and `drive_stats` read the tracker. The
**upload** path (`drive_sync`, `share`) was deliberately *not* exercised — it
publishes files to a real Drive account — so it stands **unverified since
2026-08-29**, the last recorded `drive_sync` run.

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

# List available versions of a file (bare filename, not a path)
drone @backup restore @myapp list main.py
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
clock is a separate, branch-global file — see "Status / Known issues".

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

The repo-root `/.backupignore` ships intentionally as the curated default so
users don't snapshot junk. It is hand-maintained, not generated from the seed.
It had **drifted** as of 2026-08-25 (missing `target/` and `logs/`, header still
citing the old `handlers/ignore/patterns.py`); re-checked 2026-09-05, all three
are cured — `target/` at line 26, `logs/` at line 28, header citing
`templates/backupignore.template`. AIPass's own tree is now covered against the
runaway class the `target/` pattern was added for.

A project's own `.backupignore` is **generated at `register` time** by
`handlers/project/setup.py` (`if not ignore_path.exists()`), from the seed
template. It is not shipped by `init` and it is never overwritten once present.

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
versions" — but no code reads it. Re-verified 2026-09-05: the only three
mentions in the whole tree are the two defaults that write it
(`project/config.py:24`, `project/setup.py:41`) and the one line that displays
it (`modules/status.py:80`). Nothing prunes old versions.

The only deletion of a *backed-up* file anywhere in this branch is
`mirror.py:59`, the vanished-source snapshot sweep above. (There is one other
`unlink` in the tree, `state/backup_timestamps.py:61`, but it removes that
module's own temp file when an atomic write fails — it never touches a store.)
Treat `max_versions` as advertised-but-unimplemented until a pruning lane exists.

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

Measured on 2026-08-31 by importing all 57 modules then in the tree, in a child
interpreter under two injections: **57/57 failed to import before the cure, 0/57
after**. Re-measured 2026-09-05 against the tree as it now stands (60 modules,
`audit/` added since): **0/60 red in both denial worlds**.

The standing pin is `tests/test_dead_cwd_imports.py`. Note what it does and does
not do: it re-runs the two injections against **9 representative modules**
(`PROBE_MODULES`), not the whole tree — the 57 and 60 figures above are ad-hoc
sweeps, not something CI re-walks. The file also carries an AST ban on
`inspect.stack()` — a behavioural test cannot catch its return, because the
branch that used it is unreachable from any import-shaped pin.

**Backup destinations are unaffected by all of this.** Every path under
`.backup/` is derived from the caller-supplied `project_root` (see
`handlers/path/builder.py`), never from a module-level resolve and never from
the cwd — so no backup or archive has ever been written to a location derived
from where the caller's shell happened to be standing.

---

## Tests

**298 test functions across 13 files in `tests/`; pytest expands them to 371
cases.** Both numbers re-measured 2026-09-08 — the first by counting `def test_`
lines the way the seedgo readme rule counts them, the second from a full run:

```
python -m pytest src/aipass/backup/tests -q     # 371 passed
```

The drop from the 2026-09-05 figures (302 defs / 14 files / 383 cases) is one
file, not attrition: `tests/test_json_handler.py` (6 defs, 14 cases) was
archived on 2026-09-07 to `tests/.archive/`. 302 − 6 + 2 = 298 and
383 − 14 + 2 = 371, the +2 being this wave's two added units.

The gap is parametrisation, concentrated in `test_drive_pipeline.py` (71 defs)
and `test_dead_cwd_imports.py` (37 defs). Run it from the **repo root** — from
the branch directory the local `aipass/` tree shadows the installed package.

---

## Status / Known issues

Everything below was reproduced live on 2026-09-05. These are **code** defects
found during a docs verification pass; none were fixed in that pass, and each is
logged here rather than silently corrected in prose.

| # | Where | What |
|---|---|---|
| 1 | `apps/backup.py` `print_help()` | `restore` is missing from the COMMANDS block although it appears in EXAMPLES and `modules/restore.py` sets `PRIMARY_COMMAND = "restore"`. Reported by @devpulse, confirmed here. |
| 2 | `apps/modules/restore.py:56` | `_find_file_folder` tests `(candidate / filename).is_file()`, so a path-shaped argument looks for `<store>/src/main.py/src/main.py` and never matches. Only a bare basename works. Both `--help` EXAMPLES lines spell the failing form. |
| 3 | `apps/handlers/state/backup_timestamps.py:22` | `TIMESTAMPS_FILE` is a branch-global module constant, so the "Backups now:" panel (`modules/display.py:176`) reports @backup's last run **anywhere** as if it were this project's. A project registered 30 seconds earlier displayed *"Versioned: 2 mins ago · Drive sync: 7 days ago"*. Same root cause makes the file unpatchable in tests, which is why the suite still rewrites the live one. |
| 4 | `apps/backup.py` `print_help()` | `all` is described as "Run snapshot then versioned in sequence", but `modules/all.py:117` also runs `drive_sync`. The help understates what the verb does. |

**Unverified in this pass:** the Drive **upload** path (`drive_sync`, `share`).
Authentication and connectivity were verified; uploading publishes to a real
Drive account, so it was not exercised. Last recorded successful `drive_sync`:
2026-08-29.

**Known-and-by-design, documented above:** no version pruning
(`max_versions` is inert), no ignore-aware store sweep, and `versioned/` is
append-only at roughly 2× the source.

---

## Integration Points

### Depends On
Verified 2026-09-05 by reading every import in `apps/`:

- @prax — logging (`logger`, `append_jsonl`) **and** the json service, bound by
  the shim (`from aipass.prax import json_handler`)
- @cli — Rich console output (`console`, `error`, `header`, `success`, `warning`)
- @api — Google Drive auth + retry, via
  `aipass.api.apps.modules.google_client` (Drive commands only)

### Provides To
- Any project on the PC — backups are project-owned (`.backup/` in target root)
