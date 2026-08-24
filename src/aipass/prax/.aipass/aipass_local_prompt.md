# PRAX — Branch Prompt
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/prax/.aipass/aipass_local_prompt.md — Injected every prompt when in prax directory. -->

The logging and monitoring backbone. Every branch logs through prax — `from aipass.prax import logger`. Also provides real-time Mission Control, dashboard infrastructure, and log audit.

# Commands

```
drone @prax                              # Self-map (discovered modules)
drone @prax monitor run                  # Launch Mission Control (all branches)
drone @prax monitor run seedgo,cli       # Monitor specific branches
drone @prax dashboard refresh --all      # Refresh all branch dashboards
drone @prax dashboard refresh @flow      # Refresh a specific branch
drone @prax log-audit audit              # Scan system_logs/ health
drone @prax log-audit enforce            # Truncate oversized logs
drone @prax status                       # System health
drone @prax --help                       # Full command reference
```

# Architecture

 - `apps/prax.py` — entry point. Auto-discovers modules in `apps/modules/`, routes commands. Zero business logic.
 - `apps/modules/` — 5 command modules: `logger`, `monitor`, `dashboard`, `status`, `log_audit`. Each a thin orchestrator over its handlers.
 - `apps/handlers/` — 11 handler directories. Implementation details, never imported by external branches.
 - `prax_json/` — auto-created per-module config/data/log files.
 - `templates/` — dashboard template schema (`DASHBOARD.template.json`).
 - Full tree in README.

# Logging System

 - Canonical import: `from aipass.prax import logger`. Works from any branch.
 - Direct logger: `from aipass.prax.apps.modules.logger import get_direct_logger` — for prax internals in watchdog threads or import chain.
 - Auto-routing via stack introspection: detects caller's module, branch, file path.
 - Two-tier placement: `system_logs/<branch>_<module>.log` (central) + `<branch>/logs/<module>.log` (local).
 - Self-healing: auto-creates missing dirs, warns on fallback, never crashes the caller.
 - Env var override: `AIPASS_LOG_NAME` or `AIPASS_BOT_ID` checked before stack walk for shared-base-class disambiguation.
 - External project routing: projects outside AIPass get their own `system_logs/` + `logs/` under their project root.

# Critical Rules

 - Prax is the only logging system. No branch runs its own logging setup.
 - Prax is infrastructure only — no application logic.
 - No cross-branch file edits. Issue in another branch's code? Email the owner.
 - Handlers are internal — external branches import only from `aipass.prax` or `aipass.prax.apps.modules.*`.
 - Dashboard files are auto-generated (`DASHBOARD.local.json`). Services update via `write_section()` API or central file refresh.

# Monitor — Mission Control

 - 3-thread architecture: display worker, file watcher (watchdog), log watcher (tails system_logs).
 - Multi-CLI: monitors Claude Code JSONL and Codex JSONL sessions. Model tags + caller attribution.
 - Polling fallback when inotify watches are exhausted.
 - Soft start: seeks to EOF, only shows new activity after launch.

# Integration Points

 - All branches log through `from aipass.prax import logger`.
 - Dashboard refresh reads `*.central.json` from `.ai_central/` (managed by ai_mail, flow).
 - Depends on: `aipass.cli` (formatting), `aipass.drone` (caller markers), `watchdog` (filesystem events).
 - `drone @prax dashboard push-template` syncs template schema to all branches.

# Tests

901 tests across 19 files. Run with `pytest tests/` from branch root. See README for per-file breakdown.
