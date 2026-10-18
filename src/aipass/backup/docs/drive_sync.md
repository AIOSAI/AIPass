[<- Back to BACKUP](../README.md)

# The Drive lane

Optional, off by default, and the only part of this branch that leaves the
machine. It uploads the **snapshot** store; the versioned store never leaves
the machine.

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

`drive_check` (authenticates through the gateway and prints the backup-folder
ID) and `drive_stats` (reads the tracker and the account quota) upload nothing.
The **upload** path (`drive_sync`, `share`) publishes files to a real Drive
account, and the suite exercises it only against a mocked client: no test
verifies it end to end.

## What the lane uploads

`drive_sync` walks `<project>/.backup/snapshots/` and uploads each file under
`AIPass Backups/<project dir name>/snapshot/<path relative to the snapshot
store>`. Anything else under `AIPass Backups/<project dir name>/` (such as what
a versioned-store sync put directly there) is left alone: this branch never
deletes anything remote; removing it is a job done by hand.

Before uploading, the store is re-filtered through `load_spec()`, so a store that
was filled before an ignore rule existed still does not publish the files that
rule now covers. That is why copies taken before a rule existed (see [store
cleanup](store_cleanup.md)) are inert rather than urgent.

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
follows every project. Through the host API's backup door, a refused run is a
`failed` job, not an HTTP error: the lane exits 2, the job read answers 200, and
the job's `summary`, the tail of the lane's output, carries the sentence.

## On the host API's backup door

The host API (@api) runs these lanes for the phone through four routes. A lane is
one of the four drone verb names, `snapshot`, `versioned`, `all` or `drive_sync`,
and runs as `drone @backup <lane> <root>`, with `--quiet` for all but
`drive_sync`, which has none.

| Route | Scope | Sends | Answers |
|---|---|---|---|
| `POST /v1/backup/run` | operate | `{project, lane}` | **202**, the job with `state: "running"` |
| `GET /v1/backup/job?id=<job>` | read | the job id | the job |
| `GET /v1/backup/status?project=<name>[&sizes=1]` | read | the project, `sizes=1` for the store sizes | the status |
| `POST /v1/backup/cancel` | operate | `{project, lane}`, the lane pressed | **200**, `{project, lane, stopped: true, message}` |

- **The status** is `status <root> --json [--sizes]` (see [the CLI](cli.md#status---json))
  passed through, with `project` as asked and `root` as resolved added, and each
  `running` entry given `job`: the server's id when it started that run, else null.
- **A job** carries `job`, `project`, `lane`, `state` and `started_at`; once it
  ends, also `finished_at`, `exit`, `summary` (the tail of the lane's output,
  verbatim, at most 600 characters) and `error`. `state` is `running`, `done`
  (exit 0), `stopped` (exit 130) or `failed` (any other exit, the 30-minute
  timeout, or a routing error mid-run, whose sentence is in `error`). Jobs live in
  the server's memory: a finished one is kept an hour, and a restart forgets all.
- **Four error codes.** **400 `verb_refused`**: no project or an unknown one, a
  lane outside the four, or that lane already running for that project
  (`<lane> already running for <project> since <iso>`). **404 `job_unknown`**: a
  job the server does not hold. **404 `not_running`**: cancel found nothing of
  that lane running; the message is `stop`'s line verbatim. **503
  `verb_unavailable`**: @backup, drone or the project resolver cannot answer, or
  `status --json` is missing; the message is a fixed sentence with a `ref` into
  the host's log.

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
