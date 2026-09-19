[<- Back to BACKUP](../README.md)

# Store cleanup — what exists and what does not

Which deletions this branch performs, and the sweeps it advertises but does not implement.

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

---

[<- Back to BACKUP](../README.md)
