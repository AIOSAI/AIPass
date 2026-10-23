[<- Back to the README](../README.md)

# Recovery and Catch-Up

How the scheduler detects a missed tick window, queues and drains catch-up wakes, and tells the truth about lost time without replaying it.

---

## Recovery after a gap

When the timer stops, nothing ticks, and no MISSED line can be written, because writing one
takes a tick. Recovery is how the scheduler notices the gap on its own once ticking resumes,
and tells the agents it wakes the truth about the time they lost.

The principle the header follows: **the system informs, the agent reasons.** The
header states facts about time and stops. It never tells the agent what to conclude
and it never replays history at it.

**The path a gap takes through a tick**

| Step | Where | What it does |
|------|-------|--------------|
| stamp | `recovery.record_tick` | `last_tick` written in a `finally`, so the stamp survives every early return |
| detect | `recovery.detect_gap` | gap wider than 30 min (~15 missed ticks); cause read from the host |
| enumerate | `recovery.enumerate_missed` | every `daily`/`rotation`/`hourly` window that both **opened and closed** inside the gap |
| queue | `recovery.queue_catch_up` | **one** entry per `@owner/job_id` carrying every missed instant, merged idempotently on re-detection |
| supersede | `recovery.drop_from_queue` | a job whose regular window arrives first drops its entry — the on-time wake still carries the missed list |
| drain | `recovery.drain_ready` | at most **one** catch-up in flight fleet-wide; the next goes when the previous completed, 60 min is the ceiling not the rhythm |
| inform | `recovery.scheduled_header` / `catch_up_header` | prepended to the prompt, filed to the target's `.daemon/last_wake_prompt.txt` **and** `daemon_json/last_wake_prompt.txt`, and logged to `run.log` |

**Cause is read from the host, or refused by name.** `psutil` first (it answers on every
host the code tolerates), `/proc/stat btime` second, then `BootTimeUnavailable` — never a guess,
because a guessed boot time becomes a confident false sentence in a citizen's wake
header.

| Boot time | Cause | What the sentence says |
|-----------|-------|------------------------|
| before the gap opened | `scheduler_stopped` | ticking stopped at X while the machine was up |
| inside the gap | `scheduler_stopped_then_rebooted` | ticking stopped at X, **and** the host booted at Y, inside the gap, after it had already opened |
| not readable | `unknown` | the cause could not be read from this host — the gap is still reported |

A gap can be **both** a stopped timer and a reboot, and a two-valued cause would report only
the reboot and hide the stop. There is no `machine_off` value, because boot-inside-the-gap
cannot be told apart from "shut down for the night" without positive evidence the host was up
during the gap, and no cross-platform source provides it — so the cause names what is **known**
and the sentence states both instants rather than picking a story.

**One catch-up, never a replay.** Ten days off is one wake carrying ten dates, not
ten wakes. The header ends with *do not replay each one*, because an agent handed ten dates
may otherwise reasonably try to do ten days of work. A refused fire retries after the
cooldown; three attempts and it is **parked at the tail of the queue, not dropped** — "we
could not reach this branch" and "this branch owed nothing" are not the same sentence.

**The queue is visible.** `drone @daemon queue` prints a Catch-up Queue under the job
table (owner, windows missed, oldest, cause, state, attempts) whenever anything is
owed, and `--json` carries it under an additive `catch_up_queue` key beside the three
original top-level keys and the eleven job fields, the frozen schema an outside reader parses.

**Where the wake transcript is filed.** Both places: the target branch's
`.daemon/last_wake_prompt.txt` **and** daemon's own `daemon_json/last_wake_prompt.txt`.
`.daemon/` is the scheduler's surface in every branch — the owner writes `schedule.json`
into it, the scheduler writes its outputs beside it — so this is the daemon's own artifact in
the daemon's own directory, not a cross-branch edit of somebody's code. Written atomically
(tmp then replace) so a branch waking mid-write never reads half a header, and fail-soft
**per destination** so a read-only external tree costs neither the local copy nor the wake.
The owner is resolved by **email** through discovery's roster, never by directory name: two
citizens can share a directory name across federated roots, and filing a wake under the
wrong one hands a citizen somebody else's instructions. ai_mail's `wake.py` writes the same
file for the tmux manager lane; this writer covers the headless scheduled lane.

**`RECOVERY_LANE_LIVE` (`runstate.py`) is `False`, and everything above is built but
NOT IN SERVICE.** While it is `False`, `catch_up` is opt-in (only an explicit
`"catch_up": true` turns it on), and there is no gap detection, no queue and no drain. The
systemd tick runs this **working tree** every two minutes, not a commit — an edit here is
production the moment it is saved — so nothing under the flag may be `True` at any moment
nobody is watching a tick. The flag is flipped only by a controlled live proof from
@devpulse's seat with the owner.

**Two refusals detect_gap owes the fleet:**

- **No `last_tick` is not a gap.** A runstate full of older instants (`last_run`,
  `last_success_at`, `next_run`) is the temptation; reaching for one invents an
  absence the fleet never had and queues catch-ups for windows nobody missed.
- **A boot that precedes the last tick did not cause the gap**, and the sentence has
  to *say* so rather than merely mention the instant — a boot named next to a gap
  reads as cause to anyone skimming it.

**Probes run against copies.** The live runstate is host state: never run the `run` verb
from a seat against it. Every experiment takes a `tmp_path` copy of the runstate and the
schedule file.
