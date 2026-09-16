# Known issues

[<- Back to BACKUP](../README.md)

Defects reproduced live and written down rather than corrected in prose. Each
entry names where it lives, so it can be checked against the tree rather than
believed.

## Open

**The "Backups now" clock is branch-global.**
`apps/handlers/state/backup_timestamps.py` holds `TIMESTAMPS_FILE` as a module
constant, so the panel `modules/display.py` renders reports @backup's last run
*anywhere* as if it were this project's. A project registered 30 seconds earlier
displayed *"Versioned: 2 mins ago · Drive sync: 7 days ago"*. The same root cause
makes the file unpatchable in tests, which is why a full suite run still rewrites
the live one — re-observed 2026-09-14, when a run moved its mtime.

**A name longer than 50 characters cannot be restored.**
The versioned store shortens the *folder* for such a file to
`<name[:30]>_<md5[:8]>` while the file inside keeps its full name;
`_find_file_folder` looks for a folder matching the name it was given, so
neither the bare form nor the path form finds it. Measured on a scratch store
2026-09-14: both lookups returned nothing for a 60-character filename that had
been copied correctly. The copy is safe — only the lookup is blind.

**`max_versions` is advertised and inert.** See
[store cleanup](store_cleanup.md); nothing prunes old versions.

**No ignore-aware store sweep.** A directory added to `.backupignore` after a
backup stays in the store — also in [store cleanup](store_cleanup.md).

## Unverified rather than broken

The Drive **upload** path (`drive_sync`, `share`) is not exercised by any run
this branch performs on itself, because it publishes to a real Drive account —
see [the Drive lane](drive_sync.md).

## Cured, kept for the record

A 2026-09-05 verification pass found four code defects. Three were fixed
2026-09-14, each with a test that failed before the fix: `restore` was missing
from the `--help` command reference; `restore` could not find a file named by a
path (see [restore](restore.md)); and the `all` row in `--help` named two of its
three stages, leaving out the Drive step. The fourth is the branch-global clock
above, still open.

---

[<- Back to BACKUP](../README.md)
