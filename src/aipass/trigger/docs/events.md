[<- Back to the README](../README.md)

# Events — what fires, what listens, and what only looks like an event

**Branch** trigger · **Code** `apps/handlers/events/`

`drone @trigger list` prints the live event and handler count; this page is the trigger and
the action behind each row, plus the rows that exist as vocabulary only.

---

**6 events, 6 handlers.** That is the live count and `drone @trigger list` prints it.
Registered via `handlers/events/registry.py` on first `Trigger.fire()`. All fire through
the event bus. Retired and decommissioned rows are kept and marked below, because those
files are still on disk.

| Event | Handler | Trigger | Action |
|-------|---------|---------|--------|
| `startup` | `startup.py` | **No production code fires it.** `log_watcher_service.main()` runs the same scan through `medic.run_error_catchup()`, a direct call that does not use the bus. `drone @trigger fire startup` reaches it by hand | Error catch-up scan over `system_logs/`, which is the whole handler. It does **not** check memory rollover. The scan fires `error_detected` for what it finds. See [error_catchup.md](error_catchup.md) |
| `error_detected` | `error_detected.py` | Error registered via log watcher or `report_error()` | Full 7-gate Medic dispatch — emails fix-it to affected branch + `wake_branch()` |
| `warning_logged` | `warning_logged.py` | Warning in branch or system logs | Feeds the escalation digest lane — counted by signature, never dispatched |
| `memory_template_updated` | `memory_template_updated.py` | **Nothing fires it.** No `fire("memory_template_updated")` call site exists in the fleet | **Stub — does nothing.** Writes one `json_handler` operation line and returns. Its own docstring claims it calls memory's `push_templates()`; there is no such import and no such call |
| `runaway_log_detected` | `runaway_handler.py` | Prax rate tracker detects sustained high log volume | Per-file cooldown dispatch to responsible branch; gated by VOLUME mutes only (CRITICAL bypasses); UNKNOWN attribution falls back to @prax; writes alert to `.aipass/alerts.json` |
| `memory_pool_auto_processed` | `memory_pool.py` | @memory's detached child at the point it finishes — `memory/apps/handlers/intake/auto_process.py`, `_fire_completion()` from `run_once()`, on both the success and the failure leg; a run that declines the lock announces nothing, because the holder announces its own | Logs result; on failure fires `error_detected` for Medic dispatch. `status` vocabulary is `ok` / `skipped` / `failed` / `unknown` — `unknown` means the section never reported, and an absent section must derive to it rather than to `ok`, or a crashed run announces that the pool completed — and `branch` must be a **registered** citizen — `__global__` is refused by gate 5 and the failure would be lost there. Both published in the handler docstring |

**Renamed events.** `DEPRECATED_EVENT_ALIASES` in `modules/core.py` resolves an old name in
`fire()`, `on()` and `off()` and logs a deprecation **once per name per process**. The table
is empty; the mechanism stays for the next rename.

`file_deleted` names a **real deletion**: @aipass `install.py` fires it when it removes
its install lock, @daemon `timer_install.py` after it unlinks a systemd unit. A failed
profile write fires `profile_write_failed` by name. (`plan_file_deleted` is a different
event.)

**Not wired — files on disk, deliberately unregistered:**

| Event | Handler | State |
|-------|---------|-------|
| `cli_header_displayed` | `.archive/cli.py` | **Retired** — still fired by cli's `header()` in `cli/apps/modules/display.py`, runs no handler here |
| `plan_file_created` | `.archive/plan_file.py` | **Retired** — still fired by @flow's registry scan, runs no handler here |
| `plan_file_deleted` | `.archive/plan_file.py` | **Retired** — same |
| `plan_file_moved` | `.archive/plan_file.py` | **Retired** — same |
| `bulletin_created` | `.archive/bulletin_created.py` | **Retired** — never imported |
| `pr_created` | `pr_status_sync.py` | **Decommissioned** — file kept, `trigger.on(...)` commented out in `registry.py` |
| `pr_merged` | `pr_status_sync.py` | **Decommissioned** — same |

**`error_logged` is not an event.** No handler file, no registration, and no
`Trigger.fire("error_logged")` anywhere in the fleet. The watchers fire `error_detected`
and `warning_logged`, and nothing else.

**Vocabulary with no handler.** `cli_header_displayed` and the three plan-file events are
still fired — cli from `display.py`, @flow from `handlers/registry/monitor_ops.py` — but
trigger runs no handler for them, and neither sender needs anything back. The reason each
is unwired is written beside it in `registry.py`. A fire into an empty handler list
reports `handlers: 0`, which is the honest answer and not an error.

---

## Related

- [event_bus.md](event_bus.md) — `fire`/`on`/`off`, handler isolation, per-handler data contracts
- [medic.md](medic.md) — the dispatch pipeline behind `error_detected`
- [error_catchup.md](error_catchup.md) — the catch-up scan behind `startup`
