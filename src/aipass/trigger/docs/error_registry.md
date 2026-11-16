[<- Back to the README](../README.md)

# The error registry

**Branch** trigger · **Code** `apps/handlers/error_registry.py`, `apps/handlers/error_reporter.py`, `apps/modules/errors.py`

The verbs are in `drone @trigger errors --help`; `drone @trigger errors stats` prints the
live registry and breaker state. This page is the model behind them.

---

SHA1 fingerprinting for error deduplication. Tracks: fingerprint, branch, error type, message, count, first/last seen, dispatch history, source fix status.

**The fault marker.** A message holding `fault[KEY]` names its own identity. The authority for what a marker is, the exact regex:

    fault\[([^\s\]]+)\]

KEY holds no whitespace and no closing bracket. A marked message normalizes to the marker text alone, so its fingerprint is `sha1(level:fault[KEY]:component)`: the free text after it rides in the mail and is never hashed. A marked message skips the user-error phrase test, because the emitter declared a fault. An unmarked message keeps the normalizer as it is (paths, `line N`, timestamps, UUIDs, hashes, `:NN` ports, 3+ digit ids) and the phrase test. The hooks engine's handler-failure line carries a marker.

**Circuit breaker: counts would-be mails, never log lines.** One gate, `dispatch_gate(recipient, fingerprint, note)`, called by medic and by the CI red lane at the point a mail would go: after suppression, backoff and the recipient checks. A storm of one fault therefore reaches it once per backoff step; per-fingerprint backoff bounds that fault's mail. The rules:

- Per recipient: at most 5 distinct fingerprints mailed in 10 minutes. Past that a mail is held and counted on the recipient's held list, and the list rides in that branch's next medic mail.
- Fleet trip: 10 distinct (recipient, fingerprint) mails in 60 seconds. The cap sits below the trip, so one branch alone cannot trip it. The mail that trips it is held.
- While open, every mail is held, and @devpulse gets one summary per opening, by plain email (never a wake): the recent sends and everything held. A summary that fails to send is retried at the next hold.
- `opened_at` is stamped only on closed to open. Holds never move it. After the cooldown (300 s, doubling to 3600 s on each failed probe) the next mail is the one probe; delivered closes the breaker, a failed send reopens it. A probe that never reports back is replaced after 300 s.
- A status read (`errors circuit-breaker`, `errors stats`) never moves the state; only the gate does.

State lives in `trigger_cb_state.json`: every change reads, edits and writes it under its lock, so the daemon, a CLI `circuit-breaker reset` and a `ci poll` all see each other's writes, and it survives restarts. A reset closes the breaker and keeps per-fingerprint backoff and the held lists.

**Per-fingerprint tracking:** Each unique error has independent exponential backoff and dispatch count. State persists across restarts.


The registry is **operational, not archival**: resolved entries are meant to be cleared
regularly, and a purge verb exists for the stale ones. Each log watcher start purges rows unseen for 30 days, keeping suppressed rows: a dropped one would dispatch again on its next recurrence. Nothing here is a long-term record —
that is @memory's job.

---

## Related

- [medic.md](medic.md) — the suppression doctrine and the gates that read this state
- [event_bus.md](event_bus.md) — `report_error()`, the cross-branch entry point
- [state_and_durability.md](state_and_durability.md) — how these files survive a crash
