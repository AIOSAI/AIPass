[← Back to AIPass](../../../README.md)

# Trigger

**Purpose:** Event bus and error dispatch for AIPass. Branches fire events, registered handlers react. Medic watches logs for errors, fingerprints them, gates dispatch through a 7-gate pipeline, and notifies the responsible branch.
**Module:** `aipass.trigger`
**Version:** 2.6.0
**Last Updated:** 2026-09-08

## Quick Start

```bash
drone @trigger medic status                  # Medic state + live watcher + mutes
drone @trigger errors list                   # View tracked errors
drone @trigger status                        # Branch log watcher state (see note)
drone @trigger escalation status             # Repeat-signature digest lane
drone @trigger fire error_detected branch=api error_type=ImportError
```

> **`status` reports this process, not the daemon.** `drone @trigger status`
> prints the branch log watcher belonging to the CLI process you just started —
> which has none — so it always says `Active: False` even while the systemd
> watcher runs. For the live answer use `drone @trigger medic status`, which
> reads the service, or `systemctl --user status trigger-log-watcher`. Recorded
> in APLAN-0008 as an open item; the README used to claim this command showed
> "event bus + medic state", which it never did.

## Commands

```bash
drone @trigger                              # Introspection (the 6 discovered modules)
drone @trigger --help                       # Full command listing
drone @trigger --version                    # Version string

# Event bus
drone @trigger fire <event> [key=val ...]   # Fire an event; reports handlers run/failed
drone @trigger list                         # List all registered events + handlers
drone @trigger status                       # Branch log watcher state (see note)

# Error registry
drone @trigger errors list                  # View tracked errors
drone @trigger errors stats                 # Registry stats + circuit breaker
drone @trigger errors circuit-breaker       # Circuit breaker state
drone @trigger errors circuit-breaker reset # Force the breaker closed
drone @trigger errors detail <fingerprint>  # Single error detail
drone @trigger errors suppress <id> [why]   # Silence an error — no dispatch while suppressed
drone @trigger errors unsuppress <id>       # Restore dispatch (existing backoff applies)
drone @trigger errors resolve <id>          # Mark resolved — recurrence still dispatches
drone @trigger errors clear-resolved [--days=N]  # Purge old resolved entries (default 7)
drone @trigger errors purge [--days=N]      # Purge stale entries (default 30)
drone @trigger errors --help                # Error subcommand help

# Medic (error dispatch control)
drone @trigger medic on                     # Enable auto-dispatch
drone @trigger medic off [--forever]        # Disable dispatch 24h (detection continues); --forever also stops the watcher
drone @trigger medic status                 # Medic state + suppression stats
drone @trigger medic mute @branch [--for <dur>|--forever]   # Suppress error dispatch (default 24h)
drone @trigger medic unmute @branch         # Resume error dispatch to a branch
drone @trigger medic volume-mute @branch [--for <dur>|--forever]  # Suppress runaway alerts
drone @trigger medic volume-unmute @branch  # Resume runaway alerts for a branch
drone @trigger medic --help                 # Medic subcommand help

# Escalation digest (repeat signatures → operator email)
drone @trigger escalation status            # Lane settings, tracked counts, digests sent
drone @trigger escalation list [level]      # Tracked signatures (level: warning | error)
drone @trigger escalation config            # Operator config path + effective values
drone @trigger escalation --help            # Escalation subcommand help

# Log watchers
drone @trigger branch_log_events status     # Branch log watcher state
drone @trigger branch_log_events start      # Start watching branch logs
drone @trigger branch_log_events stop       # Stop the branch log watcher
drone @trigger branch_log_events reset      # Clear error deduplication hashes
drone @trigger branch_log_events --help     # Branch watcher help
drone @trigger log_events status            # System log watcher state
drone @trigger log_events start             # Declines by design, exits 2 — see system_logs ownership
drone @trigger log_events stop              # Stop the system log watcher
drone @trigger log_events --help            # System watcher help
```

## Python API

```python
from aipass.trigger.apps.modules.core import Trigger

# Fire an event — all registered handlers run
result = Trigger.fire("plan_file_created", path="/path/to/FPLAN-0042.md")
# {'event': 'plan_file_created', 'handlers': 1, 'ran': 1, 'failed': 0}
# A nested fire (one issued from inside a handler) is queued, and says so:
# {'event': 'inner', 'deferred': True}

# Register a handler
def on_plan_created(**data):
    print(f"Plan created at {data['path']}")

Trigger.on("plan_file_created", on_plan_created)

# Remove a handler
Trigger.off("plan_file_created", on_plan_created)
```

**Handler failures are isolated, not hidden.** A handler that raises never
propagates to the caller and never stops the other handlers — that isolation is
the point of a bus. But isolation used to be indistinguishable from silence:
`drone @trigger fire` printed a green `Fired event:` whether every handler ran,
every handler crashed, or the event name was a typo nothing listened to. Firing
`plan_file_moved` with the wrong kwargs during the APLAN-0008 audit crashed the
handler and still reported success; the only trace was an ERROR line that the log
watcher later re-reported as a medic error. `fire()` now returns the counts above
and the CLI prints them, so a wrong-key or wrong-name fire is visible where it is
typed. Handler exceptions are still logged, still counted toward the
consecutive-failure auto-disable, and still never raised at the caller.

