[<- Back to the README](../README.md)

# Events — what fires, what listens, and what only looks like an event

**Branch** trigger · **Code** `apps/handlers/events/`

`drone @trigger list` prints the live event and handler count; this page is the trigger and
the action behind each row, plus the rows that exist as vocabulary only.

---

**7 events, 7 handlers.** That is the live count and `drone @trigger list` prints it
(re-measured 2026-09-05). It read 10/10 until 2026-08-31, when the plan-file handler
was retired — see the plan-file note at the foot of this page.
Registered via `handlers/events/registry.py` on first `Trigger.fire()`. All fire through
the event bus.

This section said "16 events defined, 14 active" until 2026-08-25, and that was never true
in that shape. Three of the sixteen rows named handler files that **do not exist anywhere
under `trigger/`** — `error_logged.py`, `memory_threshold_exceeded.py`, `memory.py` — and
nothing in the fleet fires those three event names either. They were aspirations wearing a
handler column, and they are gone from the table below. Retired and decommissioned rows are
kept and marked, because those files are still on disk and the distinction is real.

| Event | Handler | Trigger | Action |
|-------|---------|---------|--------|
| `startup` | `startup.py` | First prax log call in **any** process (`prax` `logger.py:132`, in `_ensure_watcher()`) — **plus**, since 2026-09-12, an explicit call from `log_watcher_service.main()` that does not use the bus at all | Error catch-up scan over `system_logs/` — that is the whole handler. It does **not** check memory rollover; this table claimed it did until 2026-08-14. The scan fires `error_detected` for what it finds. See [error_catchup.md](error_catchup.md): the per-process fire is prax's and is scheduled for removal (DPLAN-0339 step 3), which is why the service now runs its own |
| `error_detected` | `error_detected.py` | Error registered via log watcher or `report_error()` | Full 7-gate Medic dispatch — emails fix-it to affected branch + `wake_branch()` |
| `warning_logged` | `warning_logged.py` | Warning in branch or system logs | Feeds the escalation digest lane — counted by signature, never dispatched |
| `memory_template_updated` | `memory_template_updated.py` | **Nothing fires it.** No `fire("memory_template_updated")` call site exists anywhere in the fleet (measured 2026-09-05) | **Stub — does nothing.** Writes one `json_handler` operation line and returns. Its own docstring claims it calls memory's `push_templates()`; there is no such import and no such call. The real build is planned in DPLAN-0318 |
| `cli_header_displayed` | `cli.py` | CLI displays headers | Registration hook |
| `runaway_log_detected` | `runaway_handler.py` | Prax rate tracker detects sustained high log volume | Per-file cooldown dispatch to responsible branch; gated by VOLUME mutes only (CRITICAL bypasses); UNKNOWN attribution falls back to @prax; writes alert to `.aipass/alerts.json` |
| `memory_pool_auto_processed` | `memory_pool.py` | @memory's detached child at the point it finishes — `memory/apps/handlers/intake/auto_process.py`, `_fire_completion()` from `run_once()`, on both the success and the failure leg; a run that declines the lock announces nothing, because the holder announces its own | Logs result; on failure fires `error_detected` for Medic dispatch. `status` vocabulary is `ok` / `skipped` / `failed` / `unknown` — `unknown` means the section never reported, and an absent section must derive to it rather than to `ok`, or a crashed run announces that the pool completed (found by @hooks 2026-09-05, cure is @memory's) — and `branch` must be a **registered** citizen — `__global__` is refused by gate 5 and the failure would be lost there. Both published in the handler docstring |

**Renamed — one release of grace:**

| Old name | Current name | State |
|---|---|---|
| — | — | **The table is empty.** `DEPRECATED_EVENT_ALIASES` in `modules/core.py` resolves an old name in `fire()`, `on()` and `off()` and logs a deprecation **once per name per process**; the mechanism stays for the next rename |

`file_deleted` names a **real deletion**: @aipass `install.py` fires it when it removes
its install lock, @daemon `timer_install.py` after it unlinks a systemd unit. A failed
profile write fires `profile_write_failed` by name. The alias that joined the two is
retired; its dated record is the comment above the table in `modules/core.py`.
(`plan_file_deleted` is a different event and is unaffected.)

**Not wired — files on disk, deliberately unregistered:**

| Event | Handler | State |
|-------|---------|-------|
| `plan_file_created` | `.archive/plan_file.py` | **Retired 2026-08-31** — still fired by @flow's registry scan, runs no handler here |
| `plan_file_deleted` | `.archive/plan_file.py` | **Retired 2026-08-31** — same |
| `plan_file_moved` | `.archive/plan_file.py` | **Retired 2026-08-31** — same |
| `bulletin_created` | `.archive/bulletin_created.py` | **Retired** — moved to `.archive/`, never imported |
| `pr_created` | `pr_status_sync.py` | **Decommissioned** (TDPLAN-0007) — file kept, `trigger.on(...)` commented out in `registry.py` |
| `pr_merged` | `pr_status_sync.py` | **Decommissioned** (TDPLAN-0007) — same |

**`error_logged` is a name with nothing behind it.** No handler file, no registration, and no
`Trigger.fire("error_logged")` anywhere in the fleet. Until 2026-09-15 it survived as *text*
in three places: a docstring in `handlers/watchers/log_watcher.py`, a docstring in
`startup.py`, and — worse, because a human reads it — a line in
`drone @trigger log_events --help` advertising it as a real event.
The watchers fire `error_detected` and `warning_logged`, and nothing else. That help text was
corrected at the source on 2026-09-15, which took the last of the three sites with it: the
fleet now carries the string in one place only, the line recording that it never existed.

**The plan-file events are vocabulary with no handler.** `plan_file_created`,
`plan_file_deleted` and `plan_file_moved` are still fired — @flow's
`handlers/registry/monitor_ops.py` fires all three from its registry scan (verified
2026-09-05) — but trigger runs no handler for them. `plan_file.py` was retired to
`apps/handlers/events/.archive/` on 2026-08-31 as measured inert: its
`_get_plan_number()` matched `FPLAN-(\d{4})\.md` only, which hit 1 of 366 real plan
filenames, and it wrote Flow's *legacy* `flow_json/PLAN_REGISTRY.json` after Flow had
moved to typed per-kind registries. The `trigger.on(...)` lines are gone from
`registry.py` with the reason written beside them. @flow needs nothing back, so the
events stay in the vocabulary and fire into an empty handler list — `fire()` reports
`handlers: 0`, which is the honest answer and not an error.

---

## Related

- [event_bus.md](event_bus.md) — `fire`/`on`/`off`, handler isolation, per-handler data contracts
- [medic.md](medic.md) — the dispatch pipeline behind `error_detected`
- [error_catchup.md](error_catchup.md) — the only listener on `startup`
