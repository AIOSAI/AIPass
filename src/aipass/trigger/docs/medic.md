# Medic — error detection and dispatch

**Branch** trigger · **Code** `apps/modules/medic.py`, `apps/handlers/medic_state.py`, `apps/handlers/events/error_detected.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The verbs are in `drone @trigger medic --help`; `drone @trigger medic status` reads the live
state and the service. This page is the pipeline behind them and the doctrine each gate carries.

---

Error monitoring subsystem. Watches branch and system logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch.

**Dispatch pipeline — 7 sequential gates, then one either/or:**

1. **Medic enabled** — global on/off toggle
2. **Branch not muted** — per-branch suppression
3. **Count >= 2** — first occurrence suppressed, dispatch on recurrence
4. **Recipient is not `@devpulse`** — the manager is protected from self-dispatch. The code gates on the literal recipient string (`error_detected.py:509`); the older `DEV_CENTRAL` name the README used until 2026-09-05 does not appear on the path
5. **Branch in registry** — target must be a registered citizen
6. **Circuit breaker closed** — trips after 10 errors in 60s, 300s cooldown
7. **Not suppressed + backoff elapsed** — `should_dispatch()` checks registry status first, then exponential backoff

Gates 6 and 7 are the Medic v2 path and run only when the error registry is available
*and* the event carried a fingerprint. When it is not, the handler takes the **legacy
v1 fallback instead**: per-branch rate limiting, 3 dispatches per 10 minutes. The
README counted that fallback as "gate 8" until 2026-08-25, which read as a flood guard
sitting *after* the backoff check. It is not — it is the `else` arm of the same branch
(`error_detected.py`, `--- Dispatch gating ---`), so the v2 and v1 arms never both run,
and the healthy path has no rate limit at all. Escalation counting is upstream of every
gate here and is not one of them.

On successful dispatch: sends email via `deliver_email_to_branch()` then calls `wake_branch()` to spawn an agent in the target branch immediately.

**Suppression is real silence (compass #219).** A fingerprint with status `suppressed` never dispatches while suppressed — no re-wakes, ever. Agents must not be woken forever for a judged-benign error; the cycle ends at wake → investigate → suppress → sleep. Guardrails:

- Bookkeeping continues — `count` and `last_seen` keep updating, so a wrong suppress stays fully auditable in `errors list` / `errors detail`.
- `errors unsuppress <id>` restores dispatch. Backoff state is preserved, not reset to immediate.
- `errors stats` prints a **Silenced** count so the silent set is never invisible.
- Only `suppressed` gates. `resolved` deliberately does **not** — a resolved error that recurs means the fix did not hold, which is genuine signal.
- Wrong-suppress risk is handled by fingerprint precision, not by periodic re-wake machinery.
- The status read fails open: a registry read error allows dispatch rather than silencing a real error.

**Two mute classes, deliberately independent:**

| Class | Config key | Gates | Set with |
|---|---|---|---|
| CONTENT | `muted_branches` | `error_detected` dispatch | `medic mute @branch` |
| VOLUME | `volume_muted_branches` | `runaway_log_detected` alerts | `medic volume-mute @branch` |

A content mute means "expect error lines from me while I build" — it says nothing about log volume. Because every dispatch checklist tells agents to medic-mute *before* build/edit work, and build windows are exactly when floods happen, gating runaway alerts on the content mute made that channel structurally dead in its own peak window (31/31 suppressions in `logs/runaway_suppressed.jsonl` were `branch_muted`). Volume mutes must be set deliberately, and CRITICAL runaways bypass even those.

Runaway gating decisions are appended to `logs/runaway_suppressed.jsonl` with an `outcome` field — three values, not two: `suppressed` (alert dropped), `delivered` (sent anyway) and `observed` (the observe-only WARNING outcome: recorded, so it is not a suppression). Entries predating the field are all suppressions. Tonight the file holds 37 lines: 31 pre-field `branch_muted`, 5 `suppressed`/`cooldown`, 1 `observed`/`observe_only` (2026-09-05).

**Persistent log watching** runs as a systemd user service (`trigger-log-watcher.service`). Handles SIGTERM/SIGINT for clean shutdown.


---

## Related

- [error_registry.md](error_registry.md) — fingerprints, the circuit breaker and the suppression gate
- [escalation.md](escalation.md) — what happens when an answered error keeps recurring
- [log_watching.md](log_watching.md) — where the error lines come from
- [service_and_reload.md](service_and_reload.md) — the systemd unit behind "persistent log watching"
