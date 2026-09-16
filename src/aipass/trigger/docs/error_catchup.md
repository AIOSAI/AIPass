# The startup catch-up, and when the cursor moves

**Branch** trigger · **Code** `apps/handlers/events/startup.py`, `apps/modules/medic.py` (`run_error_catchup`), `apps/handlers/watchers/log_watcher.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The catch-up covers the window in which no watcher was up. This page is who runs it, why the
cursor is held back when a scan does not complete, and what that costs.

---

The error catch-up scans `system_logs/` for `ERROR` lines that landed while no
watcher was up, and fires `error_detected` for each one so the registry and Medic
see it. Two things about it were wrong until 2026-09-12 (DPLAN-0339 step 2), and
both were found by re-measuring DPLAN-0298's August claims on live code.

**It reached the service by accident.** `_run_error_catchup` hangs off the
`startup` event, and the only thing in the fleet that fired `startup` was prax's
logger on the first log line of *every* process (`prax/apps/modules/logger.py:132`).
So `trigger-log-watcher.service` — the one long-lived process that exists to own
recovery — ran its catch-up as a side effect of its own first log line, exactly
like a two-second `drone` command did. `log_watcher_service.main()` now calls
`medic.run_error_catchup(trigger.fire)` itself, once, **after** the watchers are
up — through the medic *module*, because the service is an entry point and entry
points import modules, not handlers (seedgo encapsulation rule 3).
The order is deliberate: an error arriving between the scan and the first watch
would fall through a gap if the scan ran first, whereas overlap is safe because
the registry dedupes on fingerprint.

This is the prerequisite for step 3, where prax drops the per-process fire. Until
then both paths run; the second finds nothing because the scan dedupes on
persisted hashes.

The call is a direct one and deliberately **not** `trigger.fire("startup")`: a
fire with no registered listener returns `handlers: 0` and reads as success, so
unwiring the handler would silence recovery without saying so. Trigger has that
exact failure live elsewhere — prax fires `file_watcher_died` into zero handlers
— and this path must not join it. Pinned 2026-09-12: `handle_startup` is the **only** listener on
`startup` anywhere in the fleet, and `logger.py:132` the only production firer —
every other mention is documentation. A human can still fire it by hand with
`drone @trigger fire startup`, which is the generic `fire <event>` door and not a
dependency.

**Why that mattered more than tidiness.** `last_scan_timestamp` in
`error_catchup.json` is ONE value shared by every process in the fleet. At the
measured 5.1 fires/min, an unrelated hook or `drone` command advanced it seconds
before the service scanned, so the window the service exists to cover was usually
already consumed. Measured 2026-09-11: **0 of the last 100 catch-up runs found
anything.**

**The cursor now advances only on a completed scan** (row 12 of DPLAN-0298, open
since August). `_scan_system_logs_for_errors` returns a `ScanOutcome(errors,
completed, reason)`. `completed` is True only when every candidate file was read
to its end; any DPLAN-037 limit — the time budget, `MAX_ERRORS_PER_SCAN` — or a
file skipped for exceeding `MAX_FILE_SIZE_BYTES` makes it False, and
`last_scan_timestamp` then stays where it was so the next run re-covers the same
window. It used to advance unconditionally, which silently discarded the window
an aborted scan never reached: those files fell behind the new cutoff and their
errors were unrecoverable.

Two properties keep that safe rather than merely cautious:

- **Processed hashes are persisted either way.** They are what stops a re-covered
  window from re-dispatching errors already handled. Holding the cursor back
  while dropping the hashes would turn one abort into a duplicate storm.
- **The cost of holding it back is bounded by `MAX_LOOKBACK_HOURS`**, so the worst
  case is a 24-hour window instead of a one-minute one. Measured on this tree,
  363 files: **181 ms** cold against **161 ms** warm — a 20 ms difference. That
  bound is why a permanently oversized file can be treated as "not completed"
  without inventing a softer second verdict for it.

The `startup_catchup` record in `trigger_json/startup_log.json` now carries
`completed` and `reason` alongside `errors_found`, and a held cursor also writes
its reason to `logs/medic_suppressed.jsonl`. Without those, an operator cannot
tell "found nothing" from "never looked at half the tree" — at `errors_found: 0`
the two readings are identical.


---

## Related

- [log_watching.md](log_watching.md) — the watchers the catch-up hands off to
- [events.md](events.md) — `startup` and its single listener
- [service_and_reload.md](service_and_reload.md) — the service that calls the catch-up itself
