[<- Back to the README](../README.md)

# The startup catch-up, and when the cursor moves

**Branch** trigger · **Code** `apps/handlers/events/startup.py`, `apps/modules/medic.py` (`run_error_catchup`), `apps/handlers/watchers/log_watcher.py`

The catch-up covers the window in which no watcher was up. This page is who runs it, why the
cursor is held back when a scan does not complete, and what that costs.

---

The error catch-up scans `system_logs/` for `ERROR` lines that landed while no
watcher was up, and fires `error_detected` for each one so the registry and Medic
see it.

**The service runs it, once.** `log_watcher_service.main()` calls
`medic.run_error_catchup(trigger.fire)` **after** the watchers are up — through the
medic *module*, because the service is an entry point and entry points import modules,
not handlers (seedgo encapsulation rule 3). The order is deliberate: an error arriving
between the scan and the first watch would fall through a gap if the scan ran first,
whereas overlap is safe because the registry dedupes on fingerprint.

The call is a direct one and deliberately **not** `trigger.fire("startup")`: a
fire with no registered listener returns `handlers: 0` and reads as success, so
unwiring the handler would silence recovery without saying so. Prax fires
`file_watcher_died` into zero handlers today; this path must not join it.
`handle_startup` is the only listener on `startup`, and no production code fires
the event. A human can still fire it by hand with `drone @trigger fire startup`,
which is the generic `fire <event>` door and not a dependency.

**Why the service owns it.** `last_scan_timestamp` in `error_catchup.json` is ONE
value shared by every process in the fleet. Any other process that scans advances it,
and the window the service exists to cover is then already consumed. One owner, one
scan per service start.

**The cursor advances only on a completed scan.** `_scan_system_logs_for_errors`
returns a `ScanOutcome(errors, completed, reason)`. `completed` is True only when every
candidate file was read to its end; any scan limit — the time budget,
`MAX_ERRORS_PER_SCAN` — or a file skipped for exceeding `MAX_FILE_SIZE_BYTES` makes it
False, and `last_scan_timestamp` then stays where it was so the next run re-covers the
same window. Advancing on an aborted scan would put the unread files behind the new
cutoff, and their errors would be unrecoverable.

Two properties keep that safe rather than merely cautious:

- **Processed hashes are persisted either way.** They are what stops a re-covered
  window from re-dispatching errors already handled. Holding the cursor back
  while dropping the hashes would turn one abort into a duplicate storm.
- **The cost of holding it back is bounded by `MAX_LOOKBACK_HOURS`** (24), so the worst
  case is a 24-hour window instead of a one-minute one. A full-window scan costs tens of
  milliseconds more than a short one, which is why a permanently oversized file can be
  treated as "not completed" without inventing a softer second verdict for it.

The `startup_catchup` record in `trigger_json/startup_log.json` carries
`completed` and `reason` alongside `errors_found`, and a held cursor also writes
its reason to `logs/medic_suppressed.jsonl`. Without those, an operator cannot
tell "found nothing" from "never looked at half the tree" — at `errors_found: 0`
the two readings are identical.


---

## Related

- [log_watching.md](log_watching.md) — the watchers the catch-up hands off to
- [events.md](events.md) — `startup` and its single listener
- [service_and_reload.md](service_and_reload.md) — the service that calls the catch-up itself
