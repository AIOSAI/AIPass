[← Back to the skills README](../README.md)

# The system_status Skill

The portable readings, and `machine_vitals()` — the published dict the host API relays and the phone monitor draws.

## The system_status Skill Off Linux

`lib/system_status/handler.py` asked `/proc` three times — `meminfo`, `uptime`
and the process table — so on the macOS runner `memory`, `uptime` and
`processes` each answered `success: False` every run, and `summary` reported
`success: True` over a disk line plus an Errors trailer (FPLAN-0554, runs
34704362515 and 34707099650). The four cases in `tests/test_runner.py` carried
`skipif(sys.platform == "win32")`, a guard that named the one platform that was
never the problem.

All three now ask **psutil** — `virtual_memory()`, `boot_time()`, `pids()` —
which is a declared dependency of this project (`psutil>=5.9`) and answers on
Linux, macOS and Windows. Disk was always portable (`shutil.disk_usage`) and is
untouched. Two things that are not obvious:

- **`summary` fails when a section fails.** It returns `success: False` with
  `error` naming the missing sections, and still hands back the sections that
  did answer. The old shape put the failures in an `Errors:` trailer inside
  `output` and kept `success: True`, which is a caller reading a disk line as a
  system report.
- **No psutil means a refusal, not a partial.** The three actions return
  `success: False` naming the install recipe; `disk` still answers.

The macOS half is manufactured on this Linux box in `tests/test_runner.py`, and
the psutil stand-in is part of the world rather than a shortcut around it:
psutil's *Linux* backend reads `/proc` through plain `open()`, so denying
`/proc` with the real psutil in place would have manufactured a failure no Mac
can have — there psutil answers from the kernel. The world is
`sys.platform == "darwin"` + every `/proc` read refused + a stand-in shaped like
macOS's `virtual_memory` (no `buffers`, no `cached`), with three controls: the
denial is live, the denial can still say yes, and the process table is gone too.
Against the pre-cure handler 11 of these cases go red on behaviour; 8 mutants
were killed.

**Why the audit read 100 over it.** At the time the audit corpus was `apps/`
(plus `tests/` for the branch-level arms) and never entered `lib/`, where all
seven built-in skills live — so `Host_Portability` read **100** while the skill
was red on every macOS run. Reported the same morning; @seedgo ruled that `lib/`
joins the corpus **for `host_portability` only** (the per-file audit stays
`apps/`, so tier-2 `handler.py` files are not scored for architecture). The
widened rule scored this branch 97 — see [telegram.md](telegram.md).

## machine_vitals() — The Published Read

`lib/system_status/handler.py` publishes `machine_vitals()`: one dict of the
machine's vitals for in-process callers (FPLAN-0561 row 1; every clause was
ruled in DPLAN-0341). The host API proxies it verbatim on `/v1/machine` and
BAUD's phone draws it. The meaning lives here and nowhere downstream — which
sensor is the CPU, which rows are nonsense, what an absence is called.

```python
from aipass.skills.lib.system_status import handler
vitals = handler.machine_vitals()
```

- **Shape.** `{"ok": True, "schema": 1, "sampled_at": <ISO-8601 UTC>}` plus
  eight sections: `cpu`, `load`, `memory`, `swap`, `temp`, `fan`, `network`,
  `processes`. Every section carries `available`, `reason`, `sentence` and
  `detail` beside its own values, and every value key is always present — `None`
  when the host cannot give it, never a zero. It never raises for a reading: a
  call that raises costs its own section (`read_failed`), never its siblings.
- **Whole-function refusal** is `{"ok": False, "reason": ..., "detail": ...}`,
  and only for two codes: `psutil_missing` (detail is the install recipe) and
  `switched_off`. The off-switch is consulted inside the function, because this
  door is imported directly and never passes the runner's gate; an unreadable
  switch state fails closed, exactly as the runner does.
- **Reason codes** — a closed set, one sentence each in `REASONS`:

