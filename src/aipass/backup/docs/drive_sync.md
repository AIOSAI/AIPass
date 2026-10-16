[<- Back to BACKUP](../README.md)

# The Drive lane

Optional, off by default, and the only part of this branch that leaves the
machine. Since DPLAN-0411 (2026-10-16) it uploads the **snapshot** store; the
versioned store never leaves the machine.

## When it runs

- `drone @backup drive_sync <project_path|@name>` runs it, always: the caller
  asked for it by name.
- `drone @backup all <project_path|@name>` runs it as its last step only when
  the project's `drive_sync` setting is on. When it is off, `all` prints `Drive
  sync off for this project` and its `all_complete` trail row carries
  `drive_skipped: true`.
- `drone @backup settings drive_sync on|off <project_path|@name>` writes the
  setting into the project's `.backup/config.json`. It refuses a directory with
  no `.backup/` store rather than creating one.

## Credentials

**Drive commands need credentials.** They authenticate through the @api gateway;
without Google API libraries or credentials they fail loudly rather than
pretending to sync. `drive_clear` only clears the local dedup tracker — it never
deletes anything already uploaded to Drive.

## What is verified, and what is not

`drive_check` authenticated through the gateway and returned a live backup-folder
ID, and `drive_stats` read the tracker, both on 2026-09-05. The **upload** path
(`drive_sync`, `share`) was deliberately *not* exercised — it publishes files to
a real Drive account — so it stands **unverified since 2026-08-29**, the last
recorded `drive_sync` run. The snapshot-store upload (DPLAN-0411) has been
exercised only against a mocked client; its first live run is devpulse's. A page that claims an upload works because the code
looks right would be worth less than this sentence.

## What the lane uploads

`drive_sync` walks `<project>/.backup/snapshots/` and uploads each file under
`AIPass Backups/<project dir name>/snapshot/<path relative to the snapshot
store>`. What an earlier versioned-era sync put on Drive (directly under
`AIPass Backups/<project dir name>/`) is left there: this branch never deletes
anything remote, and the owner removes that tree by hand when he chooses.

Before uploading, the store is re-filtered through `load_spec()`, so a store that
was filled before an ignore rule existed still does not publish the files that
rule now covers. That is why the pre-rule `*.tmp` copies described in [store
cleanup](store_cleanup.md) are inert rather than urgent.

## The never-leaves floor

After `load_spec()`, every path is checked against `NEVER_LEAVES_MACHINE` in
`apps/handlers/drive/floor.py`. A match is counted, never uploaded, and the run
logs one line with the count (`held back N files the never-leaves floor
matches`). The patterns, in gitignore syntax:

| Pattern | What it holds back |
|---|---|
| `.secrets/` | any directory named `.secrets`, at any depth |
| `*.key`, `*.pem` | private keys and certificates |
| `.env`, `.env.*` | environment files |
| `**/*_json/tokens_data.json`, `**/*_json/tokens_config.json` | the host API's token store |

**Why it is not in `.backupignore`.** `.backupignore` decides what the local
stores keep, and the local snapshot should keep these files: a backup that cannot
restore a project's keys and environment is not a backup. Only the lane that
leaves the machine refuses them. The floor is a separate spec, applied after the
project's own, so no line in a `.backupignore` -- a `!` negation included -- can
reopen it.

## The tracker answers for one lane

`.backup/drive_tracker.json` records what has been uploaded, keyed by path
relative to the snapshot store, and carries a top-level `"_lane": "snapshot"`.
A tracker with no stamp, or a stamp naming another lane, was written by the
versioned-era lane: its keys are versioned-store paths. The next `drive_sync`
renames it to `drive_tracker.versioned.json` beside it -- kept, never deleted --
logs one line saying so, and starts a fresh tracker. If a
`drive_tracker.versioned.json` already exists the run stops instead of
overwriting it; move one of the two by hand. An empty tracker (what
`drive_clear` leaves) has nothing to keep and is simply reused.

`share` is the single-file lane: it uploads one file and prints the shareable
link as its final line, so the link can be captured from stdout.

---

[<- Back to BACKUP](../README.md)
