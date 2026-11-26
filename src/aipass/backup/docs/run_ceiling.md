[<- Back to BACKUP](../README.md)

# The run ceiling — runaway guard

Every run measures its filtered set before copying anything and refuses loudly when it breaches a ceiling.

An ignore miss cannot be caught by better ignore patterns alone; the next unfamiliar build system will have a directory nobody has listed yet. So every run **measures the filtered set before copying anything** and holds it to two layers, in this order:

1. **Growth against the last good run.** More than `max_growth_ratio` times the last good run's files, or its bytes, refuses. A store that grows by design grows a little each run; a runaway multiplies it.
2. **The absolute walls.** The outer limit, whatever the history says.

| Config key | Default | Meaning |
|---|---|---|
| `max_growth_ratio` | `3` | Refuse past this multiple of the last good run's files or bytes |
| `max_backup_files` | `100000` | Maximum files in one run |
| `max_backup_size_gb` | `10` | Maximum total source bytes in one run |

Set any of them to `0` to disable that check.

**The baseline.** After a snapshot that completes with no failed copy, the run's file count and measured bytes are written to `.backup/last_good_run.json` (`handlers/state/baseline.py`); a quick-check run that finds nothing changed is a completed run too. A refused, stopped or failed run never writes it, so a runaway never becomes the new normal. With no baseline (a first run, or the file lost) the growth check does not apply, the log says so at info, and only the walls hold. An unreadable baseline is logged at warning and treated the same way.

A refusal names the directories that caused it, at a depth you can paste straight into `.backupignore`:

```
✗ Backup refused — 41,200 files is 3.1x the last run's 13,300
  Largest directories in this run:
    app/src-tauri/target  —  27,900 files
  Add the build-artifact directories above to .backupignore, then re-run.
  If the project really grew, raise 'max_growth_ratio' in .backup/config.json (0 disables).
```

A wall refusal reads the same way, with the wall's key as the way out ("33,093 files exceeds the 25,000-file ceiling", raise `max_backup_files`).

The guard sits in `snapshot` **and** `all`. `all` walks the tree once and hands the filtered set to the snapshot lane (`pre_scanned`), which measures that set again, so a snapshot run on its own and one run from `all` are guarded alike.

A check that cannot run refuses too. A file that exists but cannot be stat'ed (a permission error, a path under a regular file) cannot be measured, so the run is refused, naming the file and the error: make it readable or add it to `.backupignore`, then re-run. A file that vanished between the walk and the measure is skipped, logged at info; it is no longer in the set.

**Limit:** the ceiling refuses a run before it copies. A store an earlier run already filled is shrunk by prune, not by the ceiling — see [store cleanup](store_cleanup.md).

---

[<- Back to BACKUP](../README.md)
