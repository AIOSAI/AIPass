# =================== AIPass ====================
# Name: watchdog.py
# Description: Watchdog Module — directed wake system for devpulse
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""
Watchdog Module — devpulse's personal directed-wake system.

Subcommands:
  agent <id>       Wake when a dispatched agent process exits (Phase 1)
  status           List active watches via watchdog_active.json registry (Phase 4)
  timer <args>     Wake-in-N or named duration timer (Phase 2)
  schedule <time>  Wake at wall-clock time, optionally run a command (Phase 3)
  cancel <handle>  SIGTERM a specific watch + deregister (Phase 4)
  cancel --all     Kill every active watch (Phase 4)
  list             Alias for status (Phase 4)

Auto-discovered by devpulse.py via handle_command() convention.
Heavy handler imports are lazy — only imported when a subcommand is invoked.

See FPLAN-0186 for the build plan and DPLAN-0130 for the design record.
"""

import importlib
from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error, warning

_VALID_SUBCOMMANDS = ["agent", "timer", "schedule", "status", "cancel", "list"]
_DEFAULT_AGENT_TIMEOUT = 600
_NOT_IMPLEMENTED_MSG = "{sub} is not yet implemented in this phase — see FPLAN-0186 (Phase {phase})"
# Phase 4 wired cancel + list for real. Left the map so future deferrals can reuse the shape.
_PHASE_BY_SUB: dict[str, int] = {}

HELP_TEXT = """\
[bold cyan]watchdog[/bold cyan] — devpulse directed wake system

[bold]Usage:[/bold]
  watchdog agent <branch> [--timeout SECONDS]   Wake when dispatched agent exits
  watchdog status                               List active watches
  watchdog timer <duration>                     Wake in N (5m, 30s, 2h, 1h30m)
  watchdog timer start <name>                   Start named duration timer
  watchdog timer stop <name>                    Stop named timer + report elapsed
  watchdog timer list                           List active + historical timers
  watchdog timer report                         Formatted session summary
  watchdog schedule <time> [command]            Wake at HH:MM or +N, optional cmd
  watchdog cancel <handle>                      SIGTERM a specific watch + deregister
  watchdog cancel --all                         Kill every active watch
  watchdog list                                 Alias for status
  watchdog --help                               Show this help

[bold]Examples:[/bold]
  drone @devpulse watchdog agent @drone
  drone @devpulse watchdog agent @flow --timeout 600
  drone @devpulse watchdog timer 5m
  drone @devpulse watchdog timer start build-phase-3
  drone @devpulse watchdog timer stop build-phase-3
  drone @devpulse watchdog schedule "02:00"
  drone @devpulse watchdog schedule "+30m" "drone @git status"

See FPLAN-0186 (build plan) and DPLAN-0130 (design).
"""

_TIMER_HELP_TEXT = """\
[bold]watchdog timer[/bold] — wake-in-N + named duration tracking

Usage:
  watchdog timer <duration>           Wake in N (5m, 30s, 2h, 1h30m, 45)
  watchdog timer start <name>         Start a named duration timer
  watchdog timer stop <name>          Stop + report elapsed
  watchdog timer list                 Show active + history
  watchdog timer report               Formatted session summary
  watchdog timer --help               Show this help
"""

_SCHEDULE_HELP_TEXT = """\
[bold]watchdog schedule[/bold] — wall-clock or relative wake, optional command

Usage:
  watchdog schedule <time>            Wake at HH:MM[:SS] or +N (+30m, +1h30m)
  watchdog schedule <time> <command>  Wake + run command via shell
  watchdog schedule --help            Show this help

Examples:
  watchdog schedule "02:00"
  watchdog schedule "14:30" "drone @flow execute DPLAN-0200"
  watchdog schedule "+30m" "drone @git status"
