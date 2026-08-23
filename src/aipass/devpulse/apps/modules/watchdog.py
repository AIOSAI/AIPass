# =================== AIPass ====================
# Name: watchdog.py
# Description: Watchdog Module — directed wake system for devpulse
# Version: 2.0.0
# Created: 2026-04-14
# Modified: 2026-08-22
# =============================================

"""
Watchdog Module — devpulse's personal directed-wake system.

Subcommands:
  agent <id>       Wake when a dispatched agent process exits (Phase 1)
  baseline         Wake on ANY citizen completion — the always-on profile (DPLAN-0308)
  status           List active watches via watchdog_active.json registry (Phase 4)
  timer <args>     Wake-in-N or named duration timer (Phase 2)
  schedule <time>  Wake at wall-clock time, optionally run a command (Phase 3)
  cancel <handle>  SIGTERM a specific watch + deregister (Phase 4)
  cancel --all     Kill every active watch (Phase 4)
  list             Alias for status (Phase 4)

Auto-discovered by devpulse.py via handle_command() convention.
Heavy handler imports are lazy — only imported when a subcommand is invoked.

Design record: DPLAN-0130 (original), DPLAN-0308 (r2, wire/daemon split),
DPLAN-0317 (r4, the daemon deleted — the current shape). Builds: FPLAN-0186,
FPLAN-0451, FPLAN-0452.
"""

import importlib
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, err_console, error
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.watchdog import presenter

_VALID_SUBCOMMANDS = ["agent", "baseline", "timer", "schedule", "status", "cancel", "list"]
_DEFAULT_AGENT_TIMEOUT = 600

# Subcommands that are fully wired. Everything in _VALID_SUBCOMMANDS is, today —
# the list exists so the introspection view stops claiming otherwise. It used to
# read a _PHASE_BY_SUB dict that was permanently empty and never assigned
# anywhere in the repo, so timer/schedule/cancel/list each rendered as
# "phase ?" while being completely implemented (FPLAN-0452 P3).
_WIRED_SUBCOMMANDS = frozenset(_VALID_SUBCOMMANDS)

