# Architecture — routing, gates and seams

How a command reaches a handler: the router, the unknown-argument gate, the exit seam, help behaviour, and the status module.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## Design Pattern

The entry point (`prax.py`) has zero business logic — it auto-discovers modules in `apps/modules/` and routes commands. Each module is a thin orchestrator over its handlers. Handlers are never imported by external branches.

## Command Routing

```
drone @prax monitor run
  → prax.py discovers modules (glob apps/modules/*.py)
  → calls monitor.handle_command("monitor", ["run"])
  → monitor.py delegates to handlers/monitoring/*
```

## The unknown-argument gate

Patrick's standing ruling: **an unknown command or argument FAILS** — non-zero
exit, a message naming the token, a did-you-mean where one is close. @devpulse's
fleet CLI sweep (2026-09-07) found prax breaking it in six places, and they
broke it two different ways:

- `drone @prax --definitely-not-a-flag` printed the self-map and exited **0** —
  output byte-identical to a clean no-args run. argparse's `parse_known_args`
  hands an unrecognised flag back instead of erroring, so nothing ever looked at
  it. `status bogus` was the same silence at the module level: the normal status
  block, no complaint, exit 0.
- `log-audit`, `log-health`, `monitor` and `dashboard` each printed the right
  refusal and then **returned `True`**, which the router reads as "handled" and
  turns into exit 0. Truth on screen, a lie in `$?`.

The cure is one gate, `handlers/cli/arg_gate.py`. It DECIDES and does not
display: `refuse()` logs the refusal through `json_handler` and raises
`UnknownArgument`; `prax.py` catches it once, renders through cli, returns 1.
`route_command` re-raises it past its own blanket `except Exception`, because a
refusal reported as "Handler failed" loses the token the caller needs. The
modules import the gate directly; the entry point imports it re-exported through
`apps/modules/__init__.py`, since an entry point never reaches into handlers.

Help still wins over the gate everywhere: `wants_help(args)` runs first, so
`status sync -h` and `dashboard refrsh --help` explain themselves rather than
failing. A question is never a bad argument.

## The exit seam

The gate above covers refusals prax *raises*. It does not cover the other way a
command fails: a handler that routes fine, prints an error, and returns. cli's
`error()` sets a process-level failure flag, but a flag only becomes an exit
code where somebody reads it — and `main()` returned a bare `0` on any routed
command, so `error()` changed the colour on screen and nothing else.

Closed 2026-09-08 (FPLAN-0512, the fleet rule @devpulse landed in memory first):
`main()` calls `reset_command_state()` at entry, and `_run()` returns
`resolve_exit(True)` instead of `0` when `route_command` handles the command.
A handler that called `error()` now exits **2**; an unknown token still exits 1;
a clean run still exits 0. The reset is at the entry point so a flag left set by
an earlier in-process run cannot leak into the next.

Measured after the change: `dashboard refresh @nosuchbranch` → **2** (it printed
`Branch 'NOSUCHBRANCH' not found in registry` and exited **0** before), `status`
→ **0**.

The one caller this changed is `dashboard refresh --all`. A partial refresh —
some branches updated, some failed — announced itself through `warning()`, which
does not set the flag, so a run that left branches stale exited 0. It now goes
through `error()`.

## How It Works

1. **Auto-routing** — `logger.info()` inspects the call stack to identify the caller's module, branch, and file path, then routes the log entry to the correct per-module log file.
2. **Two-tier logging** — Each log entry goes to both `system_logs/` (central, all branches) and `<branch>/logs/` (branch-local), both with size-based rotation.
3. **Self-healing** — Auto-creates missing log directories, falls back to `system_logs/external/` for unknown modules, provides NullLogger if prax itself fails to import.
4. **Mission Control** — Four threads: display worker (pulls from event queue), file watcher (watchdog on branch `apps/` dirs), log watcher (tails `system_logs/*.log`), rate tracker (scans `system_logs/` for runaway growth every 10s). Falls back to polling when inotify is exhausted.
5. **Multi-CLI monitoring** — Watches Claude Code JSONL and Codex JSONL session files. Extracts agent activity (thinking, tool use, responses) with model detection and branch resolution.
6. **Runaway-log detection** — Rate tracker measures byte growth per log file, estimates lines/min from byte deltas. Sustained thresholds: WARNING (>100 lines/min for 2 min), CRITICAL (>10 lines/sec for 1 min). Fires `runaway_log_detected` on the trigger event bus. State persists to disk across process restarts. Per-file suppression available.
7. **Dashboard** — Template-based per-branch dashboard files. Refreshes from central files (`*.central.json`). Write-through API for services to update sections directly.
8. **STATUS sync** — *(Decommissioned by TDPLAN-0007, but still reachable.)* Scans all branch `STATUS.local.md` files and writes an aggregated `STATUS.md` to the repo root. The automatic path is genuinely dead — the trigger registration was unwired — but the `status sync` subcommand still calls the engine, so running it recreates a file the fleet deleted. See the status module below.

## Asking for help never does the thing

Every module screens the **whole argument sequence** for help, not just the
first token, inside `handle_command` — so the guarantee holds however the module
is reached: through drone, through `prax.py`, or by running the file directly.

- `--help` and `-h` count **anywhere** on the line, matched exactly (`--help-me`
  and `-hx` are not help flags).
- The bare word `help` counts **only in the first slot**, because branch names,
  log filenames and grep patterns are free text — `monitor run help` scopes to a
  branch called `help`.
- The gate sits *after* each module's ownership check, since `prax.py` routes by
  trying modules in turn; a scan at the top of the function would let one module
  answer another's `--help`.

This was not theoretical. Modules gated help at `args[0]` only, and the
standalone paths screened `--help` but not `-h` — which survives a `--`-prefix
filter because it carries a single dash. `log_audit.py enforce -h` truncated
every oversized log, and `monitor.py run -h` started a live Mission Control.
Found by @seedgo's `help_flag_safety` standard, 2026-08-13; `dashboard.py`
already scanned both spellings and was the reference implementation. The
predicate lives in `handlers/cli/help_flags.py` — pure argument inspection, no
I/O, matching the convention @memory, @trigger, @drone and @ai_mail settled the
same day. Its sibling `handlers/cli/arg_gate.py` answers the opposite question —
"is this token one we do not define?" — and is described under Command Routing.

## Status

```bash
drone @prax status                       # System health (modules, loggers, last discovery scan)
drone @prax status sync                  # ⚠ STILL WIRED — recreates repo-root STATUS.md (see below)
drone @prax status --help                # Status usage
```

**`status sync` is not dormant, and that is a defect.** TDPLAN-0007
decommissioned the STATUS flow: `STATUS.local.md` and the aggregated
`STATUS.md` were deleted across every branch, and the engine was made inert by
unwiring its *trigger registration*. The CLI subcommand was never unwired —
`status sync` still routes to `sync_status()`, which walks every branch and
writes `STATUS.md` back to the repo root, resurrecting a file the fleet
decided to delete. This README described the command as dormant until the
2026-08-13 audit ran it and recreated the file. The engine is intentionally
revivable, so the fix (refuse and point at `DASHBOARD.local.json`, or finish
the decommission) is a ruling for @devpulse, not a unilateral prax change —
tracked in APLAN-0009. Until then, treat this command as one that writes.

