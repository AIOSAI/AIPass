[<- Back to the README](../README.md)

# The error registry

**Branch** trigger · **Code** `apps/handlers/error_registry.py`, `apps/handlers/error_reporter.py`, `apps/modules/errors.py`

The verbs are in `drone @trigger errors --help`; `drone @trigger errors stats` prints the
live registry and breaker state. This page is the model behind them.

---

SHA1 fingerprinting for error deduplication. Tracks: fingerprint, branch, error type, message, count, first/last seen, dispatch history, source fix status.

**Circuit breaker:** Trips after 10 errors within 60 seconds. Rejects all dispatch while open. Auto-resets after 300s cooldown. State persists across restarts in `trigger_cb_state.json`.

**Per-fingerprint tracking:** Each unique error has independent exponential backoff and dispatch count. State persists across restarts.


The registry is **operational, not archival**: resolved entries are meant to be cleared
regularly, and a purge verb exists for the stale ones. Nothing here is a long-term record —
that is @memory's job.

---

## Related

- [medic.md](medic.md) — the suppression doctrine and the gates that read this state
- [event_bus.md](event_bus.md) — `report_error()`, the cross-branch entry point
- [state_and_durability.md](state_and_durability.md) — how these files survive a crash
