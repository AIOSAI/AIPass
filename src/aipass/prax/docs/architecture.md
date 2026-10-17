[<- Back to the README](../README.md)

# Architecture — routing, gates and seams

How a command reaches a handler: the router, the unknown-argument gate, the exit seam, help behaviour, and the status module.

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

**An unknown command or argument FAILS** — non-zero exit, a message naming the
token, a did-you-mean where one is close. A command fails it two ways if nothing
guards it: argparse's `parse_known_args` hands an unrecognised flag back instead
of erroring, so the flag is silently ignored; and a module that prints a refusal
and then returns `True` is read by the router as "handled" and exits 0 — truth on
screen, a lie in `$?`.

One gate guards it, `handlers/cli/arg_gate.py`. It DECIDES and does not
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
`error()` sets a process-level failure flag, and a flag only becomes an exit code
where somebody reads it.

`main()` calls `reset_command_state()` at entry, and `_run()` returns
`resolve_exit(True)` when `route_command` handles the command. A handler that
called `error()` exits **2** (`dashboard refresh @nosuchbranch` prints
`Branch 'NOSUCHBRANCH' not found in registry` and exits 2); an unknown token exits
1; a clean run exits 0. The reset is at the entry point so a flag left set by an
earlier in-process run cannot leak into the next. A partial `dashboard refresh
--all` — some branches updated, some failed — reports through `error()`, so a run
that left branches stale does not exit 0.

## How It Works

1. **Auto-routing** — `logger.info()` inspects the call stack to identify the caller's module, branch, and file path, then routes the log entry to the correct per-module log file.
2. **Two-tier logging** — Each log entry goes to both `system_logs/` (central, all branches) and `<branch>/logs/` (branch-local), both with size-based rotation.
3. **Self-healing** — Auto-creates missing log directories, falls back to `system_logs/external/` for unknown modules, provides NullLogger if prax itself fails to import.
4. **Mission Control** — Four threads: display worker (pulls from event queue), file watcher (watchdog on branch `apps/` dirs), log watcher (tails `system_logs/*.log`), rate tracker (scans `system_logs/` for runaway growth every 10s). Falls back to polling when inotify is exhausted.
5. **Multi-CLI monitoring** — Watches Claude Code JSONL and Codex JSONL session files. Extracts agent activity (thinking, tool use, responses) with model detection and branch resolution.
6. **Runaway-log detection** — Rate tracker measures byte growth per log file, estimates lines/min from byte deltas. Sustained thresholds: WARNING (>100 lines/min for 2 min), CRITICAL (>10 lines/sec for 1 min). Fires `runaway_log_detected` on the trigger event bus. State persists to disk across process restarts. Per-file suppression available.
7. **Dashboard** — Template-based per-branch dashboard files. Refreshes from central files (`*.central.json`). Write-through API for services to update sections directly.
8. **STATUS sync** — `status sync` scans every branch's `STATUS.local.md` and builds the aggregate, then writes nothing. See the status module below.

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

A gate at `args[0]` only, or a screen for `--help` but not `-h` (which survives a
`--`-prefix filter because it carries a single dash), lets a help request run the
command: `log_audit.py enforce -h` would truncate every oversized log. The
predicate lives in `handlers/cli/help_flags.py` — pure argument inspection, no
I/O. Its sibling `handlers/cli/arg_gate.py` answers the opposite question — "is
this token one we do not define?" — and is described under the unknown-argument
gate.

## Status

```bash
drone @prax status                       # System health (modules, loggers, last discovery scan)
drone @prax status sync                  # Scans branch STATUS.local.md files — writes nothing (see below)
drone @prax status --help                # Status usage
```

**`status sync` scans and declines to write.** The STATUS flow is
decommissioned: branch state lives in `DASHBOARD.local.json`, and the automatic
path has no trigger registration. The engine stays revivable, so the scan, the
registry read and the aggregate are all still built, and nothing is written: the
call returns `status: "declined"` with the reason, and the command says so rather
than reporting a write.
