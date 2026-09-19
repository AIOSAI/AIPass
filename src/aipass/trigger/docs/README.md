[<- Back to the README](../README.md)

# trigger docs

Depth for the trigger branch — one file per module or handler group, each small enough to
read in one pass. The face is [../README.md](../README.md); the live inventory is
`drone @trigger` and `drone @trigger --help`. Open a page here when something breaks.

| Doc | What it covers |
|---|---|
| [event_bus.md](event_bus.md) | `fire`/`on`/`off`, handler isolation, the deferred nested fire, the help-flag rule, `report_error()` |
| [events.md](events.md) | Every live event and its handler, the deprecated alias, the retired and decommissioned files, the names with nothing behind them |
| [medic.md](medic.md) | The dispatch pipeline gate by gate, suppression doctrine, the two mute classes, runaway gating |
| [error_registry.md](error_registry.md) | Fingerprinting, the circuit breaker, per-fingerprint backoff |
| [escalation.md](escalation.md) | The repeat-signature digest lane, what makes a signature, every operator knob |
| [log_watching.md](log_watching.md) | The two watchers, who owns `system_logs/`, twin dedup, branch attribution, path classification |
| [error_catchup.md](error_catchup.md) | The startup catch-up scan and why the cursor only moves on a completed scan |
| [service_and_reload.md](service_and_reload.md) | The systemd user unit, the systemd probe, and the reload sentinel |
| [state_and_durability.md](state_and_durability.md) | `trigger_json/`, the trio-filename doctrine, the migration, atomic writes and locking |
