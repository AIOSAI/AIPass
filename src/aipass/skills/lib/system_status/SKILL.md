---
name: system_status
description: Check system health -- disk usage, memory, running processes, uptime
version: 2.0.0
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
