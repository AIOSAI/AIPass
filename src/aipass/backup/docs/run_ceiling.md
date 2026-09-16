# The run ceiling — runaway guard

[<- Back to BACKUP](../README.md)

Every run measures its filtered set before copying anything and refuses loudly when it breaches a ceiling.

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

**Known gap:** the ceiling stops a runaway *before* it happens. It does not clean up a store that a previous run already filled — see [store cleanup](store_cleanup.md).

---

[<- Back to BACKUP](../README.md)
