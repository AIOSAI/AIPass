[<- Back to BACKUP](../README.md)

# Ignore rules — seed, floor, runtime

Three layers decide what gets copied. This page is the whole rule set, including the built-in `*.tmp` floor.

Three layers — seed, built-in floor, runtime:

1. **`templates/backupignore.template`** — the **seed**. Read by `setup._build_backupignore()` and written into a new project's `.backupignore` at `register` time. Never consulted at backup time. If this file is missing, registration raises — an empty seed would back up everything and crash the machine.
2. **`BUILTIN_IGNORE_PATTERNS`** in `handlers/ignore/patterns.py` — the **built-in floor**, today exactly one rule: `*.tmp`. `load_spec()` puts it ahead of the project's own lines on every run, so it reaches every project, including every `.backupignore` seeded before the rule existed.
3. **`.backupignore`** — the **runtime source of truth**. `load_spec()` reads it on every backup; the seed template is not applied. True pathspec/gitwildmatch semantics: `#` comments, `!` negation, trailing `/` for dirs, last-match-wins.

The floor is not a fallback for the seed. An empty or missing `.backupignore` still means back up everything except `*.tmp` (`.venv`, `node_modules`, `.git` included), which can crash the machine. The seed IS the safety mechanism. Keep the template sane.

### Why `*.tmp` is built in

The fleet's json service writes through a sibling staging temp (`.<pid>_<n>.tmp`,
older era `tmpXXXX.tmp`) inside `*_json` folders and renames it over the real
file. A writer killed mid-write leaves the temp behind. The real json is intact
either way, so a temp is never anyone's work, and backing one up only copies
litter.

- **One rule, one place.** `load_spec()` is the only ignore source for every lane: `snapshot`, `versioned`, `all` (one shared scan) and `drive_sync` (which re-filters the snapshot store through it before uploading). `DIFF_IGNORE_PATTERNS` in `handlers/diff/generator.py` decides only which files get a diff, never which files get copied, so it is not a copy rule.
- **Why not the seed?** The seed reaches only projects registered after the edit, and `.backupignore` is never overwritten. AIPass's own `/.backupignore` (hand-maintained) does not name `*.tmp`.
- **Overridable.** The floor goes first, so a project that genuinely keeps `.tmp` files re-includes them with `!*.tmp` in its own `.backupignore` (last match wins). A `whitelist` entry in `.backup/config.json` also overrides it, as it overrides any ignore.
- **Scope of the match.** gitwildmatch `*.tmp` matches at any depth and also matches a *directory* named `*.tmp`, which drops that directory's contents too. Near-misses such as `notes.tmpl`, `tmp.json`, `state.tmp.json` or `tmp/data.json` are not matched (pinned in `tests/test_ignore_pathspec.py`).

The rule stops new copies; it does not remove copies a store already holds (see [store cleanup](store_cleanup.md)).

- To change defaults for **new** projects → edit `templates/backupignore.template`
- To change ignores for an **existing** project → edit its `.backupignore`

The repo-root `/.backupignore` ships intentionally as the curated default so
users don't snapshot junk. It is hand-maintained, not generated from the seed, so it can drift from the
template; it carries `target/` and `logs/`, and its header names
`templates/backupignore.template` as the source of defaults.

A project's own `.backupignore` is **generated at `register` time** by
`handlers/project/setup.py` (`if not ignore_path.exists()`), from the seed
template. It is not shipped by `init` and it is never overwritten once present.

**A miss in the seed is expensive.** The template covers `build/`, `dist/`, `target/`, `node_modules/`, `.venv/` and friends precisely because an uncovered build-artifact tree is indistinguishable from real source to the walker. An uncovered Rust `src-tauri/target` tree is tens of thousands of files and many gigabytes, walked and copied as if it were source. Patterns are unanchored on purpose: a build tree such as `app/src-tauri/target` sits below the root, and an anchored `/target/` would miss it.


---

[<- Back to BACKUP](../README.md)
