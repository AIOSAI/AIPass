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

The 2 min is nominal, not exact: `OnUnitActiveSec` measures from the *last activation*, and systemd's
default `AccuracySec=1min` batches the wakeup, so observed gaps run **2–3 min**. A tick costs about
**0.6s of CPU** (`systemctl --user show daemon-tick.service -p CPUUsageNSec`, measured 2026-08-25:
`626320000` ns) and roughly 1s wall. `systemctl --user list-timers` shows the next fire; the tick's
own output appends to `~/.aipass/daemon-tick.log`.

**Three tiers are swept (measured 2026-09-05: 28 citizens).** Core citizens under `src/aipass/*` (listed in `AIPASS_REGISTRY.json`) — 18 tonight. Resident citizens under `projects/<name>/` (listed in that project's own sealed `<NAME>_REGISTRY.json`) — 4 tonight: AIPASS_SITE, BAUD, EARMARK, FINCH. And **federated externals** — citizens in separate repos entirely, reached through their own registries — 6 tonight: VERA, RESEARCH, VERIFY and WRITER under `external/VERA-STUDIO`, plus `external/WREN` and `external/DEMO`. `drone @daemon rotation` prints the tier label; nothing routes on it. The sweep covers all three tiers; the nightly rounds serve only the first — see [docs/rounds.md](rounds.md).

**Who counts as a citizen is no longer decided here (FPLAN-0460).** The core-registry read, the `projects/*` glob, the dot-filter and the two-key resident rule all used to live in `discovery.py` as a second copy of the fleet definition. They are now one call to `fleet.fleet_branches()` in @memory — a fleet definition with two implementations agrees only by coincidence. `discovery.py:159` consumes that list rather than mirroring it, which is why the federated-external tier above arrived here without a line changing in this branch.

**What this branch still decides is an address.** @memory deliberately leaves that to each caller: their ruling is that a branch with no `email` is KEPT, because the path-based lanes (trinity push, rollover) still want it. Daemon cannot use it — a job's owner IS an email and the wake targets an email — so an addressless citizen is refused, and refused **loudly at error level**, because a citizen dropped without a line in the log is indistinguishable from one that was never discovered. A second row carrying an address already claimed is refused the same way: @memory deduplicates by resolved path, correct for its path-keyed lanes, but daemon is email-keyed and two rows sharing an address would double-fire the first citizen's schedule.

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

### Schedule types

| Type | Fields | Due when |
|------|--------|----------|
| `interval` | `interval_minutes: N` | Elapsed >= N since last_run. With no `slot`, a job that has never run fires **immediately** — see below. |
| `daily` | `time: "HH:MM"` | Within +/-15 min of target time, once per day. |
| `hourly` | `time: "M"` (minute) | Within +/-15 min of target minute, once per hour. |
| `once` | `due_date: "YYYY-MM-DD"` | Date <= today, then marks completed. |
| `rotation` | `time: "HH:MM"` | Daily window — but wakes the next citizen on the fleet roster, not the owner. See [docs/rounds.md](rounds.md). |

### Optional schedule fields

Added 2026-09-07 under FPLAN-0492 ruling 6.

These live inside the job's `schedule` block, next to `type` and `time`. `slot` is
opt-in. `catch_up` **was** opt-in under ruling 6 and is now on by default — the owner
reversed it on 2026-09-08 after every enabled job in the fleet left it unset and the
fleet therefore recovered from nothing.

| Field | Applies to | Effect |
|-------|-----------|--------|
| `slot` | `interval` | An ISO instant naming **one occurrence** of the rhythm you want (`"2026-09-06T03:00:00"`). A job that has never run is seeded from it, so its first fire lands on the next slot instead of the next tick. |
| `catch_up` | `daily`, `rotation`, `hourly` | When the window closed with no run, the first tick after it fires the job once and stamps `caught_up` on the runstate row. **ON by default since 2026-09-08** — see [docs/recovery_and_catch_up.md](recovery_and_catch_up.md). |
| `catch_up_max_age_hours` | `daily`, `rotation`, `hourly` | Drop missed windows older than N hours. Absent = unlimited, which is the default the owner asked for: ten days away still earns one wake. |

**Why `slot` exists.** An interval job with no `last_run` is due on the very next
tick, and that tick's minute becomes its rhythm forever. @seedgo enabled a weekly
cycle at 01:34 on 2026-09-07 before its slot was seeded; `run.log` shows two blocked
attempts (01:34:52, 01:40:20) and only @seedgo's own branch lock kept the week from
locking to 01:34 Monday instead of Sunday 03:00. With a slot the "seed first, then
enable" ordering trap disappears — the job can be enabled in any order.

Seeding is keyed on an **absent `last_run`, not an absent runstate row**, and the
difference is the whole cure: a blocked fire creates a row carrying `last_blocked_at`
and no `last_run`, so a row-keyed test would refuse to seed exactly the job that most
needs it. A past slot keeps its *phase* — it is rolled forward by whole intervals, not
used verbatim, so a stale anchor never makes a job instantly overdue. A job with no
slot keeps today's behaviour and says so in `run.log` at WARNING.

**`hourly` gained a catch-up arm on 2026-09-08.** Before that `is_job_due` routed
hourly to `_is_hourly_due` alone, so an hourly job had no catch-up at all whatever
its `catch_up` field said. Its window is refused rather than guessed when it crosses
the hour (a `time` past minute 44), the same shape as daily's midnight refusal.

**`catch_up` is bounded by `_already_ran_today`**, so a caught-up run can never
double-fire the day it lands in, and it never widens the window backwards — a job is
still not due *before* its window opens. A daily window whose tail crosses midnight
(`time` later than 23:44) never closes inside its own calendar day and is refused
rather than guessed at, in both directions.

**The `MISSED` line** is written to `run.log` for every daily job whose window closed
unrun — independent of `catch_up`, because a job nobody opted in still missed its
window and that is the fact you need in order to decide whether to opt it in. Stamped
once per job per day (`missed_logged_for`), since a ~2-minute tick would otherwise
repeat the same miss ~500 times before midnight.

### Wake options

- `fresh` (bool) — start a fresh Claude session (true) or resume (false)
- `model` (string, optional) — `"haiku"` or `"sonnet"` recommended for light wakes
- no wake-back, and not an option: every wake the daemon fires passes `wake_back=False`, so no job's finish wakes `@daemon` to read a reply nobody sends (DPLAN-0337 R2, 2026-09-10)

