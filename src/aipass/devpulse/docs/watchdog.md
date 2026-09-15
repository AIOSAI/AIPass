[← Back to DevPulse](../README.md)

# Watchdog — how it works

The deep reference, for when watchdog misbehaves. Day to day you only need the sign-in in the branch prompt and the command table in the README.

## Who may call it

The project OWNER only — the first agent, seated as `owner: true` in the project's sealed `*_REGISTRY.json`. Portable: `@devpulse` in AIPass, `@vera` in Vera Studio, whoever owns elsewhere. A refusal means your project's owner isn't seated — run `aipass doctor` to see why and `aipass doctor --fix` to repair (DPLAN-0239).

## The model — a login, not a service (r4, DPLAN-0317)

Watchdog is always on because nothing runs. Dispatching registers the job at send time; the agent that finishes **reports**; `@ai_mail` writes that report to a durable notification feed, where it **queues** whether anyone is listening or not. A conversation **signs in** to receive — one call via the harness Monitor TOOL (never Bash `run_in_background`, whose output goes nowhere):

```
drone @devpulse watchdog baseline
```

Sign-in syncs whatever queued while you were logged out (`MISSED` lines), pushes new reports live from then on, and logs out any older session — the newest sign-in owns delivery. `/clear` or a new chat destroys only the receiver — the conversation's ear; reports keep queueing regardless. At idle the entire system is one `stat()` on a file. The harness status line's **"1 monitor"** is the signed-in session itself, not a watcher — nothing is being watched.

Statusline: `watchdog:in` (green) — this session is signed in and ticking. `HUNG` (signed in, receiver frozen), `ELSEWHERE` (another session holds the sign-in), `OUT` (nobody is signed in) — all red, all mean sign in again. The green also requires the registered wire's `metadata.wrapper == "monitor"`; a foreground or background wire with no listener paints `watchdog:OUT`. The statusline source is tracked at `tools/statusline.sh`; install with `cp tools/statusline.sh ~/.claude/statusline.sh`.

## There is no passive wake

ai_mail's wake-back spawns a new headless process and can never inject into a live interactive session (`BLOCKED — interactive session` in the logs is that guard working as designed; it only serves senders whose session closed). Dispatch and idle without signing in and nothing will ever wake you — the report just queues.

## Dead-monitor backstop (FPLAN-0499, DPLAN-0314 "outcome M")

A dispatch whose monitor died — host reboot, OOM, kill — can never report, so the receiver announces it: at sign-in and every 5 minutes it reads `@ai_mail`'s dispatch register once (no agent is polled, no process is armed) and pushes one line per dispatch of yours whose monitor is gone: `monitor_alive` false (ai_mail records the monitor's pid and checks `/proc` at read time — a death is announced within one cadence, wording "its monitor (pid N) is gone before the hard timeout"), or past `expected_by` (ai_mail's hard timeout — a live monitor cannot overrun it). `monitor_alive` is tri-state; `None` (a row that never learned a pid) keeps the overdue rule only:

```
DEAD @prax [70da6e9c] dispatched 09-07 12:00 "..." — no completion by 09-07 14:00, the hard timeout: its monitor died (reboot, OOM, kill). Re-dispatch in continue mode.
```

Each death is announced once ever (cursor `devpulse_json/wire_dead_cursor.json`), so a re-sign-in never repeats one. `drone @devpulse watchdog status` shows the same rows on demand as "Dispatches overdue".

## Two rules the receiver enforces

- **Only completions wake.** The feed also carries dispatch *start* edges, and those are dropped — you are woken once, when the work is actually finished.
- **Only YOUR dispatches wake you.** The feed names the branch that *finished*, never the branch that *sent*, so every citizen's completion used to wake this seat fleet-wide. `@ai_mail` stamps `sender` on the completion line and the receiver compares it against this project's sealed owner. A record with no sender is **not** yours — unattributable fails closed.

## Crash coverage needs nothing running

Every dispatch is registered at send time with an `expected_by` taken from dispatch_monitor's hard timeout. An entry past that with no completion means the monitor *died* — a fact about a file, true whether or not anything is looking. `watchdog status` reads it.

## History — rounds 1–3 had a detection daemon; r4 deleted it

Commit `5444dd9a`. It polled ~19 branches' `.dispatch.lock` every 2 s to synthesize an event that `dispatch_monitor.py` had already reported 1–2 s earlier — every completion produced **two wakes**, for months, unnoticed because a duplicate wake looks exactly like a working wake. Idle cost: 7.72 % of a core. The source is preserved in git history at the removing commit, deliberately not in `.archive/` (gitignored disposal, cleaned without warning). `watchdog baseline --daemon` is refused by name.

## Stall detection on one long job

`watchdog agent @target [--timeout s]` remains for **mid-run stall detection** on a single long job (`[watchdog.stall]` / `[watchdog.resumed]` after 120 s of JSONL silence with no in-flight tool) — it is not needed to be woken, and arming one per dispatch is a second poller doing the receiver's job. `@target` resolves in the caller's own project, then falls back to `~/Projects` registries.

## Known caveat

A wire armed *before* the 2026-09-07 statusline change carries no `wrapper` field and paints `watchdog:OUT` until re-armed through the Monitor tool.
