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

## Headroom: the run must fit the Drive

Before the first upload -- after the ignore re-filter, the never-leaves floor
and the tracker filter -- `drive_sync` sums the bytes of the files it is about
to upload and reads the account quota through `apps/handlers/drive/quota.py`
(`about.get` `storageQuota`, the same read `drive_stats` prints). Free space is
`limit - usage`, never below zero. Sizes are humanised by `_human_bytes` in
`apps/handlers/report/formatter.py`, the one humaniser the branch uses (1024
steps, one decimal).

- **It fits:** the run's first stdout line is `Drive: 2.9 GB to upload, 13.6 GB
  free`, then the upload runs.
- **No limit reported** (unlimited storage): it passes, and the first line is
  `Drive: 2.9 GB to upload, no storage limit reported`.
- **It does not fit:** nothing is uploaded, and the run's last stdout line is
  `Drive has 1.4 GB free; this run needs 2.9 GB. Nothing uploaded.`
- **The quota cannot be read** (no answer, or no `storageQuota` usage): nothing
  is uploaded, and the last stdout line is `Drive quota unavailable: <reason>.
  Nothing uploaded.` It is never a silent pass.

A refused run returns `success` false with `error` set to that sentence and
`error_shown` true, writes a `drive_sync_refused` trail row (with
`bytes_planned`), no changelog entry, and calls cli's `mark_command_failed()`,
so the verb exits 2. The sentence goes to stdout rather than through
`error()`, which prints to stderr: the contract wants it as the last stdout
line. A run with nothing to upload never asks for the quota.

`all`'s Drive step is the same function, so an `all` whose Drive step cannot
fit ends on the same sentence, exits 2, and keeps what its snapshot and
versioned steps wrote. `all` does not repeat the sentence (`error_shown`).
Under `all --registered` the per-project summary still follows it, as it
follows every project. The wire shape is the "Drive headroom" section of
`src/aipass/devpulse/docs.local/backup_door_contract.md`; it is not retyped
here.

## The tracker is saved while the upload runs

`upload_batch` takes the project root from `drive_sync` and saves
`.backup/drive_tracker.json` every 50 completed files, failures counted, as
well as once at the end of the run. A run that is killed or fails part-way
leaves the files it uploaded tracked, so the next run skips them instead of
uploading them again as orphans.

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

## The changelog entry

A run whose uploads all succeeded appends one entry to the project's
`.backup/changelog.json`, the same shape snapshot and versioned write, with
`mode` `drive_sync` and `files_copied` set to the files uploaded in that run.
`status --json` reads the Drive lane's `last` and `files` from it. A run with
a failed upload, or with nothing to upload, writes none: the snapshot lane's
rule for a run that copied nothing. The `all` cycle's Drive step is the same
function, so it writes the same entry.

`share` is the single-file lane: it uploads one file and prints the shareable
link as its final line, so the link can be captured from stdout.

---

[<- Back to BACKUP](../README.md)
