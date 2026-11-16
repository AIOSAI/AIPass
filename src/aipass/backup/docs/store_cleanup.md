[<- Back to BACKUP](../README.md)

# Store cleanup — what exists and what does not

Which deletions this branch performs, what triggers each, and what it advertises but does not do.

Two lanes delete from the snapshot store, each on its own trigger:

| Lane | Removes | Trigger |
|---|---|---|
| Mirror cleanup, `handlers/cleanup/mirror.py` | `snapshots/` files | the source file no longer exists; runs inside every snapshot |
| `prune`, `modules/prune.py` + `handlers/cleanup/prune.py` | `snapshots/` files | the ignore spec now matches the project path; runs only when called |

### Mirror cleanup

Removes a snapshot file **whose source no longer exists**. That is its only
trigger: a file that is still in the source tree keeps its snapshot copy even
when it became ignored, because `_should_delete()` only asks whether the source
exists.

### `prune` — copies the ignore spec now matches

```
drone @backup prune <project_root|@name>            # list, delete nothing
drone @backup prune <project_root|@name> --apply    # delete what the list names
```

A path is pruned by the backup's own filter rule (`scan/filter.py`): `load_spec()`
(the project's `.backupignore` behind the built-in floor, `BUILTIN_IGNORE_PATTERNS`)
matches its project-relative path, and the project's `whitelist` does not keep it.
A whitelisted path is one the next run copies straight back, so it is never listed.

One candidate per **file**, `snapshots/<rel_path>`.

The listing prints one row per top-level directory (count and bytes;
root-level files under `(root files)`), then the grand total. Without `--apply`
nothing is deleted and the last line says so. With `--apply` each listed path is
removed, one `prune_removed` row per path in `logs/operations.jsonl`, directories
left empty are removed, and the last line names what was removed and freed. A
path that cannot be removed is an error on stderr and the command exits non-zero;
it is never counted as removed.

`--apply` runs for two callers only, by @ai_mail's verified-caller rail: @backup's
own seat and the verified admin. Anyone else is refused before the store is read,
an error on stderr; the dry run stays open to every caller. Each `--apply`
verdict is one `prune_fence` row naming the caller.

`prune` never touches the remote copy. Drive entries for pruned files are not
removed from Drive; that remains the owner's by hand.

### What is not implemented

**Copies taken before an ignore rule existed stay until `prune --apply`.** A new
rule (the built-in `*.tmp` floor included) stops new copies; it removes none.
Mirror cleanup removes such a snapshot copy only once its source is gone, and
nothing removes it except `prune --apply`. Until then
the copies are inert for the Drive lane: `drive_sync` re-filters the store
through `load_spec()` before uploading, so they never upload.

---

[<- Back to BACKUP](../README.md)