"""


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("watchdog Module")
    console.print("Devpulse-local directed wake system. Wakes devpulse when a")
    console.print("watched condition fires (agent exit, timer, schedule).")
    console.print()
    console.print("Subcommands:")
    for sub in _VALID_SUBCOMMANDS:
        marker = "active" if sub in ("agent", "status") else f"phase {_PHASE_BY_SUB.get(sub, '?')}"
        console.print(f"  {sub:<10} ({marker})")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/watchdog/")
    console.print("    - agent.py (watch_agent — block until dispatched agent exits)")
    console.print()


def _guard_caller() -> bool:
    """Reject cross-branch invocation. Devpulse-only tool."""
    cwd = Path.cwd()
    if cwd.name == "devpulse" or any(p.name == "devpulse" for p in cwd.parents):
        return True
    warning("watchdog is a devpulse-only module — refusing cross-branch call")
    return False


def handle_command(command: str, args: List[str]) -> bool:
    """Route watchdog subcommands.

    Auto-discovered by devpulse.py module loader.

    Args:
        command: The primary command string.
        args: Additional arguments after the command.

    Returns:
        True if the command was handled, False otherwise.
    """
    if command != "watchdog":
        return False

    if not _guard_caller():
        return True

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        console.print(HELP_TEXT)
        return True

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand not in _VALID_SUBCOMMANDS:
        error(f"Unknown watchdog subcommand: {subcommand}", suggestion="Use 'watchdog --help' for usage")
        return True

    logger.info("[watchdog] subcommand=%s args=%s", subcommand, sub_args)

    if subcommand == "agent":
        return _handle_agent(sub_args)

    if subcommand == "status":
        return _handle_status()

    if subcommand == "list":
        return _handle_list()

    if subcommand == "timer":
        return _handle_timer(sub_args)

    if subcommand == "schedule":
        return _handle_schedule(sub_args)

    if subcommand == "cancel":
        return _handle_cancel(sub_args)

    if subcommand in _PHASE_BY_SUB:
        phase = _PHASE_BY_SUB[subcommand]
        console.print(_NOT_IMPLEMENTED_MSG.format(sub=subcommand, phase=phase))
        return True

    return True


def _handle_timer(sub_args: List[str]) -> bool:
    """Route ``watchdog timer`` subcommands through the timer handler."""
    if not sub_args:
        console.print(_TIMER_HELP_TEXT)
        return True

    if sub_args[0] in ("--help", "-h", "help"):
        console.print(_TIMER_HELP_TEXT)
        return True

    timer_mod = importlib.import_module("aipass.devpulse.apps.handlers.watchdog.timer")

    action = sub_args[0]

    if action == "start":
        if len(sub_args) < 2:
            error("Usage: watchdog timer start <name>")
            return True
        result = timer_mod.timer_start(sub_args[1])
        _print_timer_result(result)
        return True

    if action == "stop":
        if len(sub_args) < 2:
            error("Usage: watchdog timer stop <name>")
            return True
        result = timer_mod.timer_stop(sub_args[1])
        _print_timer_result(result)
        return True

    if action == "list":
        snapshot = timer_mod.timer_list()
        _print_timer_list(snapshot)
        return True

    if action == "report":
        console.print(timer_mod.timer_report())
        return True

    # Fall-through: treat the token as a duration for wake_in.
    try:
        result = timer_mod.wake_in(action)
    except ValueError as exc:
        logger.warning("[watchdog] invalid timer duration %r: %s", action, exc)
        error(f"Invalid duration: {action} ({exc})")
        return True
    _print_timer_result(result)
    return True


def _handle_schedule(sub_args: List[str]) -> bool:
    """Route ``watchdog schedule`` through the schedule handler.

    Positional form: ``schedule <time> [command]``. Command (when present)
    is the entire second positional arg — the caller is responsible for
    quoting multi-token shell commands in their invocation.
    """
    if not sub_args:
        console.print(_SCHEDULE_HELP_TEXT)
        return True

    if sub_args[0] in ("--help", "-h", "help"):
        console.print(_SCHEDULE_HELP_TEXT)
        return True

    time_str = sub_args[0]
    command = sub_args[1] if len(sub_args) >= 2 else None

    schedule_mod = importlib.import_module("aipass.devpulse.apps.handlers.watchdog.schedule")

    try:
        result = schedule_mod.wake_at(time_str, command=command)
    except ValueError as exc:
        logger.warning("[watchdog] invalid schedule %r: %s", time_str, exc)
        error(f"Invalid schedule: {time_str} ({exc})")
        return True

    _print_schedule_result(result)
    return True


def _print_schedule_result(result: dict) -> None:
    """Render a schedule handler return dict as CLI output."""
    scheduled_for = result.get("scheduled_for", "?")
    elapsed = result.get("elapsed", 0)
    console.print(f"[bold]watchdog schedule[/bold] woke after {elapsed}s (scheduled_for={scheduled_for})")
    if result.get("command"):
        exit_code = result.get("command_exit_code")
        console.print(f"  command: {result['command']} -> exit={exit_code}")
        stdout = result.get("command_stdout") or ""
        stderr = result.get("command_stderr") or ""
        if stdout:
            console.print(f"  stdout: {stdout.rstrip()}")
        if stderr:
            console.print(f"  stderr: {stderr.rstrip()}")


def _print_timer_result(result: dict) -> None:
    """Render a timer handler return dict as a single CLI line."""
    state = result.get("state", "unknown")
    name = result.get("name") or result.get("duration") or ""
    if state == "error":
        error(f"timer {name}: {result.get('reason', 'unknown error')}")
        return
    if state == "stopped":
        console.print(f"[bold]timer[/bold] {name} stopped -> elapsed={result.get('human', '?')}")
        return
    if state == "started":
        console.print(f"[bold]timer[/bold] {name} started at {result.get('started_at', '?')}")
        return
    if state == "woke":
        console.print(f"[bold]timer[/bold] {name} woke after {result.get('elapsed', 0)}s")
        return
    console.print(f"[dim]timer result:[/dim] {result}")


def _print_timer_list(snapshot: dict) -> None:
    """Pretty-print the ``timer_list`` snapshot."""
    active = snapshot.get("active", [])
    history = snapshot.get("history", [])
    console.print("[bold]Active timers:[/bold]")
    if active:
        for item in active:
            console.print(f"  - {item['name']}  elapsed {item['human']}  (started {item.get('started_at', '?')})")
    else:
        console.print("  (none)")
    console.print("[bold]History:[/bold]")
    if history:
        for item in history:
            console.print(
                f"  - {item['name']}  {item['human']}  ({item.get('started_at', '?')} -> {item.get('stopped_at', '?')})"
            )
    else:
        console.print("  (none)")


def _handle_agent(sub_args: List[str]) -> bool:
    """Parse `agent <id> [--timeout N]` and invoke the agent handler."""
    if not sub_args:
        error("Usage: watchdog agent <branch> [--timeout SECONDS]")
        return True

    timeout = _DEFAULT_AGENT_TIMEOUT
    positional: List[str] = []
    i = 0
    while i < len(sub_args):
        arg = sub_args[i]
        if arg == "--timeout" and i + 1 < len(sub_args):
            try:
                timeout = int(sub_args[i + 1])
            except ValueError as exc:
                logger.warning("[watchdog] invalid --timeout value %r: %s", sub_args[i + 1], exc)
                error(f"Invalid --timeout value: {sub_args[i + 1]}")
                return True
            i += 2
            continue
        positional.append(arg)
        i += 1

    if not positional:
        error("Usage: watchdog agent <branch> [--timeout SECONDS]")
        return True

    agent_id = positional[0]

    agent_mod = importlib.import_module("aipass.devpulse.apps.handlers.watchdog.agent")
    result = agent_mod.watch_agent(agent_id, timeout_seconds=timeout)

    state = result.get("agent_state", "unknown")
    reason = result.get("reason", "")
    elapsed = result.get("elapsed", 0)
    console.print(f"[bold]watchdog agent[/bold] {agent_id} -> state={state} elapsed={elapsed}s reason={reason}")
    console.print(
        f'watchdog: {agent_id} stopped (state={state}). Next: drone @ai_mail dispatch {agent_id} "check in" "..."'
    )
    return True


def _load_registry_module():
    """Lazy-import the watch registry. Keeps cold startup fast."""
    return importlib.import_module("aipass.devpulse.apps.handlers.watchdog.registry")


def _load_timer_module_for_format():
    """Lazy-import timer for ``format_human`` (reused in the status output)."""
    return importlib.import_module("aipass.devpulse.apps.handlers.watchdog.timer")


def _format_status_line(watch: dict, format_human) -> str:
    """One-line renderer for a single watch entry in the status output."""
    handle = watch.get("handle", "?")
    wtype = watch.get("type", "?")
    elapsed = int(watch.get("elapsed_seconds", 0))
    pid = watch.get("pid", "?")
    meta = watch.get("metadata") or {}

    if wtype == "agent":
        tail = f"{meta.get('agent_id', '?')} (timeout={meta.get('timeout_seconds', '?')}s)"
    elif wtype == "timer":
        tail = f"duration={meta.get('duration', '?')}"
    elif wtype == "schedule":
        tail_cmd = meta.get("command")
        cmd_repr = f' cmd="{tail_cmd}"' if tail_cmd else ""
        tail = f"scheduled={meta.get('scheduled_for', '?')}{cmd_repr}"
    else:
        tail = str(meta)

    # Escape the [ so Rich console doesn't interpret it as a style tag.
    return f"  \\[{handle}]  {wtype:<8}  {format_human(elapsed):<10}  pid={pid}  {tail}"


def _handle_status() -> bool:
    """Read the watch registry, prune stale entries, pretty-print active watches."""
    registry_mod = _load_registry_module()
    timer_mod = _load_timer_module_for_format()

    # list_active handles its own stale pruning — we just count survivors
    # before and after to know if we pruned anything to report.
    pre = registry_mod.list_active(prune_stale=False)
    post = registry_mod.list_active(prune_stale=True)
    pruned = len(pre) - len(post)

    console.print("[bold]Watchdog Status[/bold]")
    console.print("===============")

    if not post:
        console.print("No active watches.")
        if pruned:
            console.print(f"[dim]Pruned {pruned} stale watch(es).[/dim]")
        return True

    console.print(f"{len(post)} active watch(es):")
    console.print()
    for watch in post:
        console.print(_format_status_line(watch, timer_mod.format_human))

    if pruned:
        console.print(f"[dim]Pruned {pruned} stale watch(es).[/dim]")
    else:
        console.print("[dim]No stale watches to prune.[/dim]")
    return True


def _handle_list() -> bool:
    """Alias for ``status`` — terser framing chosen: same output.

    Phase 4 Notes: `list` just routes to `_handle_status`. The UX bar for
    differentiating wasn't worth the divergence.
    """
    return _handle_status()


def _print_kill_result(result: dict) -> None:
    """Render a single ``registry.kill_watch`` result on one line."""
    handle = result.get("handle", "?")
    killed = result.get("killed", False)
    was_alive = result.get("was_alive", False)
    reason = result.get("reason", "")
    status = "KILLED" if killed else "FAILED"
    console.print(f"  \\[{handle}] {status} was_alive={was_alive} reason={reason}")


def _handle_cancel(sub_args: List[str]) -> bool:
    """Route ``watchdog cancel <handle>`` or ``cancel --all`` through the registry."""
    if not sub_args:
        error("Usage: watchdog cancel <handle> | watchdog cancel --all")
        return True

    registry_mod = _load_registry_module()

    if sub_args[0] == "--all":
        results = registry_mod.kill_all()
        if not results:
            console.print("No active watches to cancel.")
            return True
        console.print(f"[bold]Cancelling {len(results)} watch(es):[/bold]")
        for result in results:
            _print_kill_result(result)
        return True

    handle = sub_args[0]
    result = registry_mod.kill_watch(handle)
    _print_kill_result(result)
    if not result.get("killed", False):
        logger.info("[watchdog] cancel failed handle=%s", handle)
    return True
