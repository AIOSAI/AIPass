# =================== AIPass ====================
# Name: presenter.py
# Description: Watchdog presentation layer — handler result dicts rendered as CLI output
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-10-17
# =============================================

"""Watchdog presentation — turning handler result dicts into console output.

Nothing here decides anything: the module routes, the handlers act, this only says the result.
"""

import importlib

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.devpulse.apps.handlers.json import json_handler

MODULE_NAME = "presenter"


def print_schedule_result(result: dict) -> None:
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


def print_timer_result(result: dict) -> None:
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


def print_timer_list(snapshot: dict) -> None:
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


def _tail_agent(meta: dict) -> str:
    return f"{meta.get('agent_id', '?')} (timeout={meta.get('timeout_seconds', '?')}s)"


def _tail_baseline(meta: dict) -> str:
    """A retired detection daemon still standing: an orphan the operator must see, so it stays."""
    role = meta.get("role") or "legacy"
    return f"role={role} scope={meta.get('scope', '?')} (tick={meta.get('tick_seconds', '?')}s)"


def _tail_baseline_wire(meta: dict) -> str:
    """The wire. ``session`` is the whole of the health question.

    Never a field that reads ``?`` on the happy path: it teaches the operator to
    ignore the row. Only ``via=monitor`` means covered; ``background`` wakes on exit only.
    """
    return f"session={meta.get('session') or 'NONE (fg)'} via={meta.get('wrapper') or 'unrecorded'}"


def _tail_timer(meta: dict) -> str:
    return f"duration={meta.get('duration', '?')}"


def _tail_schedule(meta: dict) -> str:
    cmd = meta.get("command")
    cmd_repr = f' cmd="{cmd}"' if cmd else ""
    return f"scheduled={meta.get('scheduled_for', '?')}{cmd_repr}"


# A table, not an if/elif chain: the chain nests one level deeper per watch type.
_TAIL_BY_TYPE = {
    "agent": _tail_agent,
    "baseline": _tail_baseline,
    "baseline_wire": _tail_baseline_wire,
    "timer": _tail_timer,
    "schedule": _tail_schedule,
}


def format_status_line(watch: dict, format_human) -> str:
    """One-line renderer for a single watch entry in the status output."""
    handle = watch.get("handle", "?")
    wtype = watch.get("type", "?")
    elapsed = int(watch.get("elapsed_seconds", 0))
    pid = watch.get("pid", "?")
    meta = watch.get("metadata") or {}

    # An unknown type still renders: a watch nobody can see is a watch nobody retires.
    render = _TAIL_BY_TYPE.get(wtype)
    tail = render(meta) if render is not None else str(meta)

    # Escape the [ so Rich console doesn't interpret it as a style tag.
    return f"  \\[{handle}]  {wtype:<8}  {format_human(elapsed):<10}  pid={pid}  {tail}"


def print_delivery_lag() -> None:
    """One line of dispatch truth: what this seat has out, and what is late.

    Looking is the whole crash coverage: nothing polls, an entry past expected_by
    is late on its own. A missing register is said as such, never "none outstanding".
    """
    dispatches_mod = importlib.import_module("aipass.devpulse.apps.handlers.watchdog.dispatches")
    try:
        open_now = dispatches_mod.outstanding()
        late = dispatches_mod.overdue()
    except dispatches_mod.RegisterUnavailable as exc:
        # Logged too: the log is what remains if coverage went blind with nobody at the terminal.
        logger.warning("[watchdog] dispatch register unavailable: %s", exc)
        console.print(f"[dim]Dispatch register unavailable: {exc}[/dim]")
        return

    # Tells a week of "nothing overdue" from a week of nobody looking.
    json_handler.log_operation("delivery_lag_read", {"outstanding": len(open_now), "overdue": len(late)})

    if late:
        names = ", ".join(str(e.get("target", "?")) for e in late)
        console.print(
            f"[yellow]Dispatches overdue: {len(late)}[/yellow] ({names}) — "
            f"{len(open_now)} outstanding. An overdue entry never reported back."
        )
    elif open_now:
        names = ", ".join(str(e.get("target", "?")) for e in open_now)
        console.print(f"[dim]Dispatches outstanding: {len(open_now)} ({names}), none overdue.[/dim]")
    else:
        console.print("[dim]Dispatches: none outstanding.[/dim]")


def print_kill_result(result: dict) -> None:
    """Render a single ``registry.kill_watch`` result on one line."""
    handle = result.get("handle", "?")
    killed = result.get("killed", False)
    was_alive = result.get("was_alive", False)
    reason = result.get("reason", "")
    status = "KILLED" if killed else "FAILED"
    console.print(f"  \\[{handle}] {status} was_alive={was_alive} reason={reason}")
