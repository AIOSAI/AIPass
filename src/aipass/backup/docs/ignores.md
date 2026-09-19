[<- Back to BACKUP](../README.md)

# Ignore rules — seed, floor, runtime

Three layers decide what gets copied. This page is the whole rule set, including the built-in `*.tmp` floor.

Three layers — seed, built-in floor, runtime:

1. **`templates/backupignore.template`** — the **seed**. Read by `setup._build_backupignore()` and written into a new project's `.backupignore` at `register` time. Never consulted at backup time. If this file is missing, registration raises — an empty seed would back up everything and crash the machine.
2. **`BUILTIN_IGNORE_PATTERNS`** in `handlers/ignore/patterns.py` — the **built-in floor**, today exactly one rule: `*.tmp`. `load_spec()` puts it ahead of the project's own lines on every run, so it reaches every project, including every `.backupignore` seeded before the rule existed.
3. **`.backupignore`** — the **runtime source of truth**. `load_spec()` reads it on every backup; the seed template is not applied. True pathspec/gitwildmatch semantics: `#` comments, `!` negation, trailing `/` for dirs, last-match-wins.

The floor is not a fallback for the seed. An empty or missing `.backupignore` still means back up everything except `*.tmp` (`.venv`, `node_modules`, `.git` included), which can crash the machine. The seed IS the safety mechanism. Keep the template sane.

### Why `*.tmp` is built in (DPLAN-0338)

The fleet's json service writes through a sibling staging temp (`.<pid>_<n>.tmp`,
older era `tmpXXXX.tmp`) inside `*_json` folders and renames it over the real
file. A writer killed mid-write leaves the temp behind. The real json is intact
either way, so a temp is never anyone's work, and backing one up only copies
litter. The owner asked for it on 2026-09-11: backup needs to ignore temporary files.

- **One rule, one place.** `load_spec()` is the only ignore source for every lane: `snapshot`, `versioned`, `all` (one shared scan) and `drive_sync` (which re-filters the versioned store through it before uploading). `DIFF_IGNORE_PATTERNS` in `handlers/diff/generator.py` decides only which files get a diff, never which files get copied, so it is not a copy rule.
- **Why not the seed?** The seed reaches only projects registered after the edit, and `.backupignore` is never overwritten. AIPass's own `/.backupignore` (hand-maintained) does not name `*.tmp`, and that store is where the temps piled up.
- **Overridable.** The floor goes first, so a project that genuinely keeps `.tmp` files re-includes them with `!*.tmp` in its own `.backupignore` (last match wins). A `whitelist` entry in `.backup/config.json` also overrides it, as it overrides any ignore.
- **Scope of the match.** gitwildmatch `*.tmp` matches at any depth and also matches a *directory* named `*.tmp`, which drops that directory's contents too. Near-misses such as `notes.tmpl`, `tmp.json`, `state.tmp.json` or `tmp/data.json` are not matched (pinned in `tests/test_ignore_pathspec.py`).

Measured 2026-09-11 on a scratch copy of `src/aipass/prax/prax_json` (599 files: 452 temps, 145 json, 2 others), outside the repo:

| Run | Snapshot store | Versioned store |
|---|---|---|
| Before the rule | 452 `*.tmp`, 145 json | 904 `*.tmp` files (452 × current + baseline), 290 json |
| After the rule, fresh project | 0 `*.tmp`, 145 json | 0 `*.tmp`, 290 json |

Re-running the *before* project after the rule still left its 452 old copies in `snapshots/`: the rule stops new copies, it does not remove old ones (see [store cleanup](store_cleanup.md)).

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

[<- Back to BACKUP](../README.md)
