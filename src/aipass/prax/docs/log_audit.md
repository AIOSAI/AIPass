# log_audit and log_health — size, growth, rotation

Log health summaries, runaway-growth rates, truncation, and the weekly tmp sweep the daemon runs.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## Log Audit

```bash
drone @prax log-audit                    # Show audit module info
drone @prax log-audit audit              # Scan system_logs/ for health + oversized files
drone @prax log-audit enforce            # Truncate oversized logs to 1000 lines
drone @prax log-audit sweep              # Delete log files older than 30 days
drone @prax log-audit --help             # Audit usage
```

`audit` reports problems but always exits 0 — it flags unbounded and critical
files in its output, so a health gate must read the text, not `$?`.

## Log Health

```bash
drone @prax log-health                   # Show module info
drone @prax log-health scan              # Scan all log files, show current growth rates
drone @prax log-health snapshot          # Show last known rates (no new scan)
drone @prax log-health --help            # Log health usage
```

Quick overview of log file growth rates across `system_logs/`. Powered by the rate tracker handler — `scan` runs a fresh measurement, `snapshot` reads the last persisted state without scanning.

`snapshot` reports what the last scan measured, including which process
measured it: the rate history is persisted, so a CLI invocation can read rates
collected by the long-running Mission Control service. Restored samples are
trimmed to the deque's own horizon (`_RATE_HISTORY_SIZE × SCAN_INTERVAL` =
5 min), so a tracker that was down for hours cannot feed stale history into the
runaway-threshold window. When nothing recent exists, `snapshot` says
**"No recent measurements"** rather than rendering every file as idle — an
all-zero screen would otherwise be indistinguishable from a genuinely quiet
fleet.

## Scheduled job — the weekly tmp sweep (DPLAN-0338, 2026-09-11)

prax owns one daemon job, in `.daemon/schedule.json`: **`tmp-sweep-weekly`**.
It is a *command* job, so the daemon tick runs it as a subprocess from this
directory. No agent is woken and no tokens are spent.

```
drone rm --stale 10d ..        # '..' from src/aipass/prax is src/aipass
```

- **What it sweeps.** Regular `*.tmp` files sitting directly inside any `*_json`
  folder under `src/aipass`, with an mtime more than 10 days old. Nothing else.
  The one call covers every branch's json folder: drone crosses its
  sibling-branch fence in stale mode only, by design, because a stale staging
  temp is nobody's work. A staged write is temp + fsync + rename, and a process
  killed between the two leaves the temp behind. The real document is intact
  whatever happens to it.
- **When.** Weekly, Sunday 04:00 local. That is the quiet hour, clear of
  @seedgo's Sunday 03:00 shadow cycle and @daemon's 09:00. The slot is
  `2026-09-13T04:00:00`. The tick seeded the runstate row from it at 13:31 on
  09-11 (`last_run` 09-06 04:00, first fire 09-13 04:00), so the job never fires
  at whatever minute a tick first discovers it. A Sunday missed while the
  machine was off fires on the first tick after it is back.
- **Where it shows.** The `FIRE` and `DONE` lines (exit code, duration, output
  tail) in daemon's `logs/run.log` and in `~/.aipass/daemon-tick.log`. The
  runstate row `@prax/tmp-sweep-weekly` in `daemon/daemon_json/daemon_runstate.json`.
  One row per deleted file in `.ai_central/deletions.jsonl` (`mode: stale`,
  `age: 10d`). A mail to @devpulse when the sweep starts and another when it
  finishes. `drone @daemon queue` lists it; `--json` carries
  `command: drone rm --stale 10d ..` as the preview.
- **Changing it.** To change the age, edit the command string (`10d` → `5d`;
  `m`/`h`/`d` are accepted, zero is refused). To turn it off, set
  `enabled: false`. `timeout_seconds` is 120 because a command job holds the
  tick lock for its whole run.

**The first sweep, run by hand 2026-09-11 13:32.** The dry run printed
`folders scanned 1539, files matched 706 (35602375 bytes)`. The real run deleted
all 706, freed 35.6 MB, refused 0 and added 706 ledger rows. `*.tmp` under
`src/aipass/*/*_json` went from 1170 to 466. Every file deleted was an old-era
`tmpXXXX.tmp` from the retired handler. The 466 left are younger than 10 days
and age in week by week. The run took **39 s wall**; a dry run with nothing to
delete takes 1.2 s. So the cost is about 54 ms per deleted file, because each one
writes a ledger row and a log line. At that rate 120 s covers about 2,100 files a
week. A timeout marks the row FAILED but keeps whatever it already deleted.

**Where the orphans come from (measured 2026-09-11, cured 2026-09-12).** Each
new-era `.<pid>_<n>.tmp` still holds the document it was staging, so its content
names the writer. Of the 442 in `prax_json/` (09-04 to 09-11), **384 (87%)**
were staging one record: `discovery_watcher_event` with `action: started`. That
is the last line of `start_file_watcher()` (`handlers/discovery/watcher.py:234`).
Since 2026-09-04 it runs on `prax-watcher-start`, the daemon thread nobody joins
(see "The watcher start does not block the first log line"). A short-lived
process such as a hook logs once and exits while that thread is still walking or
writing, and interpreter exit kills a daemon thread wherever it stands, between
temp and rename included. That dates the rise DPLAN-0338 calls "cause unknown"
to this move: about 5 a day in the old era, 18 to 73 a day since 09-04. The
files come from 439 distinct pids, so it is one death per process, not one bad
process. The rest: 28 empty or partial,
`jsonl_append` 16, `introspection_resolved` 9, `direct_log_created` 3,
`config_loaded` 2. On 09-11 the count jumped
to 174 in 13 hours. 57 of those 174 are the FPLAN-0542 data-leg bump staging the
same `started` record. That bump added a second staged write to every
`log_operation`, so each dying process now has two windows instead of one. The
strip DPLAN-0338 leaves open (the creation-time records) is aimed at
`introspection_resolved`, and by this count that is one of the smallest
writers. **The cure (DPLAN-0339 step 1, 2026-09-12).** The `started` record is gone from
`start_file_watcher()`. It had no reader — not in production, not in the tests,
nowhere in the fleet — so nothing was traded away for it. The numbers that
convicted it, re-measured on HEAD `d6deeb42`: the walk thread finishes at
**0.431-0.440 s** wall (CPU 0.133 s, so 70% of it is GIL waiting) and a
short-lived process exits at **0.394-0.433 s**, which means the record was
written inside its own destruction window on every process, every time. Removing
the one `log_operation` call removes both staged writes, because the data-leg
bump rides on it.

Proof, 240 throwaway processes each side under `AIPASS_TEST_LOG_DIR` with the
live tree untouched: **6 orphans before, 0 after** — and `watcher_log.json` came
through all 240 with its mtime unchanged, so the record is not merely unobserved,
it is never written. The after-run carried *higher* load than the before-run
(7.71 vs 3.71), so the race had more chance to fire, not less. First-log-line
cost is unchanged, as expected: this step is litter, not speed. The orphan rate
is load-dependent — the same 40-process run that gave 3 of 40 on 09-11 gave 0 of
40 on 09-12 before the change, because a slower first line pushes exit past the
0.43 s write. That is why the baseline here is 240 processes and not 40.

What is deliberately NOT in this step: the `died` record, `trigger.fire(
"startup")` on the first log line (94% of that line's cost), and the background
watcher start itself. Those are separate, separately ruled. The startup fire went
in step 3, immediately below; the other two are still open.

