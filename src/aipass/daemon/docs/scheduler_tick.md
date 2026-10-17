[<- Back to the README](../README.md)

# Scheduler Tick

How a scheduler tick fires a job, what each fire outcome consumes, how the scheduled lane differs from an interactive one, how jobs are staggered, and how run.py's code is organized.

---

## How run.py's code is split

`run.py` holds the tick lane: discovery, the due check, the fire, and the FIRE and DONE log
lines. Three handlers hold what is not the tick lane itself:

| Module | Owns | Why it is not in run.py |
|--------|------|-------------------------|
| `handlers/schedule/catch_up_lane.py` | detect-and-queue, drain-one, and the `OUTCOME_*` vocabulary | The catch-up glue is a whole subject, and the largest block a reader would otherwise skip past to follow an ordinary tick |
| `handlers/schedule/tick_lock.py` | the lock directory, the lock file, `fcntl` | It is the only thing in the tick lane that touches the filesystem, and a handler may do that where a module may not |
| `handlers/schedule/job_reference.py` | the static job-authoring reference `run --help` prints, as data | It is reference text, not logic; run.py still does the printing |

**`catch_up_lane` fires nothing itself.** `fire` and `log` arrive as callables from
`run.py`. A handler may not import a module — that is seedgo's encapsulation rule and
the circular import it exists to prevent — so injection is what keeps the dependency
arrow pointing one way. It also means the lane is testable without a tick.

**`tick_lock` takes the lock path as an argument** rather than holding its own copy of
the constant. `run.py` owns `LOCK_FILE`, so a test that seams the path on that module
seams the file that actually gets opened; a second copy of the constant would quietly
re-point the suite at the live lock.

`OUTCOME_FIRED` / `OUTCOME_FAILED` / `OUTCOME_BLOCKED` are re-exported from `run.py`,
not redefined there: the drain branches on the same three words the fire returns, and
one definition means they cannot drift.

**The fire logic stays in run.py.** seedgo's module cap is 600 lines (600 or more fails as
"too large"), but prax names a log file after the nearest calling frame, so the FIRE and DONE
lines reach `logs/run.log` only when run.py writes them.

## The scheduled lane

Every wake `run` makes was fired by a clock, so it passes `scheduled=True` to
`wake_branch` unconditionally. The flag describes **this caller's lane, never the
target** — deciding it per-target would mean reading the target's passport here, a
second copy of the manager gate `wake_branch` already owns.

What it changes: a **manager** target goes headless through `dispatch_monitor`
(self-terminating, context pin, bounce mail, lock cleanup, a register entry something
closes) instead of an interactive tmux session that nothing ever closes, which would block
the next fire. A **`WAKE_BLOCKLIST`** target (`@devpulse`) is refused outright in this lane;
`@devpulse/cl-harvest-resume` is the one job that would meet that fence, and it is disabled.
Every other target is unaffected. `rotation.py` takes the same lane for managers.

## What a fire consumes

**Only a wake that actually STARTED consumes the job's period.** A fire ends in one
of three states, not two, and each writes a different record:

| Outcome | What happened | `last_run` | Next tick |
|---------|---------------|-----------|-----------|
| `fired` | An agent started | stamped | period consumed |
| `blocked` | The wake was refused before anything started — the target is busy (`lock`), holds an interactive session (`occupancy`), autonomous_pause is on, or the dispatch lock could not be taken | **untouched** | still due; retries inside the same window after a 5-min hold |
| `failed` | The wake ran and went wrong, or the target is a decided refusal (`resolve` — no such branch; `blocklist`) | stamped | measured from the last SUCCESS; 10-min backoff |

Blocked is not ran: a refusal recorded as a run would let an interactive room left open in a
branch swallow that branch's next fire.

Both holds are **bounds, not suppressions**. Removing a suppression without adding a
bound is how you turn one swallowed fire into a spawn storm: a windowed schedule allows
±15 min at a ~2-minute tick, and an interval job measures from its last *attempt*, which
a block deliberately does not write. Blocked holds for less than a failure (5 min vs 10)
because nothing spawned and the target being busy usually clears itself.

`queue` renders `blocked` in its `last_status` column; the `--json` schema carries it as a
`last_status` value.

## Staggering

Interval jobs have `slot` (see [schedule_contract.md](schedule_contract.md)) — declare the hour you want and the first fire lands on it. For the other types, seed different `last_run` values in `daemon_json/daemon_runstate.json`. Within a single tick, jobs that fire together are already separated by a fixed 1s sleep (`run.py`) — that is not configurable and is not a substitute for offsetting the schedules themselves.
