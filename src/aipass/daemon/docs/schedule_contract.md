[<- Back to the README](../README.md)

# Schedule Contract

The job file schema, schedule types, optional fields, and wake options that define how a citizen's scheduled jobs behave.

---

## Scheduling Jobs

Each citizen owns its schedule at `<branch>/.daemon/schedule.json`. The daemon discovers and fires — citizens define their own jobs.

**Nothing here is resident.** `install-timer` writes a systemd *user* timer, `daemon-tick.timer`
(`OnActiveSec=30s`, `OnUnitActiveSec=2min`, `Persistent=true`), which fires `daemon-tick.service` —
`Type=oneshot`, running `python3 -m aipass.daemon.apps.daemon run` once and exiting. Between ticks
there is no daemon process at all.

The timer wakes the whole fleet, so `install-timer` and `uninstall-timer` run for the verified admin
seat (@devpulse) only, read through @ai_mail's verified-caller rail. Any other caller is refused by
name, with the mail to send. An install that cannot reload, enable or start the timer puts the unit
folder back as it was: units it copied are removed and units that stood before get their old bytes back.
On a host with no `systemctl`, nothing runs the units, so `uninstall-timer` removes them and exits 0.

The 2 min is nominal, not exact: `OnUnitActiveSec` measures from the *last activation*, and systemd's
default `AccuracySec=1min` batches the wakeup, so observed gaps run **2–3 min**. A tick costs well
under a second of CPU (`systemctl --user show daemon-tick.service -p CPUUsageNSec` reads it) and
roughly 1s wall. `systemctl --user list-timers` shows the next fire. The tick logs through prax
(`logs/run.log`); a tick that dies leaves its traceback in `~/.aipass/daemon-tick.err` — see
[scheduler_tick.md](scheduler_tick.md#where-a-tick-is-recorded).

**Three tiers are swept.** Core citizens under `src/aipass/*` (listed in `AIPASS_REGISTRY.json`). Resident citizens under `projects/<name>/` (listed in that project's own sealed `<NAME>_REGISTRY.json`). And **federated externals** — citizens in separate repos entirely, reached through their own registries. `drone @daemon rotation` prints the tier label; nothing routes on it. The sweep covers all three tiers; the nightly rounds serve only the first — see [docs/rounds.md](rounds.md).

**Who counts as a citizen is decided by @memory, not here.** The core-registry read, the `projects/*` glob, the dot-filter and the two-key resident rule are one call to `fleet.fleet_branches()` in @memory — a fleet definition with two implementations agrees only by coincidence. `discovery.py` consumes that list rather than mirroring it, so a new tier, like the federated externals above, reaches the daemon with no change in this branch.

**What this branch still decides is an address.** @memory deliberately leaves that to each caller: in its fleet list a branch with no `email` is KEPT, because the path-based lanes (trinity push, rollover) still want it. Daemon cannot use it — a job's owner IS an email and the wake targets an email — so an addressless citizen is refused, and refused **loudly at error level**, because a citizen dropped without a line in the log is indistinguishable from one that was never discovered. A second row carrying an address already claimed is refused the same way: @memory deduplicates by resolved path, correct for its path-keyed lanes, but daemon is email-keyed and two rows sharing an address would double-fire the first citizen's schedule.

The trust model behind the fleet definition remains asymmetric on purpose: a passport can never *add* scope (nothing walks passports, so a declared resident no registry lists is unreachable by construction), and a passport can never *remove* a core citizen (a core branch declaring nothing is kept and the disagreement is logged — otherwise an agent could stop its own jobs firing by deleting one line of its own file). A project registry's paths resolve against its own project root, never the repo root — BAUD's registry row reads `src/baud/baud`, a path that *could* also resolve under this repo, and resolving repo-first picks the wrong directory.

### Job file schema

```json
{
  "version": 1,
  "branch": "@<branch>",
  "jobs": [
    {
      "id": "my-job",
      "enabled": true,
      "schedule": { "type": "interval", "interval_minutes": 30 },
      "wake": { "fresh": true, "model": "haiku" },
      "prompt": "Do something, then STOP."
    }
  ]
}
```

A job carries **exactly one** of `prompt` (wake the owner with it) or `command` (run a drone
command, wake nobody; see [docs/command_jobs.md](command_jobs.md)). Both, or neither, is refused at discovery and
logged, the same way a missing `id` or `schedule` is.

The file's place names its owner. A `branch` field, on the file or on a job, must be the owner's
address (with or without the `@`, any case). One that names another citizen, or is not a string,
is refused and the refusal names it and the owner: on the file, the whole file is refused; on a job,
only that job is. The field is a claim, so it can never move a job into someone else's name.

### Schedule types

| Type | Fields | Due when |
|------|--------|----------|
| `interval` | `interval_minutes: N` | Elapsed >= N since last_run. With no `slot`, a job that has never run fires **immediately** — see below. N must be a positive number (`30`, `0.5`): text, `null`, `true`, zero or a negative is refused at discovery and logged with the file and the job, so the job is never due. Absent, N reads as 60. |
| `daily` | `time: "HH:MM"` | Within +/-15 min of target time, once per window. A window that wraps midnight is one window. |
| `weekly` | `weekday: "monday"`..`"sunday"`, `time: "HH:MM"` | The daily window, on that weekday only. A window that wraps midnight belongs to the day its target time falls on. |
| `monthly` | `day: 1`..`31`, `time: "HH:MM"` | The daily window, on that day of the month only. A day past the month's end means its last day: `31` fires on 30 November and 28 February, so a monthly job never skips a month. |
| `rotation` | `time: "HH:MM"` | Daily window — but wakes the next citizen on the fleet roster, not the owner. See [docs/rounds.md](rounds.md). |
| `hourly` | `time: "M"` (minute) | Within +/-15 min of target minute, once per window. A window that wraps the hour is one window. |
| `once` | `due_date: "YYYY-MM-DD"` or `"YYYY-MM-DDTHH:MM"` | From that instant on (a bare date means midnight), then marks completed. An unreadable `due_date` is never due. |

A `time` that does not read for its type (`"HH:MM"` with hours 0-23 for `daily`, `rotation`,
`weekly` and `monthly`, a minute 0-59 for `hourly`) is refused at discovery and logged with the
file and the job. So is a `weekly` job without a lowercase weekday name, and a `monthly` job
without a whole-number `day` 1-31: neither has a default.

`weekly` and `monthly` carry no phase. Each window asks only whether the job ran inside it, so a
changed `weekday`, `day` or `time` takes effect at the next matching window. An `interval` job
measures from its last run instead: each fire lands up to one tick (~2 min) after the last,
and that lateness accumulates.

When a schedule file cannot be read, or one of its jobs is refused, that owner's existing
runstate rows are kept: the tick prunes rows only for owners whose file was read whole, so a
half-read schedule never erases its jobs' history.

Every refused file or job is also told to the user, with its reason: `drone @daemon queue` lists
it as a **Refused, not scheduled** warning (and `--json` under `refused`), and each tick prints it.

### Optional schedule fields

These live inside the job's `schedule` block, next to `type` and `time`. Both are opt-in
today. `catch_up` becomes on-by-default (only an explicit `false` opts out) when
`RECOVERY_LANE_LIVE` is flipped; until then only an explicit `true` turns it on — see
[docs/recovery_and_catch_up.md](recovery_and_catch_up.md).

| Field | Applies to | Effect |
|-------|-----------|--------|
| `slot` | `interval` | An ISO instant naming **one occurrence** of the rhythm you want (`"2026-09-06T03:00:00"`). A job that has never run is seeded from it, so its first fire lands on the next slot instead of the next tick. |
| `catch_up` | `daily`, `rotation`, `hourly`, `weekly`, `monthly` | When the window closed with no run, the first tick after it, the same day, fires the job once and stamps `caught_up` on the runstate row. Opt-in (`true`) while `RECOVERY_LANE_LIVE` is `False`. |
| `catch_up_max_age_hours` | `daily`, `rotation`, `hourly` | Drop missed windows older than N hours. Absent = unlimited: ten days away still earns one wake. |

**Why `slot` exists.** An interval job with no `last_run` is due on the very next
tick, and that tick's minute becomes its rhythm forever: a weekly job enabled at 01:34 on
a Monday would fire at 01:34 every Monday, whatever hour its owner meant. With a slot the
"seed first, then enable" ordering trap disappears — the job can be enabled in any order.

Seeding is keyed on an **absent `last_run`, not an absent runstate row**, and the
difference is the whole cure: a blocked fire creates a row carrying `last_blocked_at`
and no `last_run`, so a row-keyed test would refuse to seed exactly the job that most
needs it. A past slot keeps its *phase* — it is rolled forward by whole intervals, not
used verbatim, so a stale anchor never makes a job instantly overdue. A job with no
slot fires on the next tick and says so in `run.log` at WARNING.

**`hourly` has a catch-up arm** like daily's. Its window is refused rather than guessed
when it crosses the hour (a `time` past minute 44), the same shape as daily's midnight
refusal.

**`catch_up` is bounded by the window's own run check**: once any run lands at or after
today's window opened, the window no longer reads as closed unrun, so a caught-up run can
never double-fire the day it lands in, and it never widens the window backwards — a job is
still not due *before* its window opens. A daily window whose tail crosses midnight
(`time` later than 23:44) never closes inside its own calendar day and is refused
rather than guessed at, in both directions.

**The `MISSED` line** is written to `run.log` for every daily, weekly or monthly job whose window closed
unrun — independent of `catch_up`, because a job nobody opted in still missed its
window and that is the fact you need in order to decide whether to opt it in. Stamped
once per job per day (`missed_logged_for`), since a ~2-minute tick would otherwise
repeat the same miss ~500 times before midnight. A window counts as missed when it closed
with no **successful** run; when the job's attempts inside it failed, the line says so:
`closed with no successful run (last attempt failed at HH:MM)`, not `closed with no run`.

### Wake options

- `fresh` (bool) — start a fresh Claude session (true) or resume (false)
- `model` (string, optional) — `"haiku"` or `"sonnet"` recommended for light wakes
- `provider` (string, optional) — `"claude"`, `"codex"` or `"opencode"`, passed to `wake_branch(provider=...)`; absent = `claude`, and any other value refuses the job at discovery with a warning naming the job, its file and the value. On `opencode`, `model` is `provider/model[#variant]` (`opencode/glm-5.3-flash-free`) or absent = OpenCode's own default. On `codex`, `model` is a Codex slug (`gpt-6-sol`, `gpt-6.1-sol`) or absent = Codex's config default
- no wake-back, and not an option: every wake the daemon fires passes `wake_back=False`, so no job's finish wakes `@daemon` to read a reply nobody sends