**A help flag anywhere explains; it never executes.** `--help` and `-h` are
matched exactly at *any* position in the argument sequence, so
`medic mute @branch --help` describes muting instead of performing it. Every
module's `handle_command` gates on `handlers/cli/help_flags.wants_help()`
before doing any work — but *after* checking that the module owns the command,
since a module that claimed any invocation carrying `--help` would hijack every
other module's help at the entry point. The bare word `help` is deliberately
positional (position 0 only): trigger's own commands take it as a legitimate
value — `errors suppress <id> help` is a reason and `fire evt message=help` is
event payload. Matching is exact for the same reason, so `message=--help` stays
a payload too. The fleet-wide version of this bug (seedgo `help_flag_safety`,
2026-08-13) performed a 17-branch config reset and a real backup run from
commands that were asked to describe themselves; trigger's own worst case was
a 24-hour medic mute with no unmute.

**Event data contracts are per-handler and are not published here.** Sibling
events do not share key names — `plan_file_created` and `plan_file_deleted` take
`path`, while `plan_file_moved` takes `src_path` and `dest_path`. Read the
handler in `apps/handlers/events/` before firing one by hand.

```python
from aipass.trigger.apps.modules.errors import report_error

# Cross-branch error reporting
result = report_error(
    branch="api",
    error_type="ConnectionError",
    message="Timeout reaching upstream",
    source_file="client.py",
)
# Returns: {"is_new": True, "fingerprint": "abc123", "count": 1, ...}
```

## Events

**7 events, 7 handlers.** That is the live count and `drone @trigger list` prints it
(re-measured 2026-09-05). It read 10/10 until 2026-08-31, when the plan-file handler
was retired — see the plan-file note below the table.
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
| `startup` | `startup.py` | First prax log call in **any** process (`prax` `logger.py`, in `_ensure_watcher()`) | Error catch-up scan over `system_logs/` — that is the whole handler (`startup.py:369-377`). It does **not** check memory rollover; this table claimed it did until 2026-08-14. The scan fires `error_detected` for what it finds — the handler's own docstring says `error_logged`, which is wrong and is tracked as a code fix, not a README one |
| `error_detected` | `error_detected.py` | Error registered via log watcher or `report_error()` | Full 7-gate Medic dispatch — emails fix-it to affected branch + `wake_branch()` |
| `warning_logged` | `warning_logged.py` | Warning in branch or system logs | Feeds the escalation digest lane — counted by signature, never dispatched |
| `memory_template_updated` | `memory_template_updated.py` | **Nothing fires it.** No `fire("memory_template_updated")` call site exists anywhere in the fleet (measured 2026-09-05) | **Stub — does nothing.** Writes one `json_handler` operation line and returns. Its own docstring claims it calls memory's `push_templates()`; there is no such import and no such call. The real build is planned in DPLAN-0318 |
| `cli_header_displayed` | `cli.py` | CLI displays headers | Registration hook |
| `runaway_log_detected` | `runaway_handler.py` | Prax rate tracker detects sustained high log volume | Per-file cooldown dispatch to responsible branch; gated by VOLUME mutes only (CRITICAL bypasses); UNKNOWN attribution falls back to @prax; writes alert to `.aipass/alerts.json` |
| `memory_pool_auto_processed` | `memory_pool.py` | @memory's detached child at the point it finishes — `memory/apps/handlers/intake/auto_process.py`, `_fire_completion()` from `run_once()`, on both the success and the failure leg; a run that declines the lock announces nothing, because the holder announces its own | Logs result; on failure fires `error_detected` for Medic dispatch. `status` vocabulary is `ok` / `skipped` / `failed` / `unknown` — `unknown` means the section never reported, and an absent section must derive to it rather than to `ok`, or a crashed run announces that the pool completed (found by @hooks 2026-09-05, cure is @memory's) — and `branch` must be a **registered** citizen — `__global__` is refused by gate 5 and the failure would be lost there. Both published in the handler docstring |

**Renamed — one release of grace:**

| Old name | Current name | State |
|---|---|---|
| `file_deleted` | `profile_write_failed` | **Aliased 2026-09-07** (FPLAN-0492 wave 5, ruled by @devpulse). `DEPRECATED_EVENT_ALIASES` in `modules/core.py` resolves the old name in `fire()`, `on()` and `off()`, and logs a deprecation **once per name per process**. The entry is deleted next release |

The old name described the opposite of what happens: the event fires when a **profile
write fails** and `json_handler` removes its own temp file — the store is never deleted.

Measured 2026-09-07: **zero handlers are registered on either name**, anywhere in the
fleet, so the alias is precautionary rather than load-bearing. Three fire sites carry
the old name, none of them in this branch —
`aipass/apps/modules/profile.py:84`, `aipass/apps/modules/init_flow.py:125` and
`daemon/apps/modules/timer_install.py:157`. One display consumer keys on the string:
`prax/apps/handlers/monitoring/unified_stream.py:59` colours `file_deleted` red and
will need the new key. (`plan_file_deleted` is a different event and is unaffected.)

**@daemon's fire site is not a profile write failure.** `timer_install.py:157` fires
immediately after `dst.unlink()` removes a systemd unit — a real deletion, accurately
named. Aliasing relabels it as a profile write failure, which is the same kind of lie
the rename exists to remove; the table keys on the event name and cannot tell the two
callers apart. Ruled by @devpulse 2026-09-07: that site "is a different event entirely"
and gets its own honest name in a @daemon item they queue. Until it moves, its fires
are relabelled by this table — a known interim, not an oversight.

