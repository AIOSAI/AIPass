[<- Back to BACKUP](../README.md)

# Store cleanup — what exists and what does not

Which deletions this branch performs, what triggers each, and what it advertises but does not do.

Two lanes delete from a store, each on its own trigger:

| Lane | Removes | Trigger |
|---|---|---|
| Mirror cleanup, `handlers/cleanup/mirror.py` | `snapshots/` files | the source file no longer exists; runs inside every snapshot |
| `prune`, `modules/prune.py` + `handlers/cleanup/prune.py` | `snapshots/` files and `versioned/` file-folders | the ignore spec now matches the project path; runs only when called |

### Mirror cleanup

Removes a snapshot file **whose source no longer exists**. That is its only
trigger: a file that is still in the source tree keeps its snapshot copy even
when it became ignored, because `_should_delete()` only asks whether the source
exists. It never touches `versioned/`.

### `prune` — copies the ignore spec now matches

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
  `<name>_diffs/`. The project path is the store path with one leading
  `root/` removed (`versioned_rel_path()` in `handlers/path/builder.py`), so a root-level
  file and a project file under `root/` stay apart.

The listing prints, per store, one row per top-level directory (count and bytes;
root-level files under `(root files)`), then the grand total. Without `--apply`
nothing is deleted and the last line says so. With `--apply` each listed path is
removed, one `prune_removed` row per path in `logs/operations.jsonl`, directories
left empty are removed, and the last line names what was removed and freed. A
path that cannot be removed is an error on stderr and the command exits non-zero;
it is never counted as removed.

`prune` never touches the remote copy. Drive entries for pruned files are not
removed from Drive; that remains the owner's by hand.

### What is not implemented

**No version limit.** Nothing prunes old versions of a file that is still
backed up; `prune` removes whole file-folders of ignored paths only. A
`max_versions` key left in an older `.backup/config.json` is read by nothing.

The versioned store is otherwise append-only and holds two copies of every new
file (current + baseline), so it grows to roughly 2× the source.

**Copies taken before an ignore rule existed stay until `prune --apply`.** A new
rule (the built-in `*.tmp` floor included) stops new copies; it removes none.
Mirror cleanup removes such a snapshot copy only once its source is gone, and
nothing removes the `versioned/` file-folder except `prune --apply`. Until then
the copies are inert for the Drive lane: `drive_sync` re-filters the store
through `load_spec()` before uploading, so they never upload.

---

[<- Back to BACKUP](../README.md)
