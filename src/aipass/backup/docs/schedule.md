[<- Back to BACKUP](../README.md)

# Schedule — each project's scheduled backup

A registered project's scheduled backup is one @daemon command job in this
branch's `.daemon/schedule.json`, with the id `backup-<name>`. The `schedule`
verb reads and writes it; @daemon fires it. There is no second scheduler and
no second copy of the schedule.

A scheduled run is the `all` lane for that project, `drone @backup all @<name>
--quiet`: snapshot first, then drive_sync when the project's `drive_sync`
setting is on, because Drive uploads from the snapshot. A project with
`drive_sync` off runs a snapshot only. The steps list in `--json` reads the
setting, so it is true per project.

## Commands

```
drone @backup schedule <project|@name>              # plain lines
drone @backup schedule <project|@name> --json       # one JSON object on stdout
drone @backup schedule <project|@name> daily HH:MM               # every day
drone @backup schedule <project|@name> weekly WEEKDAY HH:MM      # monday..sunday
drone @backup schedule <project|@name> monthly DAY HH:MM         # 1-31
drone @backup schedule <project|@name> on|off                    # run it, or keep it and never run it
```

The project must be registered: the job names it as `@name`. A new schedule
starts off; `on` is its own command, and changing when a schedule runs keeps
its on or off. `on` or `off` with no schedule yet is refused. `HH:MM` is
24-hour with two digits each; `WEEKDAY` is a lowercase full English day name;
`DAY` is a whole number 1 to 31 without a leading zero. A monthly day past the
month's end runs on its last day (31 runs on 30 November and 28 or 29
February), so no month is skipped. Anything else is refused on stderr, exit 2,
nothing written.

The job's `schedule` is @daemon's own shape:
`{"type": "daily", "time": "05:00"}`,
`{"type": "weekly", "weekday": "monday", "time": "05:00"}` or
`{"type": "monthly", "day": 31, "time": "05:00"}`. Each fires in @daemon's
+/-15 minute window on a day it runs.

## `--json`

```json
{"project": "aipass", "root": "/path/to/AIPass", "job_id": "backup-aipass",
 "scheduled": true, "on": true, "frequency": "daily", "time": "05:00",
 "weekday": null, "day": null, "steps": ["snapshot", "drive_sync"],
 "last_run": null, "last_status": null, "last_error": null,
 "next_run": "2026-11-16T05:00:00"}
```

- `scheduled` is false when the project has no job; then `on` is false and
  `frequency`, `time` and `next_run` are null.
- `frequency` is `"daily"`, `"weekly"` or `"monthly"`. `weekday` is the day
  name for weekly and null otherwise; `day` is the number for monthly and null
  otherwise.
- `last_run`, `last_status` and `last_error` are @daemon's queue row for the
  job (`drone @daemon queue --json`), null before its first run.
- `next_run` is the first run after now on a day the schedule runs, local,
  null when off.
- An unreadable schedule file, a job in a shape this verb does not write, an
  unreadable project config, @daemon unreachable or @daemon refusing the job:
  an error on stderr, exit 2, no JSON.

## The job

`timeout_seconds` is 28800, the owner's eight hours for a Drive upload of a
whole snapshot store. `notify` mails @devpulse on start and finish.
`catch_up` is not set: a 05:00 missed with the machine off is logged MISSED
and waits for the next day. Jobs due on the same tick fire one after another
in file order, so a short project placed first does not wait behind a long
upload.

`register --remove <name>` removes the project's job before its registry
entry, so no job is left to fail each night. A schedule file that cannot be
read or written stops the removal with an error, and the project stays
registered.
