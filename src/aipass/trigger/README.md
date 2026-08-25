[← Back to AIPass](../../../README.md)

# Trigger

**Purpose:** Event bus and error dispatch for AIPass. Branches fire events, registered handlers react. Medic watches logs for errors, fingerprints them, gates dispatch through a 7-gate pipeline, and notifies the responsible branch.
**Module:** `aipass.trigger`
**Version:** 2.6.0
**Last Updated:** 2026-08-25

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
drone @trigger log_events start             # Declines by design — see system_logs ownership
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

**10 events, 10 handlers.** That is the live count and `drone @trigger list` prints it.
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
| `plan_file_created` | `plan_file.py` | New `FPLAN-NNNN.md` detected | Adds a row to Flow's **legacy** `flow_json/PLAN_REGISTRY.json` — see the caveat below the table |
| `plan_file_deleted` | `plan_file.py` | PLAN file removed | Removes an open plan from that registry; a closed one is marked `archived` instead |
| `plan_file_moved` | `plan_file.py` | PLAN file relocated | Updates location fields only, preserving status and all other metadata |
| `memory_template_updated` | `memory_template_updated.py` | Memory template changed | **Stub — does nothing.** Writes one `json_handler` operation line and returns. Its own docstring claims it calls memory's `push_templates()`; there is no such import and no such call. The real build is planned in DPLAN-0318 |
| `cli_header_displayed` | `cli.py` | CLI displays headers | Registration hook |
| `runaway_log_detected` | `runaway_handler.py` | Prax rate tracker detects sustained high log volume | Per-file cooldown dispatch to responsible branch; gated by VOLUME mutes only (CRITICAL bypasses); UNKNOWN attribution falls back to @prax; writes alert to `.aipass/alerts.json` |
| `memory_pool_auto_processed` | `memory_pool.py` | Hook engine runs `auto_process()` | Logs result; on failure fires `error_detected` for Medic dispatch |

**Not wired — files on disk, deliberately unregistered:**

| Event | Handler | State |
|-------|---------|-------|
| `bulletin_created` | `.archive/bulletin_created.py` | **Retired** — moved to `.archive/`, never imported |
| `pr_created` | `pr_status_sync.py` | **Decommissioned** (TDPLAN-0007) — file kept, `trigger.on(...)` commented out in `registry.py` |
| `pr_merged` | `pr_status_sync.py` | **Decommissioned** (TDPLAN-0007) — same |

**`error_logged` is a name with nothing behind it.** No handler file, no registration, and no
`Trigger.fire("error_logged")` anywhere in the fleet. It survives only as *text*: a docstring
in `handlers/watchers/log_watcher.py`, a docstring in `startup.py`, and — worse, because a
human reads it — a line in `drone @trigger log_events --help` advertising it as a real event.
The watchers fire `error_detected` and `warning_logged`, and nothing else. Correcting that
help text is a code change, listed here so the README is not the last place the fiction lives.

**The plan handlers write Flow's legacy registry, and only for FPLANs.** `plan_file.py`
reads and writes `flow/flow_json/PLAN_REGISTRY.json` directly (no handler import), and
`_get_plan_number()` matches `FPLAN-(\d{4})\.md` only — every handler returns immediately
on a filename that does not match, so a DPLAN, PPLAN or APLAN path fired at these events is
a no-op that reports nothing. Flow has since moved to typed
per-kind registries (`aplan_registry.json` and siblings); the legacy file this branch still
writes holds **1 plan row against `next_number: 402`**, which is what a registry looks like
when everything real has moved elsewhere. Flow flagged the mismatch on 2026-08-24. Whether
these handlers should point at the typed registries is an open call, not a settled fix —
recorded here so nobody reads the rows above as "keeps Flow's registry current". It does not.

## Medic

Error monitoring subsystem. Watches branch and system logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch.

**Dispatch pipeline — 7 sequential gates, then one either/or:**

1. **Medic enabled** — global on/off toggle
2. **Branch not muted** — per-branch suppression
3. **Count >= 2** — first occurrence suppressed, dispatch on recurrence
4. **Not DEV_CENTRAL** — devpulse protected from self-dispatch
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

Runaway gating decisions are appended to `logs/runaway_suppressed.jsonl` with an `outcome` field (`suppressed` / `delivered`), so suppressed-by-design and delivered-by-bypass are distinguishable. Entries predating that field are all suppressions.

**Persistent log watching** runs as a systemd user service (`trigger-log-watcher.service`). Handles SIGTERM/SIGINT for clean shutdown.

