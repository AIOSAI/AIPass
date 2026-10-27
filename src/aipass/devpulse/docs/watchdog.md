[← Back to DevPulse](../README.md)

# Watchdog — how it works

The deep reference, for when watchdog misbehaves. Day to day you only need the sign-in in the branch prompt and the command table in the README.

## Who may call it

The project OWNER only — the first agent, seated as `owner: true` in the project's sealed `*_REGISTRY.json`. Portable: `@devpulse` in AIPass, `@vera` in Vera Studio, whoever owns elsewhere. A refusal means your project's owner isn't seated — run `aipass doctor` to see why and `aipass doctor --fix` to repair.

## The model — a login, not a service

Watchdog is always on because nothing runs. Dispatching registers the job at send time; the agent that finishes **reports**; `@ai_mail` writes that report to a durable notification feed, where it **queues** whether anyone is listening or not. A conversation **signs in** to receive.

## The sign-in — one shot, in the background

Nothing happening, nothing happens. Arm with the Bash tool, `run_in_background: true`:

```
drone @devpulse watchdog baseline --once
```

It syncs whatever queued while you were logged out (`MISSED` lines), then sits silent. It **exits** on the first completion of a dispatch this seat sent, or on a dead monitor — and that exit is the one wake, carrying the report. Re-arm inside that same turn while work is still out; with nothing out, arm nothing. The newest sign-in owns delivery and logs out any older one of the same seat; another seat's wire (a project manager's, `metadata.seat` in the registry) is left alone, since it delivers that seat's completions. The seat is the sealed owner of the caller's project: drone runs the handler in devpulse's directory and passes the caller's along, so `@vera` arming from Vera-Studio is `@vera`, not `@devpulse`. Every seat keeps its own feed cursor and dead cursor (`devpulse_json/<seat>.feed_cursor.json`), since a drain marks every line seen, delivered or not, and one cursor shared by two seats would swallow the other's completions. `watchdog status` lists the caller's seat's dispatches only and names the seat on each wire row. At idle the whole system is one `stat()` a second, 0.033 % of a core, and **zero model turns**.

Arm it bare: no pipe and no redirect after the command. The wire reads its own stdout to tell which wrapper carries it; behind a pipe it still wakes on exit, but it records `foreground`, the statusline does not count it, and the wire says so on stderr at arm time.

Why not the Monitor tool: Claude Code caps every Monitor watch at 30 minutes and notifies the seat to re-arm; no setting restores a persistent watch. A continuous wire under Monitor therefore dies every 30 minutes and wakes the seat to say so, and over a long absence those empty wakes alone can force an auto-compact. Background Bash has no timer on it, survives `/compact`, and notifies exactly once, on exit, which is the shape `--once` is built for.

**The one thing that does end it: the harness reaps background shells under memory pressure.** Its idea of pressure is not the kernel's `available` figure, so a reap can land on a box with gigabytes free. It happens only while the session is idle, it says nothing about the wire's own memory (a few MB), and it arrives as one `killed` notification, so the seat is woken and knows. The harness's own instruction is not to restart it unprompted. The off-switch is an environment variable Claude Code must be **started** with, `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1`; setting it from a shell command inside the session has no effect. A reaped wire with work still out is the case to watch: re-arm when the owner says so, or run with the switch set.

Not covered: what `/clear`, `/resume` or closing the terminal do to a live wire. Reports keep queueing regardless, and the next sign-in replays them; a lost receiver costs latency, never a report. After a compact, check TaskList for a live wire before arming a second.

The continuous form (`watchdog baseline`, no `--once`) exists for a harness whose Monitor tool is uncapped. It **refuses** background Bash by design: that wrapper notifies only on exit, and a continuous wire never exits, so it would give zero wakes by construction. The refusal names the one-shot.

## Statusline

`watchdog:in` (green) — this session holds a live wire and it is ticking. `watchdog:idle` (dim) — no wire armed; the designed resting state when nothing is out. `HUNG` (red) — wire registered, pid alive, heartbeat stale over 15 s: the corpse that looks signed-in everywhere else. `ELSEWHERE` (red) — another session holds the sign-in.

Green needs the registered wire's `metadata.wrapper` to be `monitor` or `background`; the continuous wire refuses background Bash before it registers, so a registered `background` wire is always a one-shot. What the line cannot see: work that is out with **no** wire armed also reads `idle`. Source is tracked at `tools/statusline.sh`; install with `cp tools/statusline.sh ~/.claude/statusline.sh`.

## There is no passive wake

