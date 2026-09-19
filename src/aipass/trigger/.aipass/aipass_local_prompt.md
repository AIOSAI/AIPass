# TRIGGER Branch-Local Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

# Role
Event bus and error dispatch. Detect errors, fingerprint them, gate dispatch, tell the branch that owns the fault. I never fix another branch's code.

# Tree
Re-derived from the real tree 2026-09-15. Depth lives in docs/, indexed by README.md.
```
apps/
├── trigger.py              → entry point, auto-discovers modules/
├── config.py               → constants, atomic_write_json, json_file_lock, TrailLogger
├── log_watcher_service.py  → the systemd daemon: watchers + its own catch-up + reload sentinel
├── modules/
│   ├── core.py             → event bus: fire / status / list
│   ├── errors.py           → registry CLI: list, detail, suppress, resolve, stats, circuit-breaker
│   ├── medic.py            → medic CLI: on, off, status, mute, unmute, volume-mute
│   ├── escalation.py       → digest lane CLI: status, list, config
│   ├── branch_log_events.py → branch log watcher CLI: start, stop, status, reset
│   └── log_events.py       → system log watcher CLI: declines to observe by design
└── handlers/
    ├── error_registry.py   → SHA1 fingerprints, circuit breaker, suppression gate, backoff
    ├── error_reporter.py   → report_error() plus the source-fix email pipeline
    ├── escalation.py       → repeat-signature counting and the digest email
    ├── log_watcher.py      → the branch log watcher (watchdog, position tracking)
    ├── medic_state.py      → medic_state.json persistence
    ├── reload_sentinel.py  → restarts the service when handler code changes
    ├── repo_root.py        → find_repo_root(), the one dead-cwd-safe walk
    ├── service_control.py  → systemd unit install, start, stop; probes for systemctl first
    ├── cli/help_flags.py   → wants_help(): a help flag anywhere explains, never executes
    ├── json/               → json_handler shim (prax-owned service) + operator config_loader
    ├── events/             → registry.py wires the handlers on first fire
    │   ├── startup.py, error_detected.py, warning_logged.py, runaway_handler.py
    │   ├── memory_pool.py, memory_template_updated.py, cli.py
    │   └── pr_status_sync.py (decommissioned, kept on disk)
    └── watchers/log_watcher.py → system_logs reader; the observer is withdrawn, the reader stays
```
 - apps/extensions, apps/plugins, apps/integrations are spawn scaffolding this branch never adopted — no code runs in them.
 - Branch root also holds templates/ (the systemd unit template), trigger_json/ (runtime state, untracked), trigger_data.json (watcher positions), tests/, docs/, docs.local/, tools/, logs/, artifacts/, dropbox/.

# Key commands
 - `drone @trigger` — self-map; `drone @trigger --help` — the reference. Each module has its own `--help`.
 - `drone @trigger list` — live event table. `drone @trigger fire <event> [key=val]` — fire one by hand.
 - `drone @trigger errors list|stats|detail <id>|suppress <id>|resolve <id>` — the registry.
 - `drone @trigger medic status|on|off|mute @branch|unmute @branch` — dispatch control.
 - `drone @trigger escalation status|list|config` — the digest lane.
 - `drone @trigger branch_log_events status` — the watcher CLI reports THIS process, never the daemon.
 - `pytest` from this directory, or `python -m pytest src/aipass/trigger/tests` from the repo root.
 - `systemctl --user status trigger-log-watcher` — the live daemon, when the host has systemd.

# Dispatch pipeline
Sequential gates in handlers/events/error_detected.py, then one either/or. Depth: docs/medic.md.
 - medic enabled → branch not muted → count at least two → recipient is not the manager → branch is a registered citizen → circuit breaker closed → not suppressed and backoff elapsed.
 - The last two are the v2 path and need a fingerprint and a reachable registry; without them the handler takes the v1 arm instead (per-branch rate limit). They never both run.
 - Escalation counting happens before every gate. A mute stops dispatch; it must never stop the counting.

# Critical files
 - `trigger_json/medic_state.json` — medic state, muted branches, breaker.
 - `trigger_json/error_registry.json` — every tracked error.
 - `trigger_json/error_catchup.json` — catch-up cursor and processed hashes; one value the whole fleet writes.
 - `trigger_json/escalation_state.json` — repeat-signature counts and digest cooldowns.
 - `trigger_json/custom_config/trigger.config.json` — operator config, created on first read.
 - `trigger_data.json` at the branch root — watcher positions and dedup hashes.
 - Live state never sits on a `<module>_<config|data|log>.json` name: the fleet json service owns those and regenerates them. `trigger_config.json` and `trigger_data.json` inside `trigger_json/` are inert placeholders.

# Gotchas
 - `drone @trigger status` describes the CLI process you just started, so it always says Active False. `medic status` reads the service.
 - Mute yourself before build or edit work, or your own error lines dispatch back to you.
 - The event bus fire path must stay silent by default — logging on the hot path feeds the watcher its own output.
 - A fire into zero handlers returns handlers 0 and reads as success. Never wire recovery through an unlistened event.
 - The `.jsonl` trails under logs/ are deliberate: the branch watcher reads `*.log` only, so the lane cannot eat its own decisions.
 - The service holds its handlers for its whole life; the reload sentinel restarts it on a code change, and a hand-run process refuses to exit instead.
 - Event payload keys are per handler, not shared across siblings. Read the handler before firing by hand.

# Rules
 - Detect and dispatch; the owning branch fixes. No cross-branch file edits — mail the owner.
 - The registry is operational, not archival. Clear resolved entries regularly.
 - Suppression is real silence. Resolution is not: a resolved error that recurs is signal.
 - Severity follows design intent: a chosen behaviour is never logged at ERROR, or I mail the operator about my own decision.
