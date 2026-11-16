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
drone @backup schedule <project|@name> daily HH:MM  # every day at that 24-hour time
drone @backup schedule <project|@name> on|off       # run it, or keep it and never run it
```

The project must be registered: the job names it as `@name`. A new schedule is
written by `daily HH:MM` and starts off; `on` is its own command. `on` or `off`
with no schedule yet is refused. A time that is not a 24-hour `HH:MM`, any
other word, `weekly` and `monthly` are refused on stderr, exit 2, nothing
written. @daemon's schedule has daily, hourly, interval, once and rotation
types and no weekly or monthly one; an interval of a week loses its weekday
when the schedule changes, so weekly and monthly wait for @daemon types.

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
- `frequency` is `"daily"`; `weekday` and `day` are always null.
- `last_run`, `last_status` and `last_error` are @daemon's queue row for the
  job (`drone @daemon queue --json`), null before its first run.
- `next_run` is the next local `HH:MM`, null when off.
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