| Code | When |
|------|------|
| `platform` | The OS has no such reading. psutil defines `sensors_temperatures` and `sensors_fans` only on Linux (temperatures also on FreeBSD); load on Windows is emulated and reads 0 until warm, so it is not drawn |
| `no_sensor` | The function exists but reported nothing to read from |
| `no_allowlisted_sensor` | Chips were reported, none on the allowlist; `seen` names them |
| `read_failed` | The call raised; `detail` carries the error |
| `warming` | A rate needs two samples — the first call in a process |
| `no_range` | The fan's rpm is real, but its min/max is missing, unreadable, or not a range; `current` is still published, `range` and `percent_of_range` are `None` |
| `switched_off` | Refusal only |
| `psutil_missing` | Refusal only |

- **The cpu section carries the cores.** Beside `percent` and `window_s`:
  `cores`, one busy percent per logical CPU in index order; `logical` and
  `physical`, from `cpu_count()` and `cpu_count(logical=False)`; `mhz` and
  `mhz_max`, the frequency now and its ceiling from `cpu_freq()` (FPLAN-0586).
  One read takes **one** sample, `cpu_times(percpu=True)`, and the headline
  percent is summed from the same per-CPU deltas as the cores — 3 busy seconds
  of 5 ticked is 60, where the mean of the bars would say 37.5 — so the
  headline and the bars agree by construction. Guest time comes back out of
  each total and iowait is idle, the same accounting as before. `percent` and
  `cores` are `None` while warming, and also when the CPU count changed between
  the two samples (hotplug) or a CPU did not tick between them; the counts and
  the frequency are instant readings, so they are published even then. psutil's
  `/proc/cpuinfo` fallback reports the ceiling as `0.0` and an offline policy as
  all zeros: both are `None`. A `cpu_freq()` that raises (psutil's Linux reader
  raises `NotImplementedError` or `OSError` when a cpufreq file is missing)
  costs the frequency only — `mhz` is `None` and `detail` names the error, while
  the percent and the cores still answer. A host whose psutil has no
  `cpu_freq` at all gets `None` too.
- **The skill owns its baselines.** CPU percent and network rate come from
  `cpu_times()` and `net_io_counters()` samples held in this module, each with
  `window_s`. Never `psutil.cpu_percent(interval=None)`: its baseline is a psutil
  module global keyed by thread id, so any other caller in the process moves the
  window without saying so.
- **An allowlist, not a threshold.** CPU temperature is `coretemp` /
  `Package id 0` (the hottest `Core N` when there is no package row), with
  `high` and `critical` from the sensor. Fans come from `applesmc`. Every other
  applesmc temperature row stays off — on the MacBook this was built on, five
  read -127 and a pair drifted from -34.25 to -30.0 inside twenty minutes — and
  so does `BAT0`, a battery. Keyed by chip and label, never by position; growing
  a list is a change to `TEMP_ALLOWLIST` / `FAN_ALLOWLIST`, never to a face.
- **The fan range is a read-only sysfs read, Linux only.** psutil reports a
  fan's label and rpm, not its range. The chip is found by the `name` file beside
  its fan input — never a `hwmonN` index, which is boot order — walking the
  directories the way psutil does (on this box `hwmon2/name` does not exist and
  the name is at `hwmon2/device/name`). It opens `name`, `fanN_label`,
  `fanN_min` and `fanN_max`, read-only, and nothing else: `fanN_manual` and
  `fanN_output` are root-writable and never opened. `percent_of_range` is
  clamped to 0–100 and the range is carried beside it, so a fan sitting at its
  floor (0%, as it does here at idle) is distinguishable from a fan with no scale.
- **Cost, measured here:** about 19 ms warm, 12 ms of it psutil's own
  temperature sweep; the fan range adds about 2 ms, and the per-CPU sample,
  the counts and the frequency add under 1 ms (0.85 ms, 2026-09-13).

Pinned by `tests/test_machine_vitals.py`, 41 functions expanding to 57 cases,
against stand-ins only: psutil, the monotonic clock and the hwmon tree are all
manufactured, so the file is green on a host with no sensor chips. The
read-only pin records every `open`, `io.open` and `os.open` under the tree and
raises on a write mode or a fan control file, with a control proving the guard
is armed and can still say yes. 20 mutants, one per clause, all go red; the
per-core read added 17 more, all red, and 15 cases in the file fail against
the handler that read one aggregate. The stand-in psutil is four logical CPUs with
different loads, CPU 2 spending half its idle time in iowait, and the Windows
field set (no guest, no iowait) is manufactured beside it. The text
actions and their 29 `test_runner.py` functions are unchanged; making them
renderings of this dict is a later row.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
