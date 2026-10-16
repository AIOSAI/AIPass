---
name: system_status
description: Check system health -- disk usage, memory, running processes, uptime, battery
version: 2.3.0
tags: [system, monitoring, health]
requires:
  pip: [psutil]
  bins: []
  config: []
has_handler: true
---

# System Status Skill

Check system health metrics without leaving your workflow. Returns structured data about disk usage, memory, running processes, and system uptime.

## Available Actions

| Action      | Description                                    |
|-------------|------------------------------------------------|
| `disk`      | Disk usage for the root filesystem             |
| `memory`    | Memory and swap usage (psutil, portable)       |
| `uptime`    | System uptime from psutil's boot time          |
| `processes` | Count of processes (every pid the host lists)   |
| `battery`   | Charge, mains, state, time left (none is an answer) |
| `summary`   | All of the above combined into one report       |

## Published Function: `machine_vitals()`

An in-process read for callers that want data, not text - the host API's
`/v1/machine` route proxies it verbatim and BAUD's phone draws it (FPLAN-0561).

```python
from aipass.skills.lib.system_status import handler
vitals = handler.machine_vitals()
```

- `{"ok": True, "schema": 2, "sampled_at": ...}` plus nine sections: `cpu`,
  `load`, `memory`, `swap`, `temp`, `fan`, `network`, `processes`, `battery`
  (schema 1 had the first eight). Each carries
  `available`, `reason`, `sentence`, `detail` beside its values. Never raises
  for a reading; a value the host cannot give is `None`, never a zero.
- Whole-function refusal: `{"ok": False, "reason", "detail"}` with
  `psutil_missing` or `switched_off` (the off-switch is consulted, and an
  unreadable switch state fails closed).
- Reason codes (closed set, one sentence each in `REASONS`): `platform`,
  `no_sensor`, `no_allowlisted_sensor`, `read_failed`, `warming`, `no_range`,
  `switched_off`, `psutil_missing`.
- `cpu` carries `percent` and `window_s`, plus `cores` (busy percent per
  logical CPU, in index order), `logical` and `physical` (the counts) and `mhz`
  / `mhz_max` (frequency now and its ceiling). One `cpu_times(percpu=True)`
  sample per read: the headline is summed from the same per-CPU deltas as the
  cores, so the two agree. `percent` and `cores` are `None` while warming (and
  when the CPU count changed between samples); the counts and frequency are
  instant readings and are published even then. No frequency on a host is
  `None`, never `0`.
- CPU temperature and fans come from allowlists keyed by chip and label
  (`coretemp` / `Package id 0`; `applesmc` fans). The fan range is a read-only
  Linux sysfs read of `fanN_min` / `fanN_max`.
- `battery` carries `percent`, `plugged`, `state` (`charging`, `discharging`,
  `full` or `unknown`), `seconds_left`, `low` and `critical`. A host whose
  `psutil.sensors_battery()` answers `None` is `no_sensor`; a psutil without
  the function is `platform`. `seconds_left` is `None` on psutil's
  `POWER_TIME_UNLIMITED` / `POWER_TIME_UNKNOWN`, and `detail` names which.
  `state` is the kernel's `/sys/class/power_supply/BAT*/status` word on Linux
  when it is one of the three (any other word is `unknown`), else derived
  from `plugged` and `percent`. `low` / `critical` are UPower's
  `PercentageLow` / `PercentageCritical` from `/etc/UPower/UPower.conf` on
  Linux (UPower's 20 / 5 when the file leaves a key out); no file, or a
  time-based policy, is `None` - a face tones only against a line the host
  published.

The contract in full is in the branch README; it is pinned by
`tests/test_machine_vitals.py`.

## Published Function: `machine_processes(limit=20)`

The busiest processes on the host, for "the fan is loud and no agent is
running - what is?" (contract C-B, DPLAN-0414 theme 3).

```python
from aipass.skills.lib.system_status import handler
top = handler.machine_processes(20)
```

- `{"sampled_at", "window_ms", "total", "sort": "cpu", "processes": [...]}`;
  each row is `pid`, `name`, `cpu_pct`, `mem_pct`, `mem_mb`, `user`, `state`.
- The top `limit` (clamped to 1..100) by `cpu_pct`, ties by `mem_pct`.
  `cpu_pct` is a real ~0.5 s sample, normalised to the whole machine (a
  4-core box at full tilt sums to ~100, not ~400). `total` counts every pid.
- The process name only - never its command line, arguments, environment or
  working directory. A process that vanishes or is denied mid-sample is left
  out; an unreadable owner is `user: None`.
- Off, unreadable switch, or no psutil: the same refusal `machine_vitals()`
  answers.

## Usage

```bash
drone @skills run system_status disk
drone @skills run system_status memory
drone @skills run system_status uptime
drone @skills run system_status processes
drone @skills run system_status battery
drone @skills run system_status summary
```

## Output Format

All actions return structured dicts:

```python
{"success": True, "output": "...", "error": None}
```

## When to Use

- Quick health check before resource-intensive operations
- Diagnosing slow performance (memory pressure, disk full)
- Monitoring system state during long-running tasks
- Getting a snapshot of system health for reports

## Notes

- Disk usage uses `shutil.disk_usage()` -- stdlib, portable
- Memory, uptime and process count use `psutil` (`psutil>=5.9`, a declared
  dependency of this project), which answers them on Linux, macOS and Windows
- Until 2026-09-12 those three read `/proc` directly, so every one of them
  returned `success: False` on macOS and `summary` reported `success: True`
  over a disk line and an Errors trailer (FPLAN-0554)
- `summary` is `success: False` whenever any section fails, and `error` names
  the sections that are missing; the sections that did answer are still in
  `output`
- On a host without psutil the three actions refuse and name the install
  recipe -- they never answer a partial