Renaming the fire calls is **not this branch's work**: @aipass's two sites go into its
own wave-6 brief. The error registry holds no entry under either name (measured
2026-09-07), so there was nothing there to update.

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
`Trigger.fire("error_logged")` anywhere in the fleet. It survives only as *text*: a docstring
in `handlers/watchers/log_watcher.py`, a docstring in `startup.py`, and — worse, because a
human reads it — a line in `drone @trigger log_events --help` advertising it as a real event.
The watchers fire `error_detected` and `warning_logged`, and nothing else. Correcting that
help text is a code change, listed here so the README is not the last place the fiction lives.

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

## Medic

Error monitoring subsystem. Watches branch and system logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch.

**Dispatch pipeline — 7 sequential gates, then one either/or:**

1. **Medic enabled** — global on/off toggle
2. **Branch not muted** — per-branch suppression
3. **Count >= 2** — first occurrence suppressed, dispatch on recurrence
4. **Recipient is not `@devpulse`** — the manager is protected from self-dispatch. The code gates on the literal recipient string (`error_detected.py:509`); the older `DEV_CENTRAL` name this README used does not appear on the path
5. **Branch in registry** — target must be a registered citizen
6. **Circuit breaker closed** — trips after 10 errors in 60s, 300s cooldown
7. **Not suppressed + backoff elapsed** — `should_dispatch()` checks registry status first, then exponential backoff

Gates 6 and 7 are the Medic v2 path and run only when the error registry is available
*and* the event carried a fingerprint. When it is not, the handler takes the **legacy
v1 fallback instead**: per-branch rate limiting, 3 dispatches per 10 minutes. This
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

**`system_logs/` has exactly one owner: the branch watcher** (Patrick's ruling,
2026-08-14). Both watchers used to register the directory.
`watchers/log_watcher.start_log_watcher()` now declines and returns `None`
(`SYSTEM_LOGS_OWNER` names the owner in the code); the rest of that module stays live,
because it is still the reader the startup catch-up scan uses. The ruling ends the
duplicate, not the watching — the branch watcher globs `system_logs/*.log` alongside the
per-branch logs and carries the branch mapping, the parsing and the staleness handling.
`drone @trigger log_events start` says so rather than reporting a failure — and since
2026-09-08 it also **exits 2** rather than 0. Both halves are the contract: the wording
must not send a reader hunting a broken watcher, and the exit code must not tell a
caller's `&&` that a watcher is running. Exiting 0 for eighteen months meant
`log_events start && <next>` ran `<next>` with nothing watching. The refusal now travels
through cli's `error()`, `main()` returns `resolve_exit(True)` instead of a literal `0`,
and `reset_command_state()` at the top of `main()` stops one refusal colouring the next
command in the same process. A clean routed command is still 0; an unknown command is
still 1; a routed refusal is 2. Ruled by @devpulse over this branch's own 2026-08-14
reading, following @daemon's identical call at `schedule.py:50-52`.

**One line is counted once, even though prax writes it twice.** Every prax call
lands in *two* files: `src/aipass/<branch>/logs/<module>.log` and
`system_logs/<branch>_<module>.log`. The branch watcher globs both trees, so a single
warning became two escalation signatures — and the two disagreed about who wrote it,
because the branch copy is attributed by the directory it sits in while the
`system_logs` copy is attributed by guessing at its filename. The reported pair
(2026-08-14) was `0249c13b4d64` `HOOKS` and `690de8d87cdc` `UNKNOWN`, the same three
sample lines, consecutive sequence numbers 8514/8515 — one reader, two files, not two
readers. `_should_process()` now drops a `system_logs` file when
`_system_log_branch_twin()` finds the branch copy that already covers it: measured
across the tree on 2026-08-14, 230 of 243 `system_logs` files were twin-backed and 229 of
those twins were written within one second of their system copy. Re-measured 2026-09-05:
**334 of 346 twin-backed, 12 with no twin** (`telegram-bot-*`, external projects such as
`chess_perft` and `marketstand_*`, and test-fixture logs). The untwinned ones keep being
watched — that is the only reason the directory is still read at all.

**Branch attribution comes from the live tree, not a list.** `_known_branch_names()`
reads the branch directories (60s TTL) instead of trusting a hardcoded roster. The
roster held 11 names against 17 branches, so every `system_logs` file belonging to
@hooks, @backup, @commons, @daemon, @skills or @aipass was reported as `UNKNOWN` — the
fault was the list, not the log. The static list survives as a floor for when the tree
cannot be read. `UNKNOWN` now means what it says: nobody in the tree owns this log.

**Path classification is separator-agnostic.** `_classify_log_path()` matches on
`PurePath.parts` — `"aipass" in parts and "logs" in parts` for a branch log,
`"system_logs" in parts` for a system log — not on `"/logs/" in path`. The string
form only ever matched forward slashes, so on Windows every branch log classified
as foreign and was silently skipped: the watcher would have run, reported healthy,
and processed nothing. Pinned on both platforms from either one with
`PureWindowsPath` and `PurePosixPath` (2026-08-18, reported by @devpulse from
Windows CI).

```bash
systemctl --user status trigger-log-watcher    # Check watcher service
systemctl --user restart trigger-log-watcher   # Restart watcher
```

**The service reloads itself when handler code changes** (`handlers/reload_sentinel.py`). It is a long-running process that imports trigger's handlers once and holds them for its whole life, so a fix shipped to disk does nothing until it restarts. That gap cost this branch 25 hours of a signature fix reported live while the old code was still running, twice mistaken for the fix being incomplete. Remembering to restart after shipping is a human remembering something — the mechanism that already failed — so the process now notices for itself.

