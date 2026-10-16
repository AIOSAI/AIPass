[<- Back to BACKUP](../README.md)

# Store cleanup — what exists and what does not

Which deletions this branch performs, what triggers each, and what it still advertises but does not do.

Two lanes delete from a store, each on its own trigger:

| Lane | Removes | Trigger |
|---|---|---|
| Mirror cleanup, `handlers/cleanup/mirror.py` | `snapshots/` files | the source file no longer exists; runs inside every snapshot |
| `prune`, `modules/prune.py` + `handlers/cleanup/prune.py` | `snapshots/` files and `versioned/` file-folders | the ignore spec now matches the project path; runs only when called |

### Mirror cleanup

Removes a snapshot file **whose source no longer exists**. That is its only
trigger: a file that is still in the source tree keeps its snapshot copy even
when it became ignored, because `_should_delete()` only asks whether the source
exists. (`cleanup_deleted_files()` used to accept a `should_ignore` callback it
never called; the parameter was dropped 2026-09-27.) It never touches `versioned/`.

### `prune` — copies the ignore spec now matches (2026-10-16, DPLAN-0411)

```
drone @backup prune <project_root|@name>            # list, delete nothing
drone @backup prune <project_root|@name> --apply    # delete what the list names
```

A path is pruned by the backup's own filter rule (`scan/filter.py`): `load_spec()`
(the project's `.backupignore` behind the built-in floor, `BUILTIN_IGNORE_PATTERNS`)
matches its project-relative path, and the project's `whitelist` does not keep it.
A whitelisted path is one the next run copies straight back, so it is never listed.

- `snapshots/` — one candidate per **file**, `snapshots/<rel_path>`.
- `versioned/` — one candidate per **file-folder**: the folder `build_versioned_file_path()`
  makes for one source file, holding the current copy, its baseline and its
  `<name>_diffs/`. A file-folder under `root/` is read as a root-level file; the
  layout gives a project file `root/<name>` the same folder and cannot tell the two apart.

The listing prints, per store, one row per top-level directory (count and bytes;
root-level files under `(root files)`), then the grand total. Without `--apply`
nothing is deleted and the last line says so. With `--apply` each listed path is
removed, one `prune_removed` row per path in `logs/operations.jsonl`, directories
left empty are removed, and the last line names what was removed and freed. A
path that cannot be removed is an error on stderr and the command exits non-zero;
it is never counted as removed.

`prune` never touches the remote copy. Drive entries for pruned files are not
removed from Drive; that remains the owner's by hand.

### What is still not implemented

**`max_versions` does nothing.** `.backup/config.json` carries a `max_versions`
key (default `10`), `register` writes it, and `status` prints it as "Max
versions" — but no code reads it. Nothing prunes old versions of a file that is
still backed up; `prune` removes whole file-folders of ignored paths only. Treat
`max_versions` as advertised-but-unimplemented.

The versioned store is otherwise append-only and holds two copies of every new
file (current + baseline), so it grows to roughly 2× the source.

**The `*.tmp` copies made before the rule (2026-09-11).** The AIPass store
(`/.backup/`, last snapshotted 2026-08-15) held 498 temp copies in `snapshots/`
(14,265,519 B) and 996 in `versioned/` (498 file-folders × current + baseline,
28,531,038 B), every one from a `*_json` folder: 458 prax, 36 memory, 3 trigger,
1 seedgo. None of the 498 snapshot copies still had a source.

- `snapshots/` — **pruned** with `drone rm --stale 10d .backup/snapshots`, the
  fleet's logged delete: 498 matched, 498 deleted, 0 refusals, 0 left. They
  could never be restored as anything useful, and with no source they would
  only have gone at the next AIPass snapshot.
- `versioned/` — **left in place, 996 files.** The stale sweep matches only
  files directly inside a `*_json` folder, and this store wraps each file in a
  `<name>.tmp/` folder. The plain `drone rm` lane refuses the folders
  (`Protected: path is inside sibling branch memory/`) because the store
  mirrors `src/aipass/<branch>/`. The gate is not routed around. The copies
  are inert: `drive_sync` re-filters the store through `load_spec()`, so they
  never upload. They go when a pruning lane exists.
  *(2026-10-16: `prune` is that lane. `*.tmp` is in the built-in floor, so
  `prune` lists these file-folders; they stay until `--apply` is run.)*

---

[<- Back to BACKUP](../README.md)
