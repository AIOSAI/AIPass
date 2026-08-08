# TRIGGER Branch-Local Context

## Role
Event bus + error dispatch. Detect errors, fingerprint them, gate dispatch, notify affected branches.

## Architecture
```
trigger.py (entry point — auto-discovers modules/)
├── core.py        → Event bus: fire/on/off/status (14 events, 14 handlers)
├── errors.py      → Error registry CLI: list/detail/suppress/resolve/stats/circuit-breaker
├── medic.py       → Medic toggle: on/off/status/mute/unmute
├── log_events.py  → Centralized log watcher (system_logs/)
└── branch_log_events.py → Branch log watcher (*/logs/*.log)

handlers/
├── error_registry.py  → SHA1 fingerprinting, circuit breaker, exponential backoff
├── error_reporter.py  → report_error() public API + source fix email pipeline
├── medic_state.py     → Persistence (medic_state.json)
├── log_watcher.py     → Watchdog-based branch log watcher with position tracking
├── events/            → 12 event handlers (registry.py wires them on first fire)
└── watchers/          → Centralized log watcher (system_logs/)
```

## Key Commands
```
drone @trigger fire <event> [key=val]    # Fire event
drone @trigger list                      # Show registered handlers
drone @trigger errors list               # View error registry
drone @trigger errors stats              # Registry + circuit breaker stats
drone @trigger medic status              # Medic state
drone @trigger medic on|off              # Toggle dispatch
drone @trigger medic mute|unmute @branch # Per-branch control
drone @trigger branch_log_events status  # Log watcher state
```

## Dispatch Pipeline (8 gates)
1. Medic enabled → 2. Branch not muted → 3. Count >= 2 → 4. Not DEV_CENTRAL
5. Branch in registry → 6. Circuit breaker closed → 7. Per-fingerprint backoff → 8. Rate limit

## Critical Files
- `trigger_json/medic_state.json` — medic state, circuit breaker, muted branches
- `trigger_json/error_catchup.json` — startup catch-up position + processed hashes
- `trigger_json/error_registry.json` — all tracked errors
- `trigger_data.json` — log watcher positions, dedup hashes

Live state never uses a `<module>_<config|data|log>.json` name — json_handler
owns those and regenerates them from a template. `trigger_config.json` and
`trigger_data.json` in `trigger_json/` are inert placeholders, NOT live state.

## Integration Points
- **ai_mail**: `deliver_email_to_branch()` dispatch + source fix emails
- **prax**: Logger (`from aipass.prax import logger`), prax monitor live log watching
- **AIPASS_REGISTRY.json**: Branch validation, dispatch targets

## Rules
- Never fix errors other branches — detect + dispatch, they fix their own
- Hot path logging poison — event bus fire() must be silent default
- Error registry operational, not archival — clear resolved entries regularly
