[<- Back to the README](../README.md)

# log_audit and log_health — size, growth, rotation

Log health summaries, runaway-growth rates, truncation, and the weekly tmp sweep the daemon runs.

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

## Scheduled job — the weekly tmp sweep

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
  `2026-09-13T04:00:00`, a Sunday. A never-run job is seeded from the slot, so
  the job never fires at whatever minute a tick first discovers it. A Sunday
  missed while the machine was off fires on the first tick after it is back.
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
- **Cost.** About 54 ms per deleted file, because each one writes a ledger row
  and a log line; a sweep with nothing to delete takes about 1 s. 120 s covers
  about 2,100 files a week. A timeout marks the row FAILED but keeps whatever it
  already deleted, and the next week finishes the rest.
