[← Back to AIPass](../../../README.md)

# Trigger

**Purpose:** Event bus and error dispatch for AIPass. Branches fire events and registered handlers react; Medic watches every branch log for errors, fingerprints what it finds, gates dispatch, and tells the branch that owns the fault.
**Module:** `aipass.trigger`
**Version:** 3.0.0
**Created:** 2026-03-07

---

## Quick Start

```bash
drone @trigger medic status                 # Medic state, the live watcher, every mute
drone @trigger errors list                  # Tracked errors
drone @trigger escalation status            # The repeat-signature digest lane
drone @trigger fire error_detected branch=api error_type=ImportError
```

---

## What It Does

- **Carries the fleet's events.** Any branch can fire an event and any branch can listen. A
  handler that raises never reaches the caller and never stops its siblings — and the fire
  reports how many handlers ran and how many failed, so a typo is visible where it is typed.
- **Detects errors nobody reported.** The log watcher reads every branch's logs and the
  shared system log directory, parses the prax line format, and turns an ERROR line into a
  tracked error with a fingerprint.
- **Dispatches the fault to its owner** through a pipeline of sequential gates — medic
  enabled, branch not muted, second occurrence, not the manager, a registered citizen, the
  circuit breaker closed, backoff elapsed — then emails the branch and wakes it.
- **Escalates what stays broken.** A signature still repeating after its owner was told, or
  while a branch is muted, becomes one digest email to the operator. Warnings have no
  dispatch path at all, so repetition is the only signal they have.
- **Keeps the registry operational, not archival** — suppression is real silence, resolution
  is not, and both stay auditable.

It never fixes another branch's code: it detects, it tells the owner, and the owner fixes.

---

## Live Inventory

The list of modules and commands is **generated from the code that runs them**, so it is not
written down on this page and cannot go stale:

- `drone @trigger` — the self-map: every discovered module with its one-line description.
- `drone @trigger --help` — the command surface; each module's own `--help` for its verbs.
- `drone @trigger list` — the live event table: every registered event and its handler count.

---

## How To Reach Me

- Mail: `drone @ai_mail email @trigger "Subject" "Body"` — a dispatch you believe was wrong,
  an error attributed to the wrong branch, an event you want on the bus.
- Silence a false alarm rather than living with it: an error can be suppressed by fingerprint
  and a branch can be muted for a window, both from `drone @trigger medic --help`.
- A wrong attribution is a bug here, not a fault in your branch. Say which log line and which
  fingerprint, and it gets reproduced before anything is argued.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of the branch's own
help output rots the next time a verb lands. The generated surface is above under **Live
Inventory**, and it is always current.

---

## Architecture

Three layers. `apps/trigger.py` is a thin router: it discovers modules, hands the command to
the first one that claims it, and turns a refusal into an exit code. `apps/modules/` holds
one business-logic module per surface — `core` (the event bus), `errors` (the registry CLI),
`medic` (the dispatch toggle and the service door), `escalation` (the digest lane),
`branch_log_events` and `log_events` (the two watcher CLIs). `apps/handlers/` holds the
implementation, grouped by concern: the event handlers (`events/`), the watchers
(`log_watcher.py` and `watchers/`), the registry and reporter, the escalation counter, medic
state, the systemd unit and its reload sentinel, the operator-config and json shim (`json/`),
and the help-flag gate (`cli/`).

`apps/log_watcher_service.py` is the long-lived entry point behind the systemd user unit; it
starts the watchers, runs its own error catch-up through the medic module, and restarts
itself when handler code changes on disk. The suite runs from this directory with `pytest`,
and the count comes from `pytest -q` rather than from this page.

The full directory tree lives in this branch's own prompt
(`.aipass/aipass_local_prompt.md`) — one place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/event_bus.md](docs/event_bus.md) | `fire`/`on`/`off`, handler isolation, the deferred nested fire, the help-flag rule, `report_error()` |
| [docs/events.md](docs/events.md) | Every live event and its handler, the deprecated alias, the retired files, the names with nothing behind them |
| [docs/medic.md](docs/medic.md) | The dispatch pipeline gate by gate, suppression doctrine, the two mute classes, runaway gating |
| [docs/error_registry.md](docs/error_registry.md) | Fingerprinting, the circuit breaker, per-fingerprint backoff |
| [docs/escalation.md](docs/escalation.md) | The digest lane, what makes a signature, every operator knob |
| [docs/log_watching.md](docs/log_watching.md) | The two watchers, who owns the system log directory, twin dedup, branch attribution |
| [docs/error_catchup.md](docs/error_catchup.md) | The startup catch-up scan, and why the cursor moves only on a completed scan |
| [docs/service_and_reload.md](docs/service_and_reload.md) | The systemd user unit, the systemd probe, the reload sentinel |
| [docs/state_and_durability.md](docs/state_and_durability.md) | `trigger_json/`, the trio-filename doctrine, atomic writes and locking |
| [docs/known_issues.md](docs/known_issues.md) | Open defects with their measurements, and what the standards audit means here |

---

## Integration Points

### Depends On
- `aipass.prax` — logging through `system_logger`, and the fleet json service that
  `apps/handlers/json/json_handler.py` binds as a byte-identical shim
- `aipass.cli` — console output, refusal formatting and exit-code state
- `aipass.ai_mail` — `deliver_email_to_branch()` and the wake behind a dispatch (lazy import,
  graceful fallback)

### Provides To
- Every branch — the event bus (`Trigger.fire`, `Trigger.on`, `Trigger.off`)
- Every branch — cross-branch error reporting through `report_error()`
- Every branch — automated error dispatch, and the mutes that pause it while you build

---

**Last Updated:** 2026-09-15

---
[← Back to AIPass](../../../README.md)
