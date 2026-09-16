# Scheduler Tick

How a scheduler tick fires a job, what each fire outcome consumes, how the scheduled lane differs from an interactive one, how jobs are staggered, and how run.py's code is organized.

[<- daemon README](../README.md)

---

## run.py's split

Built 2026-09-08 (PR #759 row 13). `run.py` reached 690 lines against seedgo's module cap and held one direct file
operation — `LOCK_FILE.parent.mkdir` — which a module may not do. Both were the last
red row on PR #759. Two coherent pieces came out; the tick lane itself did not move.

| Module | Owns | Why it is not in run.py |
|--------|------|-------------------------|
| `handlers/schedule/catch_up_lane.py` | detect-and-queue, drain-one, and the `OUTCOME_*` vocabulary | The DPLAN-0332 glue is a whole subject, and it was the largest block a reader had to skip past to follow an ordinary tick |
| `handlers/schedule/tick_lock.py` | the lock directory, the lock file, `fcntl` | It is the only thing in the tick lane that touches the filesystem, and a handler may do that where a module may not |

**`catch_up_lane` fires nothing itself.** `fire` and `log` arrive as callables from
`run.py`. A handler may not import a module — that is seedgo's encapsulation rule and
the circular import it exists to prevent — so injection is what keeps the dependency
arrow pointing one way. It also means the lane is testable without a tick.

**`tick_lock` takes the lock path as an argument** rather than holding its own copy of
the constant. `run.py` still owns `LOCK_FILE`, so a test that seams the path on that
module still seams the file that actually gets opened; a second copy of the constant
would have quietly re-pointed the suite at the live lock.

`OUTCOME_FIRED` / `OUTCOME_FAILED` / `OUTCOME_BLOCKED` are re-exported from `run.py`,
not redefined there: the drain branches on the same three words the fire returns, and
one definition means they cannot drift.

Result: **run.py 690 → 585 lines**, zero direct file operations, `Modules` 100,
`drone @seedgo audit aipass @daemon` **100%**. No behaviour changed and
`RECOVERY_LANE_LIVE` stayed `False` throughout.

**The cap is 600 lines, not 650** (measured 2026-09-11 in seedgo's
`handlers/aipass_standards/modules_check.py`: 600 or more fails as "too large"). This section
said 650 until then. DPLAN-0338 wave 1a's command-job arm took run.py from 589 to 647 and cost
the audit a point. The 79 lines of static job-authoring reference that `run --help` prints moved
to `handlers/schedule/job_reference.py` as data, and run.py still does the printing. Result:
**run.py 570 lines**, with `run --help` output byte-identical before and after (diffed at
`COLUMNS=200`). The fire logic stayed in run.py on purpose. Prax names a log file after the
nearest calling frame, so the FIRE and DONE lines reach `logs/run.log` only when run.py
writes them.

## The scheduled lane

Every wake `run` makes was fired by a clock, so it passes `scheduled=True` to
`wake_branch` unconditionally. The flag describes **this caller's lane, never the
target** — deciding it per-target would mean reading the target's passport here, a
second copy of the manager gate `wake_branch` already owns.

What it changes: a **manager** target goes headless through `dispatch_monitor`
(self-terminating, context pin, bounce mail, lock cleanup, a register entry something
closes) instead of an interactive tmux session that nothing ever closes — which was the
room that blocked the next night's fire. A **`WAKE_BLOCKLIST`** target (`@devpulse`) is
refused outright in this lane; `@devpulse/cl-harvest-resume` is the one job that would
meet that fence, and it ships disabled. Every other target is unaffected.
`rotation.py` already took this lane for managers; `run.py` was the odd path out.

## What a fire consumes

Built 2026-08-30. **Only a wake that actually STARTED consumes the job's period.** A fire ends in one
of three states, not two, and each writes a different record:

| Outcome | What happened | `last_run` | Next tick |
|---------|---------------|-----------|-----------|
| `fired` | An agent started | stamped | period consumed |
| `blocked` | The wake was refused before anything started — the target is busy (`lock`), holds an interactive session (`occupancy`), autonomous_pause is on, or the dispatch lock could not be taken | **untouched** | still due; retries inside the same window after a 5-min hold |
| `failed` | The wake ran and went wrong, or the target is a decided refusal (`resolve` — no such branch; `blocklist`) | stamped | measured from the last SUCCESS; 10-min backoff |

The middle row is the fix for a scheduler that planted the blocker for its own next
fire: an interactive room left open in a branch made `wake_branch` refuse, the refusal
was recorded as a run, and the next day's fire was swallowed by a room nobody was
sitting in. Blocked is not ran.

Both holds are **bounds, not suppressions**. Removing a suppression without adding a
bound is how you turn one swallowed fire into a spawn storm: a windowed schedule allows
±15 min at a ~2-minute tick, and an interval job measures from its last *attempt*, which
a block deliberately does not write. Blocked holds for less than a failure (5 min vs 10)
because nothing spawned and the target being busy usually clears itself.

`queue` renders the new `blocked` value in its existing `last_status` column — the
`--json` schema is unchanged.

## Staggering

Interval jobs have `slot` (see [schedule_contract.md](schedule_contract.md)) — declare the hour you want and the first fire lands on it. For the other types, seed different `last_run` values in `daemon_json/daemon_runstate.json`. Within a single tick, jobs that fire together are already separated by a fixed 1s sleep (`run.py`) — that is not configurable and is not a substitute for offsetting the schedules themselves.

