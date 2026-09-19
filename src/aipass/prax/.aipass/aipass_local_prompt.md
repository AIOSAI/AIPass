# PRAX — Branch Prompt
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/prax/.aipass/aipass_local_prompt.md — Injected every prompt when in prax directory. -->

The logging and monitoring backbone. Every branch logs through prax — `from aipass.prax import logger`. Also real-time Mission Control, the branch dashboards, log audit, and the module registry.

# Inventory

 - `drone @prax` — the live self-map of discovered modules. Never hand-type this list anywhere.
 - `drone @prax --help` — the full command surface; every verb takes `--help` for its own reference.
 - Depth is in `docs/`, one file per module group, indexed from `README.md`. The README is the face for strangers, not your reference.

# Tree

```
prax/
├── __init__.py                 # Public API, lazy (PEP 562): logger, append_jsonl, json_handler
├── apps/
│   ├── prax.py                 # Entry point — discovers modules, routes commands, zero logic
│   ├── modules/                # One orchestrator per verb: logger, monitor, dashboard,
│   │                           #   status, log_audit, log_health, discover
│   ├── handlers/               # Implementation, never imported by other branches
│   │   ├── central/            # Reader for .ai_central/*.central.json
│   │   ├── cli/                # Help-flag detection, unknown-argument gate (pure predicates)
│   │   ├── config/             # Path resolution, log config, ignore patterns
│   │   ├── dashboard/          # Refresh, operations, limits, status, template push/diff
│   │   ├── discovery/          # Module scan, filters, the watcher
│   │   ├── json/               # The fleet json service + prax's own shim
│   │   ├── logging/            # Setup, rotation, introspection, override, direct logger, jsonl
│   │   ├── monitoring/         # Event queue, branch detect/scope, log watcher, rate tracker,
│   │   │                       #   filters, commons feed, telegram relay, instance lock, pid cache
│   │   ├── registry/           # Module registry load/save
│   │   ├── status/             # STATUS.md sync handler
│   │   └── watcher/            # Background system watchers
│   ├── plugins/                # devpulse_dashboard: git, session and dispatch sections
│   └── integrations/           # Per-integration prompt and config
├── templates/                  # DASHBOARD.template.json — the dashboard schema
├── prax_json/                  # Auto-created per-module config/data/log triplets
├── .daemon/schedule.json       # Daemon jobs: the weekly tmp sweep, the daily module scan
├── docs/                       # The depth, indexed from README.md
└── tests/                      # pytest tests/ from branch root
```

# Logging system

 - Canonical import: `from aipass.prax import logger`. Works from any branch, no setup call.
 - Direct logger: `from aipass.prax.apps.modules.logger import get_direct_logger` — for prax internals inside watchdog threads or the import chain, where the stack walk would recurse.
 - Auto-routing by stack introspection: caller's module, branch and file path decide the destination.
 - Two-tier placement: `system_logs/<branch>_<module>.log` central, `<branch>/logs/<module>.log` local. Both rotate by size.
 - Env override before the stack walk: `AIPASS_LOG_NAME` or `AIPASS_BOT_ID`, for shared base classes that would otherwise all log as one caller.
 - Projects outside AIPass get their own `system_logs/` and `logs/` under their own root.
 - Self-healing: missing directories are created, an unknown caller falls back and says so, and a failed prax import hands back a NullLogger rather than taking the caller down.

# Critical rules

 - Prax is the only logging system. No branch runs its own setup.
 - Infrastructure only — no application logic, no alerting on log content beyond growth rate.
 - No cross-branch file edits. Issue in another branch's code? Mail the owner.
 - Handlers are internal. Other branches import `aipass.prax` or `aipass.prax.apps.modules.*` and nothing deeper.
 - Dashboards are generated. Services update their own section through `write_section()`, never by editing the file.
 - Caps other branches read are constants, not numbers to copy: `SUBJECT_CAP`, `DASHBOARD_CHAR_BUDGET` in `apps.modules.dashboard`, contract in `docs/dashboard_caps.md`.

# Gotchas

 - A refresh rebuilds each dashboard from the template and carries only `sections` forward. A top-level key another branch added is dropped on the next refresh.
 - `sections.flow` has two writers, prax's refresh and flow's push, and both assign it wholesale. A change on one side alone is undone by the other side's next write.
 - `monitor run` is not single-instance. The instance lock guards the Telegram relay only, so several Mission Controls can run at once, each adding its own watches.
 - Mission Control's interactive prompt answers `help` and `status` only. Branch selection is launch-time. The commons feed mode is the exception: it takes `filter <room>` and `filter clear` live.
 - Discovery is a scheduled scan, not a per-process watcher: a log line starts nothing. The registry never prunes, so entries can name files that no longer exist.
 - The `AIPASS_TEST_LOG_DIR` seam redirects what the json service writes by module name. It does not reach module-level path constants in the config and registry handlers, so a registry save under a suite writes the live file.
 - Trigger is optional and every import site is guarded. The logging path fires no events at all; the lifecycle doors and the discovery watcher do.
 - An unknown verb or flag exits 1 with the token named on stderr. Asking for help never performs the action.
 - inotify runs out quietly; the watchers fall back to polling and keep working, slower.

# Integration points

 - Every branch logs through prax; every branch reads a dashboard prax refreshes.
 - Dashboard refresh reads `*.central.json` from `.ai_central/`, owned by ai_mail and flow.
 - Depends on `aipass.cli` for formatting and `watchdog` for filesystem events. Drone is not an import: prax parses the caller marker drone writes into log lines.
 - `drone @prax dashboard push-template` syncs the dashboard schema to every branch.

# Tests

Run `pytest tests/` from the branch root; `drone @seedgo audit aipass @prax` for standards. New test files are gated — extend an existing file, or mail @devpulse with the defect the new file would pin. Conventions and fixtures: `docs/tests.md`.