ai_mail's wake-back spawns a new headless process and can never inject into a live interactive session (`BLOCKED — interactive session` in the logs is that guard working as designed; it only serves senders whose session closed). Dispatch and idle without signing in and nothing will ever wake you — the report just queues.

## Dead-monitor backstop

A dispatch whose monitor died — host reboot, OOM, kill — can never report, so the receiver announces it: at sign-in and every 5 minutes it reads `@ai_mail`'s dispatch register once (no agent is polled, no process is armed) and pushes one line per dispatch of yours whose monitor is gone: `monitor_alive` false (ai_mail records the monitor's pid and checks `/proc` at read time — a death is announced within one cadence, wording "its monitor (pid N) is gone before the hard timeout"), or past `expected_by` (ai_mail's hard timeout for the attempt). Overdue is not proof of death: ai_mail retries a dispatch up to three times with a fresh timeout each attempt, so an overdue row is often a live monitor part way through attempt 2, and the line says so. `monitor_alive` is tri-state; `None` (a row that never learned a pid) keeps the overdue rule only:

```
DEAD @prax [70da6e9c] dispatched 09-07 12:00 "..." — no completion by 09-07 14:00, the hard timeout. Nothing here checked whether its monitor is alive, and ai_mail retries a dispatch up to three times with a fresh timeout each attempt, so an overdue row is often a live monitor part way through attempt 2. Check the service and the dispatch log first: re-dispatching over a running retry doubles the work.
```

Each death is announced once ever (cursor `devpulse_json/wire_dead_cursor.json`), so a re-sign-in never repeats one — and a one-shot does not exit on a death it already announced. `drone @devpulse watchdog status` shows the same rows on demand as "Dispatches overdue".

## Two rules the receiver enforces

- **Only completions wake.** The feed also carries *start* edges, and there are two sorts. A direct wake writes `kind="wake"`, dropped by kind — the receiver reads `dispatch` only. The daemon's start edge is `kind="dispatch"`, the same as a completion, so kind cannot filter it: it is dropped because it carries no `sender`, and rule two fails it closed. You are woken once, when the work is actually finished.
- **Only YOUR dispatches wake you.** The feed names the branch that *finished*, never the branch that *sent*, so the sender has to be stamped: `@ai_mail` writes `sender` on the completion line and the receiver compares it against this project's sealed owner. Without that stamp every citizen's completion would wake this seat fleet-wide. A record with no sender is **not** yours; unattributable fails closed.

## Crash coverage needs nothing running

Every dispatch is registered at send time with an `expected_by` taken from dispatch_monitor's hard timeout. An entry past that with no completion is overdue — a fact about a file, true whether or not anything is looking: the monitor died, or it is on a later attempt with a fresh timeout. `monitor_alive` false is the death; overdue alone is a prompt to look before re-dispatching. `watchdog status` reads both.

## No detection daemon

`watchdog baseline --daemon` is refused by name. A poller that synthesizes completion events from the branches' `.dispatch.lock` files reports what `dispatch_monitor.py` has already written to the feed, so every completion would wake the seat **twice**, and a duplicate wake looks exactly like a working one, so nobody notices. It also costs CPU at idle. The feed is the only source.

## Stall detection on one long job

`watchdog agent @target [--timeout s]` remains for **mid-run stall detection** on a single long job (`[watchdog.stall]` / `[watchdog.resumed]` after 300 s of JSONL silence with no in-flight tool; 120 s false-fired on every long response and compaction) — it is not needed to be woken, and arming one per dispatch is a second poller doing the receiver's job. Under background Bash its per-line events land in the task's output file and are read when it exits, so it does not need the Monitor tool. It is not the sign-in: `watchdog agent` wires with no `baseline --once` armed leave every completion queued as `MISSED` while the statusline reads `idle`, so the verb says at arm time whether this session holds a sign-in wire, and names it. `@target` resolves in the caller's own project, then falls back to `~/Projects` registries.

A branch whose session pointer (`.ai_mail.local/session.json`) names provider `codex` is watched through its one rollout under `~/.codex/sessions/YYYY/MM/DD/rollout-*-<thread_id>.jsonl`, re-read from the pointer on each refresh so a provider switch is followed. A Codex turn is in flight until the rollout's last line is an `event_msg` of type `task_complete` or `turn_aborted`. An unparseable last line counts as in flight. The wire and `watchdog agent` take this seat's session id from `CLAUDE_CODE_SESSION_ID`, and when it is absent, from a Codex pointer's thread id.
