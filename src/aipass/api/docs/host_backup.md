[<- Back to the README](../README.md)

# The host backup door — runs, jobs, status and the schedule

**Branch** api · **Code** `apps/handlers/host/backup.py`, `apps/handlers/host/backup_route.py`

The host API's six `/v1/backup` routes: they start and stop @backup's lanes, poll the jobs,
read the store's status, and read and set a project's scheduled backup, all through
`drone @backup`. Routes and scopes are tabled in [host_api.md](host_api.md).

---

**The backup door proxies @backup and owns no backup.** `POST /v1/backup/run`,
`POST /v1/backup/cancel`, `GET /v1/backup/job`, `GET /v1/backup/status` and both `/v1/backup/schedule` (`backup.py`,
hung on the app by `backup_route.py`) reach `drone @backup` through drone's router and
nothing else: a run is `drone @backup <lane> <root>` (`--quiet` on every lane but
`drive_sync`, which has no such flag); a cancel is `drone @backup stop <root> <lane>`;
status is `drone @backup status <root> --json [--sizes]`, passed through with `project`
and `root` added.
The root comes from the read lane's resolver (the seat or a census name), never a `@name`.
A status answer that is not one JSON object is a 503; the Rich panel is never scraped.

**A job is `{job, project, lane, state, started_at}`**; a finished one adds `finished_at`,
`exit` (`null` when the lane never answered), `summary` and `error`. Refusals ride the
`{error: {code, message}}` envelope: **400 `verb_refused`** (no or unknown lane or
project, the lane already running) says its sentence; **503 `verb_unavailable`** gives a
fixed sentence and a `ref` into this host's log.

**`running` is @backup's list** (its running files: terminal and daemon runs too), entry
for entry, each with `job`: this server's id for a run it started there under the entry's
`verb`, else `null`. No `running` key (older @backup): this server's in-flight jobs and one
log line. Not a list of objects: 503.

**Cancel never touches the job table.** `stop` runs on the request thread (60 s timeout,
over @backup's 30 s wait); the job closes when its lane exits.

**Start and poll, because a lane outlives a request.**
The run answers **202** with the job at once and runs the lane on a worker thread; the phone polls the job every few seconds. One job per project and lane at a
time (a second is a 400 naming the first); different lanes overlap and
@backup's own locks decide the rest. `summary` is the last 600 characters of the output,
verbatim. A job ends `done` (exit 0), `stopped` (130) or `failed` (anything else).
snapshot gets 30 min, all a day; drive_sync has no limit (a Drive
rebuild is hours; cancel ends it). At a limit the server asks @backup to `stop` the
lane, which exits 130 and clears its running file; drone's hang guard backs it up. A run that never reached @backup is a 503 and opens no job; one that died behind
the door is a `failed` job with drone's sentence in `error`.

**A restart forgets every job.** Jobs live in the server's memory, and a finished one is
dropped after an hour. A forgotten id is **404 `job_unknown`**, and the phone then reads
`/v1/backup/status`, whose answer comes from @backup's store and survives everything.

**The schedule is @backup's, read and set through it.** `GET /v1/backup/schedule` answers
`drone @backup schedule <root> --json` unchanged: `project`, `root`, `job_id`, `scheduled`,
`on`, `frequency` (`daily`, `weekly`, `monthly` or null), `time`, `weekday` (the day's name,
weekly only), `day` (an integer, monthly only), `steps`, `last_run`, `last_status`,
`last_error`, `next_run`. `POST /v1/backup/schedule` takes a frequency with its fields and
`on`, in one body or apart: `daily` takes `time`; `weekly` takes `weekday` (`monday` to
`sunday`, lowercase) and `time`; `monthly` takes `day` (a JSON integer, 1 to 31) and `time`.
It sends @backup's set form first (`weekly monday 05:00`), then `on` or `off`, and answers the
schedule read back; changing the frequency or time keeps on or off. A new schedule starts
off, and `on` with no schedule yet is @backup's refusal. The body is checked first, so nothing
@backup would refuse for its form reaches it: a missing field, a field the frequency does not
take (`weekday` with `daily`), a time that is not a 24-hour `HH:MM`, an `on` that is not a
JSON boolean. Each is a **400 `verb_refused`** naming the field.
@backup's exit 2 carries a sentence on stderr: that sentence, without its usage hint, is a
**400 `verb_refused`**, for a refusal and for a fault @backup names (@daemon unreachable)
alike, because one exit code covers both. Any other exit, or an exit 2 with no sentence, is a
**503**. A schedule set before a refused `on` stays set.