**`system_logs/` has exactly one owner: the branch watcher** (Patrick's ruling,
2026-08-14). Both watchers used to register the directory.
`watchers/log_watcher.start_log_watcher()` now declines and returns `None`
(`SYSTEM_LOGS_OWNER` names the owner in the code); the rest of that module stays live,
because it is still the reader the startup catch-up scan uses. The ruling ends the
duplicate, not the watching — the branch watcher globs `system_logs/*.log` alongside the
per-branch logs and carries the branch mapping, the parsing and the staleness handling.
`drone @trigger log_events start` says so rather than reporting a failure.

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
across the tree, 230 of 243 `system_logs` files are twin-backed and 229 of those twins
were written within one second of their system copy. The 13 with no twin
(`telegram-bot-*`, external projects) keep being watched — that is the only reason the
directory is still read at all.

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
│       ├── cli/
│       │   └── help_flags.py       # wants_help(): a help flag anywhere explains, never executes
│       ├── json/
│       │   ├── json_handler.py     # JSON structure logging
│       │   └── config_loader.py    # Operator config loader (S193 self-heal doctrine)
│       ├── events/
│       │   ├── registry.py         # Auto-registers the 10 active event handlers
│       │   ├── startup.py          # Startup catch-up scan
│       │   ├── error_detected.py   # 7-gate Medic dispatch + escalation counting
│       │   ├── warning_logged.py   # Warning monitor + escalation counting
│       │   ├── plan_file.py        # Plan lifecycle events
│       │   ├── .archive/bulletin_created.py  # Retired
│       │   ├── memory_template_updated.py
│       │   ├── cli.py              # cli_header_displayed hook
│       │   ├── runaway_handler.py  # Runaway log dispatch (per-file cooldown, independent of Medic)
│       │   ├── pr_status_sync.py   # PR → prax status sync (decommissioned TDPLAN-0007)
│       │   └── memory_pool.py     # Pool auto-process observability
│       └── watchers/
│           └── log_watcher.py      # system_logs reader — observer withdrawn, see below
├── tests/                          # 1068 tests across 28 modules
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

Three package directories under `apps/` are deliberately not drawn above:
`extensions/`, `json_templates/` and `plugins/`. Each holds a single `__init__.py`
carrying one comment line and nothing else — spawn scaffolding this branch has never
used. They are named here rather than drawn so the tree keeps showing code that runs,
while the README still accounts for every directory a reader will actually find.

Nothing under `trigger_json/` is in git — it is runtime state, written by the
running system. The operator config lives at
`trigger_json/custom_config/trigger.config.json` and is created by
`config_loader.load()` on the first read, so on a fresh clone that directory
does not exist yet. It is named here in prose rather than drawn into the tree
above for exactly that reason: the tree describes what a checkout contains.

**Live state never sits on a trio filename.** `json_handler` owns every
`<module>_<config|data|log>.json` name in `trigger_json/`: it validates such a
file against its template and regenerates it when the shape does not match.
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

- **Atomic writes:** All JSON state files use `config.atomic_write_json()` — writes to a temp file in the same directory, then an atomic rename. No partial writes on crash.
  The rename goes through `config.replace_with_retry()`, not a bare `os.replace()`: on Windows an antivirus scanner or the search indexer can hold a transient handle on the destination and `os.replace` raises `PermissionError`. 40 attempts, 5ms apart, `PermissionError` only — any other `OSError` propagates on the first attempt, and exhaustion raises rather than reporting a write that did not happen. Fleet-canonical shape, matching `@commons`.
- **File locking:** All read-modify-write cycles wrapped in `config.json_file_lock()` with `.lock` sidecar files — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows. Prevents concurrent corruption from watcher + CLI. Both arms are pinned: the win32 one by an injected fake, the POSIX one by measurement (4 threads x 60 entries, peak 1 holder — `flock` takes a fresh open file description per call, so it conflicts even inside one process).
  This line said "all" from the day it was written and was **not true until 2026-08-16**: `json_handler`'s own `log_operation`, `increment_counter` and `update_data_metrics` read a document, changed it in memory and wrote it back with no lock at all. Atomic is not serialised — `atomic_write_json` stops a *torn* file, not a *lost* one, and having the atomic helper is exactly what made the gap look closed. Measured on the unfixed handler across 4 processes: **100 appends asked, 62 on disk, 38 lost silently, every call returning `True`.** After the fix, 100 of 100. Found by checking my own paths against a defect @api reported in theirs (`6cd8f22c`), not by anyone auditing this claim.
- **The Windows lock was a silent no-op until 2026-08-18.** `json_file_lock` carried `if sys.platform == "win32": yield` with the comment "single-user typical" — on Windows the context manager returned having taken *nothing*, and every caller ran unserialised while the code read as locked. Windows has no blocking `flock`, so the fix polls: `msvcrt.locking(..., LK_NBLCK, 1)` on one byte of the sidecar, 100 attempts 50ms apart, and the final attempt is deliberately unguarded so the caller gets the OS's own `OSError` instead of running unlocked. The sidecar opens `"a+"`, not `"w"` — truncating a file another process byte-locks is a sharing violation on Windows. Proven **from Linux** by a fake `msvcrt` injected into `sys.modules` with `sys.platform` patched: acquires and releases, retries-then-succeeds (exactly 3 waits, 4 lock calls), and refuses rather than yielding unlocked. A source-inspection test pins that the words "single-user typical" never come back.

