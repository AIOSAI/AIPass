[← Back to DevPulse](../README.md)

# Watchdog — how it works

The deep reference, for when watchdog misbehaves. Day to day you only need the sign-in in the branch prompt and the command table in the README.

## Who may call it

The project OWNER only — the first agent, seated as `owner: true` in the project's sealed `*_REGISTRY.json`. Portable: `@devpulse` in AIPass, `@vera` in Vera Studio, whoever owns elsewhere. A refusal means your project's owner isn't seated — run `aipass doctor` to see why and `aipass doctor --fix` to repair (DPLAN-0239).

## The model — a login, not a service (r4, DPLAN-0317)

Watchdog is always on because nothing runs. Dispatching registers the job at send time; the agent that finishes **reports**; `@ai_mail` writes that report to a durable notification feed, where it **queues** whether anyone is listening or not. A conversation **signs in** to receive.

## The sign-in — one shot, in the background (DPLAN-0348)

Nothing happening, nothing happens. Arm with the Bash tool, `run_in_background: true`:

```
drone @devpulse watchdog baseline --once
```

It syncs whatever queued while you were logged out (`MISSED` lines), then sits silent. It **exits** on the first completion of a dispatch this seat sent, or on a dead monitor — and that exit is the one wake, carrying the report. Re-arm inside that same turn while work is still out; with nothing out, arm nothing. The newest sign-in owns delivery and logs out any older one. At idle the whole system is one `stat()` a second, 0.033 % of a core, and **zero model turns**.

Why not the Monitor tool: Claude Code 2.1.271 changed Monitor watches "to always have a deadline (at most 30 minutes…) and notify Claude to re-arm, replacing the no-timeout `persistent` option". No setting restores it. A continuous wire under Monitor therefore dies every 30 minutes and wakes the seat to say so — measured at 33 empty wakes across one 15-hour absence, enough to force an auto-compact. Background Bash has no coded lifetime cap, survives `/compact`, and notifies exactly once, on exit — which is the shape `--once` was built for.

Measured proof, 2026-09-16: a `--once` wire armed at 20:33 stayed silent for 31 minutes — past the Monitor cap — and exited once, at 21:03, with `DISPATCH @hooks title="@hooks completed"` and `delivered=1 ticks=1875`. No wake before it.

Not yet settled: an OS-level cap on a long-lived background task, and what `/clear`, `/resume` or closing the terminal do to one. Reports keep queueing regardless, and the next sign-in replays them — a lost receiver costs latency, never a report. After a compact, check TaskList for a live wire before arming a second.

The continuous form (`watchdog baseline`, no `--once`) still exists for a harness whose Monitor tool is uncapped. It **refuses** background Bash by design: that wrapper notifies only on exit, and a continuous wire never exits — zero wakes by construction (the 2026-08-19 failure). The refusal names the one-shot.

## Statusline

`watchdog:in` (green) — this session holds a live wire and it is ticking. `watchdog:idle` (dim) — no wire armed; the designed resting state when nothing is out. `HUNG` (red) — wire registered, pid alive, heartbeat stale over 15 s: the corpse that looks signed-in everywhere else. `ELSEWHERE` (red) — another session holds the sign-in.

Green needs the registered wire's `metadata.wrapper` to be `monitor` or `background`; the continuous wire refuses background Bash before it registers, so a registered `background` wire is always a one-shot. What the line cannot see: work that is out with **no** wire armed also reads `idle`. Source is tracked at `tools/statusline.sh`; install with `cp tools/statusline.sh ~/.claude/statusline.sh`.

## There is no passive wake

ai_mail's wake-back spawns a new headless process and can never inject into a live interactive session (`BLOCKED — interactive session` in the logs is that guard working as designed; it only serves senders whose session closed). Dispatch and idle without signing in and nothing will ever wake you — the report just queues.

## Dead-monitor backstop (FPLAN-0499, DPLAN-0314 "outcome M")

A dispatch whose monitor died — host reboot, OOM, kill — can never report, so the receiver announces it: at sign-in and every 5 minutes it reads `@ai_mail`'s dispatch register once (no agent is polled, no process is armed) and pushes one line per dispatch of yours whose monitor is gone: `monitor_alive` false (ai_mail records the monitor's pid and checks `/proc` at read time — a death is announced within one cadence, wording "its monitor (pid N) is gone before the hard timeout"), or past `expected_by` (ai_mail's hard timeout — a live monitor cannot overrun it). `monitor_alive` is tri-state; `None` (a row that never learned a pid) keeps the overdue rule only:

```
DEAD @prax [70da6e9c] dispatched 09-07 12:00 "..." — no completion by 09-07 14:00, the hard timeout: its monitor died (reboot, OOM, kill). Re-dispatch in continue mode.
```

Each death is announced once ever (cursor `devpulse_json/wire_dead_cursor.json`), so a re-sign-in never repeats one — and a one-shot does not exit on a death it already announced. `drone @devpulse watchdog status` shows the same rows on demand as "Dispatches overdue".

## Two rules the receiver enforces

- **Only completions wake.** The feed also carries *start* edges, and there are two sorts. A direct wake writes `kind="wake"`, dropped by kind — the receiver reads `dispatch` only. The daemon's start edge is `kind="dispatch"`, the same as a completion, so kind cannot filter it: it is dropped because it carries no `sender`, and rule two fails it closed. You are woken once, when the work is actually finished.
- **Only YOUR dispatches wake you.** The feed names the branch that *finished*, never the branch that *sent*, so every citizen's completion used to wake this seat fleet-wide. `@ai_mail` stamps `sender` on the completion line and the receiver compares it against this project's sealed owner. A record with no sender is **not** yours — unattributable fails closed.

## Crash coverage needs nothing running

Every dispatch is registered at send time with an `expected_by` taken from dispatch_monitor's hard timeout. An entry past that with no completion means the monitor *died* — a fact about a file, true whether or not anything is looking. `watchdog status` reads it.

## History — rounds 1–3 had a detection daemon; r4 deleted it

Commit `5444dd9a`. It polled ~19 branches' `.dispatch.lock` every 2 s to synthesize an event that `dispatch_monitor.py` had already reported 1–2 s earlier — every completion produced **two wakes**, for months, unnoticed because a duplicate wake looks exactly like a working wake. Idle cost: 7.72 % of a core. The source is preserved in git history at the removing commit, deliberately not in `.archive/` (gitignored disposal, cleaned without warning). `watchdog baseline --daemon` is refused by name.

## Stall detection on one long job

`watchdog agent @target [--timeout s]` remains for **mid-run stall detection** on a single long job (`[watchdog.stall]` / `[watchdog.resumed]` after 120 s of JSONL silence with no in-flight tool) — it is not needed to be woken, and arming one per dispatch is a second poller doing the receiver's job. It prints per-line events, so it needs the Monitor tool and inherits its 30-minute deadline. `@target` resolves in the caller's own project, then falls back to `~/Projects` registries.

## Known caveat

A wire armed *before* the 2026-09-07 statusline change carries no `wrapper` field and never paints green; re-arm it.