HELP_TEXT = """\
[bold cyan]watchdog[/bold cyan] — devpulse directed wake system

[bold]Usage:[/bold]
  watchdog agent <branch> [--timeout SECONDS]   Wake when dispatched agent exits
  watchdog baseline                             Arm THIS session's wire: deliver my dispatch completions
  watchdog baseline --once                      Wire until the first delivered completion
  watchdog status                               List active watches
  watchdog timer <duration>                     Wake in N (5m, 30s, 2h, 1h30m)
  watchdog timer start <name>                   Start named duration timer
  watchdog timer stop <name>                    Stop named timer + report elapsed
  watchdog timer list                           List active + historical timers
  watchdog timer report                         Formatted session summary
  watchdog schedule <time> \\[command]            Wake at HH:MM or +N, optional cmd
  watchdog cancel <handle>                      SIGTERM a specific watch + deregister
  watchdog cancel --all                         Kill every active watch
  watchdog list                                 Alias for status
  watchdog --help                               Show this help

[bold]Examples:[/bold]
  drone @devpulse watchdog agent @drone
  drone @devpulse watchdog agent @flow --timeout 600
  drone @devpulse watchdog baseline            (via Monitor, description "watchdog" — one line per completion,
                                                replays events missed while no wire was up)
  drone @devpulse watchdog baseline --once     (via run_in_background — wake on first)
  drone @devpulse watchdog timer 5m
  drone @devpulse watchdog timer start build-phase-3
  drone @devpulse watchdog timer stop build-phase-3
  drone @devpulse watchdog schedule "02:00"
  drone @devpulse watchdog schedule "+30m" "drone @git status"

Current design: DPLAN-0317 (r4 — completion is reported by the finishing agent,
not discovered by polling). Earlier rounds: DPLAN-0130, DPLAN-0308.
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
    console.print("[bold cyan]watchdog Module[/bold cyan]")
    console.print("[dim]Devpulse-local directed wake system. Wakes devpulse when a[/dim]")
    console.print("[dim]watched condition fires (agent exit, timer, schedule).[/dim]")
    console.print()
    console.print("[yellow]Subcommands:[/yellow]")
    for sub in _VALID_SUBCOMMANDS:
        marker = "active" if sub in _WIRED_SUBCOMMANDS else "unwired"
        console.print(f"  [cyan]{sub:<10}[/cyan] [dim]({marker})[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/watchdog/[/cyan]")
    console.print("    [dim]- agent.py (watch_agent — block until dispatched agent exits)[/dim]")
    console.print("    [dim]- wire.py (arm_wire — deliver MY dispatch completions into this session)[/dim]")
    console.print("    [dim]- dispatches.py (the register — which dispatches are this seat's)[/dim]")
    console.print()


def _owner_address() -> str | None:
    """Whose watchdog this is, for the refusal message. None if unresolvable.

    Named rather than described: "owner-only" tells a stranger they are in the
    wrong place but not where the right place is, and a refusal with no next
    step is what teaches people to route around a gate.
    """
    from aipass.devpulse.apps.handlers.owner.guard import owner_address

    return owner_address()


def _guard_caller() -> bool:
    """Reject non-owner invocation. Owner-only tool.

    Gates on the PROJECT OWNER (sealed registry) via the shared owner guard, so
    it works across projects — not a hardcoded 'devpulse' name. (Drone runs a
    routed module with cwd=<branch_path>, so Path.cwd() can't identify the real
    caller; the guard reads the AIPASS_CALLER_* env drone sets.) #681.

    Uses ``error`` and NOT ``warning``, which is the whole point of this
    docstring. ``warning`` does not call ``mark_command_failed``, so for months
    this refusal EXITED 0: ``watchdog baseline && <next step>`` ran the next
    step believing the wire was armed, and nothing in the exit status said
    otherwise. @canary found it from a non-owner seat on 2026-08-22 and proved
    it was specific rather than a drone-wide limitation — unknown subcommand
    exits 2, this exited 0. A refusal that does not flip the exit code is a
    lie to every caller that is not a human reading stderr.
    """
    from aipass.devpulse.apps.handlers.owner.guard import guard_owner_caller

    if guard_owner_caller("watchdog"):
        return True
    owner = _owner_address()
    whose = f"it belongs to {owner}" if owner else "no owner is sealed for this project"
    error(
        "watchdog is owner-only and this seat is not the owner",
        suggestion=(
            f"{whose} — ownership is the entry marked owner: true in the project's sealed registry. "
            "Ask that seat to arm it, or run 'aipass doctor' if you believe the seat is wrong. "
            "'watchdog --help' works from anywhere."
        ),
    )
    return False


def _wants_help(args: List[str]) -> bool:
    """Help flag anywhere in args = explain, never execute (DPLAN-0291 rule E).

    Bare word 'help' counts only at position 0 — later positions may be values.
    """
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


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

    # EXPLAIN BEFORE GATE, EXECUTE AFTER IT. The gate used to run first, which
    # made --help owner-only too: a non-owner got "refusing non-owner call" and
    # could not read the text that would have told them whose module it is.
    # Help is precisely the verb that must survive an ownership check, because
    # it is how a stranger discovers the thing is not theirs (@canary, from a
    # non-owner seat, 2026-08-22). It also restores this module's own rule E
    # (DPLAN-0291), which _wants_help documents and the gate outranked, and it
    # matches @ai_mail's identity fence, which leaves help/version open for the
    # same reason. Neither branch reveals anything privileged — both print
    # static text that is already in a public repo.
    if not args:
        print_introspection()
        return True

    if _wants_help(args):
        console.print(HELP_TEXT)
        return True

    if not _guard_caller():
        return True

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand not in _VALID_SUBCOMMANDS:
        error(f"Unknown watchdog subcommand: {subcommand}", suggestion="Use 'watchdog --help' for usage")
        return True

    logger.info("[watchdog] subcommand=%s args=%s", subcommand, sub_args)
    json_handler.log_operation("watchdog_command", {"subcommand": subcommand, "args": sub_args})

    if subcommand == "agent":
        return _handle_agent(sub_args)

    if subcommand == "baseline":
        return _handle_baseline(sub_args)

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
        presenter.print_timer_result(result)
        return True

    if action == "stop":
        if len(sub_args) < 2:
            error("Usage: watchdog timer stop <name>")
            return True
        result = timer_mod.timer_stop(sub_args[1])
        presenter.print_timer_result(result)
        return True

    if action == "list":
        snapshot = timer_mod.timer_list()
        presenter.print_timer_list(snapshot)
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
    presenter.print_timer_result(result)
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

    presenter.print_schedule_result(result)
    return True


def _handle_agent(sub_args: List[str]) -> bool:
    """Parse `agent <id> [--timeout N]` and invoke the agent handler."""
    if not sub_args:
        error("Usage: watchdog agent <branch> [--timeout SECONDS]")
        return True

    # Reminder, not an error: this call blocks until the agent exits, so it must
    # run via the Monitor tool (not run_in_background) for the wake to fire on
    # completion. MUST go to stderr: the Monitor tool treats every STDOUT line
    # as a wake event, so a stdout banner fires a spurious wake at arm time —
    # stdout carries completion/stall events only (#634 contract; VERA feedback
    # 315c005e). error() is also wrong — ❌ trips the exit-code fail-flag on an
    # otherwise-successful watch (#661 output_routing).
    err_console.print("[dim]watchdog agent: invoke via Monitor tool, not run_in_background[/dim]")

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
    if state == "completed_silent":
        console.print(
            f"watchdog: {agent_id} stopped (state={state}) -- CHECK DELIVERABLES. "
            f'Next: drone @ai_mail dispatch {agent_id} "check in" '
            '"You finished your last task but did not send a reply. '
            f'Please reply with your results now via drone @ai_mail email @devpulse."'
        )
    elif state == "completed_replied":
        console.print(f"watchdog: {agent_id} stopped (state={state}). Reply detected — check inbox.")
    else:
        console.print(
            f'watchdog: {agent_id} stopped (state={state}). Next: drone @ai_mail dispatch {agent_id} "check in" "..."'
        )
    return True


def _handle_baseline(sub_args: List[str]) -> bool:
    """Route ``watchdog baseline [--once]`` (DPLAN-0317 r4).

    The ARM DOOR (wire.py): take the delivery wire for THIS session, replay
    completions missed while nothing was wired, follow the notification feed.
    Run it via the Monitor tool with description "watchdog". ``--once`` wires
    until the first delivered completion (run_in_background style).

    ``--daemon`` was removed in r4. There is no detection process any more: the
    agent that finishes REPORTS, and this wire delivers what it reported. The
    flag is rejected by name below rather than as "unknown", because an
    operator or a stale script passing it deserves to be told the lane changed
    instead of being told they made a typo.
    """
    once = False
    for arg in sub_args:
        if arg == "--once":
            once = True
            continue
        if arg == "--daemon":
            error(
                "--daemon was removed in watchdog r4",
                suggestion=(
                    "There is no detection daemon. Completion is reported by the finishing agent, "
                    "not discovered by polling. Arm the wire alone: watchdog baseline"
                ),
            )
            return True
        error(f"Unknown baseline flag: {arg}", suggestion="Usage: watchdog baseline [--once]")
        return True

    # stderr, never stdout: the Monitor tool reads every stdout line as a wake
    # event, so an arm-time banner there fires a spurious wake (same contract as
    # _handle_agent's reminder, #634).
    err_console.print("[dim]watchdog baseline: arming the wire (run via Monitor, description 'watchdog')[/dim]")

    wire_mod = importlib.import_module("aipass.devpulse.apps.handlers.watchdog.wire")
    result = wire_mod.arm_wire(once=once)

    state = result.get("state", "unknown")
    err_console.print(
        f"[dim]watchdog baseline: state={state} replayed={result.get('replayed', 0)} "
        f"delivered={result.get('delivered', 0)} ticks={result.get('ticks', 0)}[/dim]"
    )
    return True


def _load_registry_module():
    """Lazy-import the watch registry. Keeps cold startup fast."""
    return importlib.import_module("aipass.devpulse.apps.handlers.watchdog.registry")


def _load_timer_module_for_format():
    """Lazy-import timer for ``format_human`` (reused in the status output)."""
    return importlib.import_module("aipass.devpulse.apps.handlers.watchdog.timer")


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
        console.print(presenter.format_status_line(watch, timer_mod.format_human))

    if pruned:
        console.print(f"[dim]Pruned {pruned} stale watch(es).[/dim]")
    else:
        console.print("[dim]No stale watches to prune.[/dim]")

    presenter.print_delivery_lag()
    return True


def _handle_list() -> bool:
    """Alias for ``status`` — terser framing chosen: same output.

    Phase 4 Notes: `list` just routes to `_handle_status`. The UX bar for
    differentiating wasn't worth the divergence.
    """
    return _handle_status()


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
            presenter.print_kill_result(result)
        return True

    handle = sub_args[0]
    result = registry_mod.kill_watch(handle)
    presenter.print_kill_result(result)
    if not result.get("killed", False):
        logger.info("[watchdog] cancel failed handle=%s", handle)
    return True