- **The read side was the other half, and it was the one that lost data (2026-08-18).** `os.replace` was hardened against the Windows sharing window; every *reader* was left exposed to the identical transient. `ensure_json_exists` caught `OSError` alongside decode errors and answered both by writing a fresh template over the document — so a 5ms timing event was read as corruption and the file was thrown away. Windows CI counted it: **98 of 100** concurrent appends survived, the two lost being exactly the two on disk when one read was refused. Reproduced on Linux in three lines. Reads now go through `config.read_text_with_retry` (the mirror of `replace_with_retry`), **unreadable is no longer treated as corrupt**, and `log_operation` refuses rather than writing `[]` over a document it could not read. The lock was never involved — the destructive write lived outside the critical section, where no lock could reach it.
- **"Ensure this exists" is not "write this", and the difference was a lost entry (2026-08-19).** `ensure_json_exists` implemented create-if-missing as a replacing write, and it runs outside every lock — so two callers that both find a document missing both stage an empty template, and the loser's completes after a lock holder has written its first real entry. Linux CI counted **99 of 100**; reproduced locally at 3 losing runs in 400, with the instrumented write order naming the culprit outright (two empty-template writes staged first, one landing after a 1-entry write). No lock could have prevented it — the template write is outside every critical section by construction. Creation now goes through `config.atomic_create_json`: the staged file is **linked** into place, so a second creator is refused rather than overwriting, and the document is complete the instant it appears. 0 losses in 1500 runs after — with the same loop still losing when the replacing write is put back, so the loop has power. A filesystem without hard links degrades to the replacing write and says so in the log.
- **Circuit breaker persistence:** Trip state, recent errors, per-fingerprint tracking all survive restarts via `trigger_cb_state.json`.
- **Off the trio path:** Hand-written live state uses filenames `json_handler`'s trio machinery does not own — see the Architecture section.

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and formatting
- `aipass.ai_mail` — `deliver_email_to_branch()` for dispatch emails (lazy import, graceful fallback)

### Provides To
- All branches — Event bus (`Trigger.fire`, `Trigger.on`, `Trigger.off`)
- All branches — Cross-branch error reporting (`report_error()`)
- All branches — Automated error dispatch via Medic

## Testing

1068 tests across 28 test modules, all passing (`1068 passed`, 0 failed, 0 skipped —
measured 2026-08-25). Coverage: 106/106 public functions (100%), as reported by
`drone @seedgo audit aipass @trigger`.

```bash
cd src/aipass/trigger && pytest    # Run all tests
```

Test files: `test_branch_log_events`, `test_config_migration`, `test_core`,
`test_error_detected`, `test_error_registry`, `test_error_reporter`, `test_errors`,
`test_escalation`, `test_escalation_upsert`, `test_event_handlers`, `test_help_flags`,
`test_json_durability`, `test_json_handler`, `test_log_events`, `test_log_watcher`,
`test_log_watcher_service`, `test_medic`, `test_medic_state`, `test_memory_pool_handler`,
`test_plan_file_handler`, `test_pr_status_sync`, `test_reload_sentinel`,
`test_runaway_handler`, `test_scaffold`, `test_startup_handler`,
`test_trigger_config_loader`, `test_trigger_entry`, `test_watchers_log_watcher`

The count said "27 modules" and the list named only 24 of them until 2026-08-25 — four
modules shipped without ever being added here (`test_escalation_upsert`,
`test_json_durability`, `test_reload_sentinel`, `test_scaffold`). A hand-maintained list
beside a hand-maintained count drifts in two directions at once; both are now taken from
`find tests -name "test_*.py"` and `pytest -q`.

## Compliance

Seedgo: **100% with bypasses, 98% without** (46 standards). Zero type errors. Both
numbers are published deliberately: 100% is the shielded score, and the 26 bypass
rules behind it each suppress exactly one real violation — measured by running the
audit with `bypass: []` and matching one rule to one surviving violation, with no
violation left un-bypassed and no rule left dead (APLAN-0008). The registry
holds **zero `tests/*` rules**, so the checklist-lane trap that bit other branches
(a rule that reads dead in the audit lane while still suppressing findings in the
PostToolUse hook) does not apply here.

The largest single deduction is `handlers` on `handlers/escalation.py`: its five same-branch imports are all ALLOWED by the published handlers standard ("same-branch handler imports: ALLOWED, even across packages"), but `handlers_check` computes a handler's own package as the path part after `handlers/` — for a file sitting at the handlers root that is the *filename*, so the exemption can never match. Raised with @seedgo as a standards question rather than restructured around; the same check rejects the standard's own documented ALLOWED example.

---

*Last Updated: 2026-08-25*

---
[← Back to AIPass](../../../README.md)
