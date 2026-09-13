---
name: system_status
description: Check system health -- disk usage, memory, running processes, uptime
version: 2.1.0
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
| `processes` | Count of currently running processes            |
| `summary`   | All of the above combined into one report       |

## Published Function: `machine_vitals()`

An in-process read for callers that want data, not text - the host API's
`/v1/machine` route proxies it verbatim and BAUD's phone draws it (FPLAN-0561).

```python
from aipass.skills.lib.system_status import handler
vitals = handler.machine_vitals()
```

- `{"ok": True, "schema": 1, "sampled_at": ...}` plus eight sections: `cpu`,
  `load`, `memory`, `swap`, `temp`, `fan`, `network`, `processes`. Each carries
  `available`, `reason`, `sentence`, `detail` beside its values. Never raises
  for a reading; a value the host cannot give is `None`, never a zero.
- Whole-function refusal: `{"ok": False, "reason", "detail"}` with
  `psutil_missing` or `switched_off` (the off-switch is consulted, and an
  unreadable switch state fails closed).
- Reason codes (closed set, one sentence each in `REASONS`): `platform`,
  `no_sensor`, `no_allowlisted_sensor`, `read_failed`, `warming`, `no_range`,
  `switched_off`, `psutil_missing`.
- CPU temperature and fans come from allowlists keyed by chip and label
  (`coretemp` / `Package id 0`; `applesmc` fans). The fan range is a read-only
  Linux sysfs read of `fanN_min` / `fanN_max`.

The contract in full is in the branch README; it is pinned by
`tests/test_machine_vitals.py`.

## Usage

```bash
drone @skills run system_status disk
drone @skills run system_status memory
drone @skills run system_status uptime
drone @skills run system_status processes
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