Every 30s it compares the mtimes of `apps/handlers/**.py` and `apps/modules/**.py` against the snapshot taken when it started. On a change it exits `75` (`EX_TEMPFAIL`) and systemd's `Restart=on-failure` brings up a fresh interpreter that imports everything from disk. Deliberately a restart, not `importlib.reload()`: handlers register callbacks on the event bus, and reloading in place leaves the bus holding the old function objects.

Two guards keep it from making things worse:

| Guard | Behaviour |
|---|---|
| **Settle** | A change is ignored until its mtime has been still for 15s, so an editor mid-save cannot restart the service into a half-written module |
| **Supervision** | A process with no `INVOCATION_ID` (run by hand, not by systemd) **never exits** — it logs loudly that it is running stale code instead. Exiting there would stop log watching entirely, trading a stale watcher for no watcher |

Reloads are recorded in `logs/reload_sentinel.jsonl` with the files that triggered them, so a restart is never indistinguishable from a crash. Tests and JSON state are not watched — only code the process actually imports.

Note the exit code is coupled to the unit: `Restart=on-failure` means exiting `0` would be read as a completed job and the watcher would stay down. If the unit ever moves to `Restart=always`, `RELOAD_EXIT_CODE` should become `0`; a test pins the two together.

## Escalation Digest

Medic answers an error **once**: it dispatches the owning branch, then goes quiet — backoff, a mute, or a suppression keeps it quiet. That is correct for agents and blind for humans. An error still firing after its owner was told, or while a branch is muted, was invisible to Patrick forever. Warnings were worse: they had **no escalation path at all**.

The escalation lane counts repetition and mails the operator when repetition means nothing got fixed:

> same signature, >= threshold occurrences inside the window → **one email** to the digest recipient → per-signature cooldown so the same noise cannot spam the mailbox

**Two tiers:**

| Tier | Covers | Escalates when |
|---|---|---|
| 1 — Warnings | Any repeating WARNING signature | Threshold crossed. Warnings have no dispatch path anywhere, so repetition alone is the signal |
| 2 — Errors past medic | ERROR signatures still recurring after medic acted | Owner already dispatched, branch muted, medic off, or no registered owner to dispatch to |

**Counting is unconditional; only sending is gated.** `record_error()` runs *before* every dispatch gate in `error_detected.py` — a mute stops re-dispatching, it must never stop the counting, or the repeat goes dark exactly when it matters most. A signature that never escalates is still fully auditable in the state file.

