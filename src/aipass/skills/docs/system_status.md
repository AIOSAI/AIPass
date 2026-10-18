[← Back to the skills README](../README.md)

# The system_status Skill

The portable readings, and the two published dicts the host API relays and the phone monitor draws: `machine_vitals()` and `machine_processes()`.

## The Portable Readings

Disk comes from `shutil.disk_usage`; memory, uptime and the process count ask
**psutil** — `virtual_memory()`, `boot_time()`, `pids()` — a declared
dependency of this project (`psutil>=5.9`) that answers on Linux, macOS and
Windows. Two things that are not obvious:

- **`summary` fails when a section fails.** It returns `success: False` with
  `error` naming the missing sections, and still hands back the sections that
  did answer.
- **No psutil means a refusal, not a partial.** The three psutil actions return
  `success: False` naming the install recipe; `disk` still answers.

The macOS half is manufactured on Linux in `tests/test_runner.py`, and the
psutil stand-in is part of the world rather than a shortcut around it: psutil's
*Linux* backend reads `/proc` through plain `open()`, so denying `/proc` with
the real psutil in place would manufacture a failure no Mac can have — there
psutil answers from the kernel. The world is `sys.platform == "darwin"` + every
`/proc` read refused + a stand-in shaped like macOS's `virtual_memory` (no
`buffers`, no `cached`), with three controls: the denial is live, the denial
can still say yes, and the process table is gone too.

**What the audit reads.** The per-file audit corpus is `apps/` (plus `tests/`
for the branch-level arms); `lib/`, where the built-in skills live, joins it
for `host_portability` only. Tier-2 `handler.py` files are not scored for
architecture.

## machine_vitals() — The Published Read

`lib/system_status/handler.py` publishes `machine_vitals()`: one dict of the
machine's vitals for in-process callers. The
host API proxies it verbatim on `/v1/machine` and BAUD's phone draws it. The meaning lives here and nowhere downstream — which
sensor is the CPU, which rows are nonsense, what an absence is called.

```python
from aipass.skills.lib.system_status import handler
vitals = handler.machine_vitals()
```

- **Shape.** `{"ok": True, "schema": 2, "sampled_at": <ISO-8601 UTC>}` plus
  nine sections: `cpu`, `load`, `memory`, `swap`, `temp`, `fan`, `network`,
  `processes`, `battery`. Every section carries `available`, `reason`,
  `sentence` and `detail` beside its own values, and every value key is always present — `None`
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
| `platform` | The OS has no such reading. psutil defines `sensors_temperatures` and `sensors_fans` only on Linux (temperatures also on FreeBSD); load on Windows is emulated and reads 0 until warm, so it is not drawn; `sensors_battery` exists on Linux, Windows, macOS and FreeBSD only |
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
  `mhz_max`, the frequency now and its ceiling from `cpu_freq()`.
  One read takes **one** sample, `cpu_times(percpu=True)`, and the headline
  percent is summed from the same per-CPU deltas as the cores — 3 busy seconds
  of 5 ticked is 60, where the mean of the bars would say 37.5 — so the
  headline and the bars agree by construction. Guest time comes back out of
  each total and iowait is idle. `percent` and `cores` are `None` while warming, and also when the CPU count changed between
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
  applesmc temperature row stays off — on a MacBook, five read -127 and others
  drift by several degrees inside minutes — and so does `BAT0`, a battery. Keyed by chip and label, never by position; growing
  a list is a change to `TEMP_ALLOWLIST` / `FAN_ALLOWLIST`, never to a face.
- **The fan range is a read-only sysfs read, Linux only.** psutil reports a
  fan's label and rpm, not its range. The chip is found by the `name` file beside
  its fan input — never a `hwmonN` index, which is boot order — walking the
  directories the way psutil does (on an applesmc MacBook `hwmonN/name` may not
  exist and the name is at `hwmonN/device/name`). It opens `name`, `fanN_label`,
  `fanN_min` and `fanN_max`, read-only, and nothing else: `fanN_manual` and
  `fanN_output` are root-writable and never opened. `percent_of_range` is
  clamped to 0–100 and the range is carried beside it, so a fan sitting at its
  floor (0%, as an idle MacBook fan does) is distinguishable from a fan with no scale.
- **The battery section** carries `percent`, `plugged`, `state`, `seconds_left`,
  `low` and `critical`; its full contract is in
  [`lib/system_status/SKILL.md`](../lib/system_status/SKILL.md).
- **Cost:** about 19 ms warm, 12 ms of it psutil's own temperature sweep; the
  fan range adds about 2 ms, and the per-CPU sample, the counts and the
  frequency add under 1 ms.

## machine_processes() — The Busiest Processes

`machine_processes(limit=20)` sits beside `machine_vitals()`, behind the same
switch and the same refusal. It lists the top `limit` processes (clamped to
1..100) by a real ~0.5 s CPU sample, normalised to the whole machine, ties by
memory percent; each row is `pid`, `name`, `cpu_pct`, `mem_pct`, `mem_mb`,
`user`, `state`. It reads the process name only — never the command line,
arguments, environment or working directory — and leaves out a process that
vanishes or is denied mid-sample. The host API relays it on
`/v1/machine/processes`. The shape is in
[`lib/system_status/SKILL.md`](../lib/system_status/SKILL.md).

## The Pins

`tests/test_machine_vitals.py` pins both doors against stand-ins only: psutil,
the monotonic clock, the sample's sleep and the hwmon tree are all
manufactured, so the file is green on a host with no sensor chips. The
read-only pin records every `open`, `io.open` and `os.open` under the tree and
raises on a write mode or a fan control file, with a control proving the guard
is armed and can still say yes. The stand-in psutil is four logical CPUs with
different loads, CPU 2 spending half its idle time in iowait, and the Windows
field set (no guest, no iowait) is manufactured beside it. The text actions
are pinned in `tests/test_runner.py`.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