A deliberately **suppressed** fingerprint stays silent here too (compass #219 — a human already judged it benign), unless `escalate_suppressed` is turned on.

Digests are **email, never dispatch** (`auto_execute=False`). The default recipient `@devpulse` is a manager — wakes are blocked there, and the mail is meant to be read, not to spawn an agent.

**One signature, one message.** Digests are delivered with `upsert_key="escalation:<signature>"`, so a repeat *updates the existing message in place* — the counter climbs (`Updates: N`), the body refreshes to the latest numbers, read-state is preserved, and no notification fires. The key is the **signature**, never the rendered subject: the subject carries the repeat count and changes every digest, so keying on it would start a fresh thread each time. A digest that lands as an update is recorded as `upsert_action` in `logs/escalation.jsonl` and in the `escalation_digest_sent` operation, so an in-place update is auditable instead of looking like a digest that vanished. Cooldown semantics are unchanged — it now paces in-place updates rather than new mail, and `Digests sent` still counts every digest that left the branch. Closing the message ends the thread: the next digest creates a fresh one.

**What makes a signature.** `sha1(LEVEL|BRANCH|module|normalized_message)[:12]`. The message goes through the error registry's `normalize_message` (paths, timestamps, hashes, 3+ digit IDs), then through a second pass that is **local to this lane** — registry fingerprints keep their finer grain, so `errors list` and medic dispatch are untouched by anything here. That second pass collapses what varies between *repeats of one condition* rather than between errors:

| Collapsed | To | Why |
|---|---|---|
| Any standalone number, plus a short unit suffix (`20`, `1237ms`, `pid 4471`) | `<id>` | A climbing count or a duration is the same condition recurring. The suffix is load-bearing: there is no word boundary between digits and letters, so a bare `\b\d+\b` leaves `1237ms` alone |
| Registered citizen names, from `AIPASS_REGISTRY.json` (TTL-cached) | `<branch>` | "latest: log from SEEDGO" and "from PRAX" are one queue-full condition, not two |
| Any `@handle`, registered or not | `<branch>` | An unregistered name must not fragment what the registered ones unify |

The placeholder is `<id>` on purpose — the same token the registry normalizer emits for 3+ digits. A different token would make the two passes disagree at the 100 boundary, and `99 events` / `101 events` would keep minting separate signatures.

**Digest body carries the investigation:** signature, level, branch, module, occurrences in window, lifetime count, first/last seen, log file path, why it escalated, and the last N sample lines.

**Config knobs** — operator-editable, live in `trigger_json/custom_config/trigger.config.json` under `escalation` (S193 doctrine: the file on disk is runtime authority; `config_loader.DEFAULT_CONFIG` is only the regeneration seed):

| Knob | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch — false records nothing, sends nothing |
| `digest_recipient` | `@devpulse` | Where digests land (email only, never a wake) |
| `warning_threshold` | `10` | WARNING occurrences in window before a digest |
| `error_threshold` | `5` | ERROR occurrences in window before a digest |
| `window_minutes` | `60` | Rolling window; older occurrences stop counting |
| `cooldown_minutes` | `360` | Per-signature silence after a digest fires |
| `sample_lines` | `3` | Sample log lines carried in the digest body |
| `max_signatures` | `500` | Cap on tracked signatures (least-recently-seen pruned) |
| `escalate_suppressed` | `false` | Escalate operator-suppressed fingerprints anyway |
| `watch_branch_log_warnings` | `true` | Parse WARNING lines out of branch logs |
| `ignore_branches` | `[]` | Branches never escalated (deliberate, like a volume mute) |

State lives at `trigger_json/escalation_state.json` — deliberately **not** a trio name (see Architecture). The decision trail is `logs/escalation.jsonl` — `.jsonl`, not `.log`, so the branch watcher (which reads only `*.log`) cannot feed the lane its own output. It is written through `TrailLogger` (`apps/config.py`), the shared recursion-safe sink every trigger handler on the error path logs through; a write it cannot complete is counted on `.dropped` and surfaced as `Trail lines lost` in `escalation status` rather than discarded.

## Error Registry

SHA1 fingerprinting for error deduplication. Tracks: fingerprint, branch, error type, message, count, first/last seen, dispatch history, source fix status.

**Circuit breaker:** Trips after 10 errors within 60 seconds. Rejects all dispatch while open. Auto-resets after 300s cooldown. State persists across restarts in `trigger_cb_state.json`.

**Per-fingerprint tracking:** Each unique error has independent exponential backoff and dispatch count. State persists across restarts.

## Architecture

```
trigger/
├── apps/
│   ├── trigger.py                  # Entry point (auto-discovers modules/)
│   ├── config.py                   # Constants, atomic_write_json, json_file_lock, TrailLogger
│   ├── log_watcher_service.py      # Persistent watcher daemon (systemd)
│   ├── modules/
│   │   ├── core.py                 # Event bus: Trigger.fire/on/off/status
│   │   ├── errors.py               # Error registry CLI: list/suppress/unsuppress/stats
│   │   ├── medic.py                # Medic toggle: on/off/status/mute/unmute
│   │   ├── escalation.py           # Escalation digest CLI: status/list/config
│   │   ├── branch_log_events.py    # Branch log watcher CLI: start/stop/status
│   │   └── log_events.py           # System log watcher CLI: start/stop/status
│   └── handlers/
│       ├── error_registry.py       # SHA1 fingerprinting, circuit breaker, suppression gate, backoff
│       ├── error_reporter.py       # report_error() API + source fix emails
│       ├── escalation.py           # Repeat-signature counting + digest email
│       ├── log_watcher.py          # Branch log watcher (watchdog, position tracking)
│       ├── medic_state.py          # Medic state persistence (medic_state.json)
│       ├── reload_sentinel.py      # Restarts the service when handler code changes
│       ├── repo_root.py            # find_repo_root() — the one dead-cwd-safe root walk
│       ├── service_control.py      # systemd unit install/start/stop from templates/
│       ├── cli/
│       │   └── help_flags.py       # wants_help(): a help flag anywhere explains, never executes
│       ├── json/
│       │   ├── json_handler.py     # Shim: binds the fleet json service (prax-owned)
│       │   └── config_loader.py    # Operator config loader (S193 self-heal doctrine)
│       ├── events/
│       │   ├── registry.py         # Auto-registers the 7 active event handlers
│       │   ├── startup.py          # Startup catch-up scan
│       │   ├── error_detected.py   # 7-gate Medic dispatch + escalation counting
│       │   ├── warning_logged.py   # Warning monitor + escalation counting
│       │   ├── .archive/plan_file.py         # Retired 2026-08-31, measured inert
│       │   ├── .archive/bulletin_created.py  # Retired
│       │   ├── memory_template_updated.py  # Stub, and nothing fires it
│       │   ├── cli.py              # cli_header_displayed hook
│       │   ├── runaway_handler.py  # Runaway log dispatch (per-file cooldown, independent of Medic)
│       │   ├── pr_status_sync.py   # PR → prax status sync (decommissioned TDPLAN-0007)
│       │   └── memory_pool.py     # Pool auto-process observability
│       └── watchers/
│           └── log_watcher.py      # system_logs reader — observer withdrawn, see below
├── tests/                          # 1017 test functions in 28 files (pytest expands to 1051)
├── trigger_json/                   # Runtime state files
│   ├── medic_state.json            # Medic state, muted branches, breaker
│   ├── error_catchup.json          # Startup catch-up scan position + hashes
│   ├── error_registry.json         # All tracked errors
│   ├── escalation_state.json       # Repeat-signature counts + digest cooldowns
│   ├── trigger_cb_state.json       # Circuit breaker persistence
│   ├── trigger_<config|data|log>.json  # Inert json_handler trio placeholders
│   └── .archive/                   # Retired state files, never deleted
└── trigger_data.json               # Log watcher positions + dedup hashes
```

Two package directories under `apps/` are deliberately not drawn above, both spawn
scaffolding this branch has never used (re-checked 2026-09-07): `extensions/` holds a
single `__init__.py` with one comment line; `plugins/` holds that plus a README.md
describing a daemon-plugin pattern this branch never adopted. They are named here
rather than drawn so the tree keeps showing code that runs.

A third, `json_templates/`, was retired on 2026-09-07 (FPLAN-0492 wave 5). It carried
an `__init__.py` and `default/{config,data,log}.json`, dead since the json sweep
because the fleet json service generates its defaults **in code** and reads no
on-disk template. Measured at zero references outside its own directory, then moved
to `apps/.archive/json_templates/` rather than deleted. `.archive/` is gitignored
with no exceptions, so in git this lands as a deletion of four files; the copy on
disk is a local recovery path only, and the disposal zone is cleaned without warning.

Branch-root directories the tree also does not draw: `logs/` (prax output plus this
branch's `.jsonl` trails), `templates/` (the systemd unit template `service_control.py`
installs from), `tests/`, `tools/`, `docs/`, `docs.local/`, `artifacts/` and `dropbox/`.

Nothing under `trigger_json/` is in git — it is runtime state, written by the
running system. The operator config lives at
`trigger_json/custom_config/trigger.config.json` and is created by
`config_loader.load()` on the first read, so on a fresh clone that directory
does not exist yet. It is named here in prose rather than drawn into the tree
above for exactly that reason: the tree describes what a checkout contains.

**Live state never sits on a trio filename.** `json_handler` owns every
`<module>_<config|data|log>.json` name in `trigger_json/`: it validates such a
file against the structure its type declares and regenerates it when the shape
does not match. Since the json sweep (2026-09-03) that owner is the fleet
service behind the shim, and the default it regenerates from is **in code**
(`json_service._default_document`), not an on-disk template directory — the
`json_templates/` this branch still carried was retired on 2026-09-07 precisely
because nothing read it. The service recomputes the target directory on every
call, so nothing here is captured at import.
Medic state and catch-up state used to live at `trigger_config.json` and
`trigger_data.json` — both trio names for module `trigger`, both hand-written,
neither matching the template. Any trio call resolving to caller module
`trigger` would have replaced them with blank templates, dropping every live
mute, the persisted breaker state, and the processed-hash set that stops
already-handled errors being re-dispatched. The state moved to
`medic_state.json` and `error_catchup.json`; the trio names are now inert
placeholders that `json_handler` is free to own.

`config.migrate_json_file()` performs the move on first read: it is one-shot
(a file re-created at a legacy name afterwards belongs to its owner and is left
alone), never deletes — the old file moves to `trigger_json/.archive/` — and
leaves an unreadable legacy file in place for a human rather than guessing.

## Data Safety

> **On the numbers below.** Every concurrency count in this section (100 appends / 62 on
> disk, 98 of 100 on Windows CI, 99 of 100 on Linux CI, 0 losses in 1500 runs, 4 threads
> x 60 entries) is a **dated lab or CI measurement from the run that found the defect**,
> not a claim about tonight's tree. They are kept because the defect and its proof are the
> point. Re-measured tonight: only that the helpers still exist, are still imported by the
> handlers named, and that the suite pinning them is green. Anything else here is
> unverified as of 2026-09-05 by design — the original conditions no longer exist.

- **Atomic writes:** All JSON state files use `config.atomic_write_json()` — writes to a temp file in the same directory, then an atomic rename. No partial writes on crash.
  The rename goes through `config.replace_with_retry()`, not a bare `os.replace()`: on Windows an antivirus scanner or the search indexer can hold a transient handle on the destination and `os.replace` raises `PermissionError`. 40 attempts, 5ms apart, `PermissionError` only — any other `OSError` propagates on the first attempt, and exhaustion raises rather than reporting a write that did not happen. Fleet-canonical shape, matching `@commons`.
- **File locking:** All read-modify-write cycles wrapped in `config.json_file_lock()` with `.lock` sidecar files — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows. Prevents concurrent corruption from watcher + CLI. Both arms are pinned: the win32 one by an injected fake, the POSIX one by measurement (4 threads x 60 entries, peak 1 holder — `flock` takes a fresh open file description per call, so it conflicts even inside one process).
  Scope, after the json sweep: these two helpers serialise trigger's **own** state files — the error registry, the circuit breaker, medic state, escalation state, `.aipass/alerts.json` and `trigger_data.json`. Trio documents under `trigger_json/` are written by the fleet json service, which carries its own durability machinery; trigger's `config.py` no longer sits on that path.
  This line said "all" from the day it was written and was **not true until 2026-08-16**: the then-local `json_handler`'s own `log_operation`, `increment_counter` and `update_data_metrics` read a document, changed it in memory and wrote it back with no lock at all. Those three moved to prax with the sweep — `increment_counter` and `update_data_metrics` no longer exist anywhere in this tree. Atomic is not serialised — `atomic_write_json` stops a *torn* file, not a *lost* one, and having the atomic helper is exactly what made the gap look closed. Measured on the unfixed handler across 4 processes: **100 appends asked, 62 on disk, 38 lost silently, every call returning `True`.** After the fix, 100 of 100. Found by checking my own paths against a defect @api reported in theirs (`6cd8f22c`), not by anyone auditing this claim.
- **The Windows lock was a silent no-op until 2026-08-18.** `json_file_lock` carried `if sys.platform == "win32": yield` with the comment "single-user typical" — on Windows the context manager returned having taken *nothing*, and every caller ran unserialised while the code read as locked. Windows has no blocking `flock`, so the fix polls: `msvcrt.locking(..., LK_NBLCK, 1)` on one byte of the sidecar, 100 attempts 50ms apart, and the final attempt is deliberately unguarded so the caller gets the OS's own `OSError` instead of running unlocked. The sidecar opens `"a+"`, not `"w"` — truncating a file another process byte-locks is a sharing violation on Windows. Proven **from Linux** by a fake `msvcrt` injected into `sys.modules` with `sys.platform` patched: acquires and releases, retries-then-succeeds (exactly 3 waits, 4 lock calls), and refuses rather than yielding unlocked. A source-inspection test pins that the words "single-user typical" never come back.

- **The read side was the other half, and it was the one that lost data (2026-08-18).** `os.replace` was hardened against the Windows sharing window; every *reader* was left exposed to the identical transient. `ensure_json_exists` caught `OSError` alongside decode errors and answered both by writing a fresh template over the document — so a 5ms timing event was read as corruption and the file was thrown away. Windows CI counted it: **98 of 100** concurrent appends survived, the two lost being exactly the two on disk when one read was refused. Reproduced on Linux in three lines. Reads now go through `config.read_text_with_retry` (the mirror of `replace_with_retry`), **unreadable is no longer treated as corrupt**, and `log_operation` refuses rather than writing `[]` over a document it could not read. The lock was never involved — the destructive write lived outside the critical section, where no lock could reach it.
- **"Ensure this exists" is not "write this", and the difference was a lost entry (2026-08-19).** `ensure_json_exists` implemented create-if-missing as a replacing write, and it runs outside every lock — so two callers that both find a document missing both stage an empty template, and the loser's completes after a lock holder has written its first real entry. Linux CI counted **99 of 100**; reproduced locally at 3 losing runs in 400, with the instrumented write order naming the culprit outright (two empty-template writes staged first, one landing after a 1-entry write). No lock could have prevented it — the template write is outside every critical section by construction. Creation now goes through `config.atomic_create_json`: the staged file is **linked** into place, so a second creator is refused rather than overwriting, and the document is complete the instant it appears. 0 losses in 1500 runs after — with the same loop still losing when the replacing write is put back, so the loop has power. A filesystem without hard links degrades to the replacing write and says so in the log. **Since the json sweep this helper has no production caller left in trigger** — `ensure_json_exists` now lives in the fleet service, and `config.atomic_create_json` is reached only from `tests/test_json_durability.py` and the archived local handler (measured 2026-09-05). The account above is the history of a defect, not a description of tonight's live creation path.
- **Circuit breaker persistence:** Trip state, recent errors, per-fingerprint tracking all survive restarts via `trigger_cb_state.json`.
- **Off the trio path:** Hand-written live state uses filenames `json_handler`'s trio machinery does not own — see the Architecture section.

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`, and **the fleet json service**: `apps/handlers/json/json_handler.py` is the byte-identical shim binding `aipass.prax.json_handler` (DPLAN-0325, landed here 2026-09-03). 24 production files in this branch import that shim
- `aipass.cli` — Console output and formatting
- `aipass.ai_mail` — `deliver_email_to_branch()` for dispatch emails (lazy import, graceful fallback)

### Provides To
- All branches — Event bus (`Trigger.fire`, `Trigger.on`, `Trigger.off`)
- All branches — Cross-branch error reporting (`report_error()`)
- All branches — Automated error dispatch via Medic

## Testing

**1017 test functions across 28 test files; pytest expands them to 1051 cases**, all
passing (`1051 passed`, 0 failed, 0 skipped, 17.8s from the repo root and 25.1s from this
directory — measured 2026-09-08). It read 1015 / 28 / 1049 the evening before; FPLAN-0508
wave 9 took every v5 pytest_quality rule to 100 by rewriting eighteen units in place, and
added exactly two functions — both in `test_trigger_entry.py`, pinning the new exit seam.
It read 1006 / 28 / 1039 earlier on 2026-09-07; FPLAN-0492 wave 5 added
the occurrence-counting, alias and module-identity pins and merged 6 of the 7 DPLAN-0323
duplicate rows. It read 1016 / 29 / 1057 for the two days before that: on 2026-09-07
01:30 `test_json_handler.py` was archived and four test functions were removed from
`test_error_detected.py` and `test_log_watcher.py` by an author this branch cannot
name — see Status / Known issues. Both numbers are published because parametrization moves them apart:
`def test_` lines are what a reader counts in the files, collected cases are what CI
reports. Coverage: 103/103 public functions (100%), as reported by
`drone @seedgo audit aipass @trigger` tonight.

```bash
cd src/aipass/trigger && pytest    # Run all tests
```

Test files (28, listed from `ls tests/test_*.py` on 2026-09-07): `test_branch_log_events`,
`test_bypass_anchors`, `test_config_migration`, `test_core`, `test_error_detected`,
`test_error_registry`, `test_error_reporter`, `test_errors`, `test_escalation`,
`test_escalation_upsert`, `test_event_handlers`, `test_help_flags`, `test_import_dead_cwd`,
`test_json_durability`, `test_log_events`, `test_log_watcher`,
`test_log_watcher_service`, `test_medic`, `test_medic_state`, `test_memory_pool_handler`,
`test_pr_status_sync`, `test_reload_sentinel`, `test_runaway_handler`, `test_service_control`,
`test_startup_handler`, `test_trigger_config_loader`, `test_trigger_entry`,
`test_watchers_log_watcher`

Archived, and no longer in the count: `test_plan_file_handler` and `test_scaffold` (both
in `tests/.archive/` with the handlers they pinned), plus two files the json sweep retired
on 2026-09-04 (`deleted_2026-09-04_json_handler.py`, `deleted_2026-09-04_cli_routing.py`).
`test_json_handler` is gone too, archived 2026-09-07 as
`deleted_2026-09-07_test_json_handler.py`. Its six wiring tests pinned that every public
name is a bound method of the fleet service; @seedgo now holds that contract fleet-wide
and checks the shim by hash (`json_handler_check`, canonical shim bytes), so the per-branch
copy was redundant. That reasoning is mine, reconstructed after the fact — the archival
carries no note and I did not make it.

The count said "27 modules" and the list named only 24 of them until 2026-08-25; it then
said 28 and named two files that had since been archived, until this pass. A
hand-maintained list beside a hand-maintained count drifts in two directions at once; both
are taken from `ls tests/test_*.py`, `grep -c "def test_"` and `pytest -q`.

## Status / Known issues

Live state read 2026-09-05 23:30, and every item below is a defect measured in this
pass rather than a plan. Code fixes are deliberately **not** in this pass — it was a
docs-only truth pass — and each one is either owned here or already mailed out.

**Running now:** medic ENABLED, log watcher running under systemd, 12 branches content-muted
(all auto-expiring inside 24h), 0 volume mutes. Error registry: 476 tracked errors —
437 `new`, 37 `resolved`, 2 `suppressed`. Lifetime counters: 2116 suppressions, 217 rate
limits. Suite 1049 passed; audit 100 with bypasses, 98 without.

| Issue | Where | State |
|---|---|---|
| **Unexplained work in my own tree.** On 2026-09-07 01:30–01:32 `test_json_handler.py` was archived to `tests/.archive/deleted_2026-09-07_test_json_handler.py` and four test functions were removed from `test_error_detected.py` (50→49) and `test_log_watcher.py` (164→161). Not my edits, and the archived file carries no note of author or reason | `tests/` | **Reported, not reverted.** Coherent with the fleet json sweep — @seedgo now pins the shim by hash, so a per-branch wiring copy is redundant — but that is reconstruction, not attribution. Suite is green (1039 at the time, 1049 now) and the shim hash is unchanged (`3456b766…`). Raised with @devpulse 2026-09-07 |
| `error_logged` is advertised as a real event by `log_events --help` and two docstrings, and nothing fires it anywhere in the fleet | `modules/log_events.py:71,135`, `handlers/watchers/log_watcher.py:17`, `events/startup.py:323` | **Open, mine.** Known since 2026-08-25 and still unfixed; the watchers fire `error_detected` and `warning_logged`, and nothing else |
| ~~`memory_pool_auto_processed` has a registered handler and no firer~~ | `events/memory_pool.py` | **Closed 2026-09-05, same night.** Found here, confirmed by @hooks, cured by @memory. The fire belonged in neither of the two places I offered: @hooks returns the instant a PID exists and cannot see the outcome, so it now fires from the child's own completion point. Verified end-to-end on my side — their exact payload gives `handlers: 1, ran: 1, failed: 0`, and a nested `error_detected` from inside a handler is deferred and then actually delivered, so the medic path is live again |
| `memory_template_updated` has a registered handler, no firer, and the handler is a stub whose docstring claims a `push_templates()` call it does not make | `events/memory_template_updated.py` | **Open, mine.** DPLAN-0318 |
| 15 stray `tmp*.tmp` files sit in `trigger_json/`, 14 of them zero-byte, oldest 2026-08-14 | `trigger_json/` | **Open, mine.** Staged temp files whose rename never landed; harmless but unswept, and the sweep belongs in the writer, not in a cron |
| ~~`apps/json_templates/default/` still ships `config.json`, `data.json`, `log.json` after the json service moved defaults into code~~ | `apps/.archive/json_templates/` | **Closed 2026-09-07** (FPLAN-0492 wave 5). Measured at zero references outside its own directory, then moved to `apps/.archive/` — archived, never deleted. Nothing imported it, so the suite was unchanged by the move |
| `drone @trigger status` always reports `Active: False` — it describes the CLI process you just started, never the systemd watcher | `modules/branch_log_events.py` | **Open, mine.** APLAN-0008. `medic status` is the command that reads the service |
| `.aipass/aipass_local_prompt.md` still says "14 events, 14 handlers" and lists `log_events.py` / `branch_log_events.py` shapes from before the retirement | branch prompt | **Open, mine.** Prompt file, out of scope for this docs pass (README + `.trinity` only) |

## Compliance

Seedgo: **100% with bypasses, 98% without** — both re-measured 2026-09-05 across 47
scored categories on 30 production files (`apps/` only; `tests/` is not in the audit
corpus). Zero type errors. Both numbers are published deliberately: 100% is the
shielded score, and the **25** bypass rules behind it each suppress exactly one real
violation — measured by running `--no-bypass` and matching one rule to one surviving
violation, with no violation left un-bypassed and no rule left dead (APLAN-0008). The
count was 26 until the json sweep retired the local handler and its rule with it. The
registry holds **zero `tests/*` rules**, so the checklist-lane trap that bit other
branches (a rule that reads dead in the audit lane while still suppressing findings in
the PostToolUse hook) does not apply here.

The `handlers` deduction on `handlers/escalation.py` this section described until
tonight is **gone**: `Handlers` scores 100 in both lanes and no bypass rule stands in
for it. @seedgo cured the check that could never match its own standard's documented
ALLOWED example — the question was raised, not restructured around, and the answer
landed upstream.

---

*Last Updated: 2026-09-08*

---
[← Back to AIPass](../../../README.md)
