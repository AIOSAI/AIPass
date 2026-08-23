# =================== AIPass ====================
# Name: presenter.py
# Description: Watchdog presentation layer — handler result dicts rendered as CLI output
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""
Watchdog presentation — turning handler result dicts into console output.

Every function here takes a plain dict from one of the watchdog handlers and
writes (or returns) the operator-facing rendering of it. Nothing here decides
anything: no registry reads that change state, no process control, no parsing
of user arguments. That split is the point — the module routes and the handlers
act, and this file is only how the result is said out loud.

Public surface:
  print_schedule_result(result)
  print_timer_result(result)
  print_timer_list(snapshot)
  format_status_line(watch, format_human) -> str
  print_delivery_lag()
  print_kill_result(result)

WHY THIS FILE EXISTS: ``apps/modules/watchdog.py`` reached 692 lines across
three rewrites (r2, r3, r4) and broke the 600-line module ceiling, which is a
hard failure in the seedgo CI gate. The presentation functions were the
cohesive third of it — they share no state with the routing code and were
already only called at the end of a subcommand — so they moved as a group
rather than the module being sliced at an arbitrary line number.

The one-line renderers keyed by watch type live here too, as a table rather
than an if/elif chain: the chain nested one level deeper per watch type, so
adding a seventh kind of watch was a standards failure on arrival.

Design record: DPLAN-0130 (original), DPLAN-0308 (r2), DPLAN-0317 (r4).
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
    """A pre-r4 detection daemon, if one is somehow still standing.

    r4 deleted the daemon, so this row should never appear again — which is
    exactly why the renderer stays. A row nothing can render is a row nobody
    sees, and an orphaned daemon from an older binary is precisely the thing
    the operator needs shown to them.
    """
    role = meta.get("role") or "legacy"
    return f"role={role} scope={meta.get('scope', '?')} (tick={meta.get('tick_seconds', '?')}s)"


def _tail_baseline_wire(meta: dict) -> str:
    """The wire. ``session`` is the whole of the health question.

    This used to print ``daemon_pid`` — a field r4's wire no longer writes, so
    it rendered as a permanent ``daemon_pid=?`` that read like a fault. The
    first replacement was ``tasks_dir``, which was the same mistake wearing a
    different name: a Monitor child's stdout is a socket and has no tasks dir,
    so the healthy case printed ``tasks=?`` forever. A field that reads ``?``
    on the happy path teaches the operator to ignore the row.

    ``via`` is the honest one. Only ``monitor`` means covered — ``background``
    is the wrapper that notifies on exit only (a continuous wire never exits,
    so zero wakes), and ``foreground`` means nobody is listening at all.
    """
    return f"session={meta.get('session') or 'NONE (fg)'} via={meta.get('wrapper') or 'unrecorded'}"


def _tail_timer(meta: dict) -> str:
    return f"duration={meta.get('duration', '?')}"


def _tail_schedule(meta: dict) -> str:
    cmd = meta.get("command")
    cmd_repr = f' cmd="{cmd}"' if cmd else ""
    return f"scheduled={meta.get('scheduled_for', '?')}{cmd_repr}"


# Type -> tail renderer. A table rather than an if/elif chain: the chain nested
# one level deeper per watch type, so adding a seventh kind of watch was a
# standards failure on arrival.
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

    # An unknown type still renders — raw metadata beats hiding the row, because
    # a watch nobody can see is a watch nobody retires.
    render = _TAIL_BY_TYPE.get(wtype)
    tail = render(meta) if render is not None else str(meta)

    # Escape the [ so Rich console doesn't interpret it as a style tag.
    return f"  \\[{handle}]  {wtype:<8}  {format_human(elapsed):<10}  pid={pid}  {tail}"


def print_delivery_lag() -> None:
    """One line of dispatch truth: what this seat has out, and what is late.

    r4 replaced the old observable (events written vs bytes delivered) because
    both files it read are gone with the daemon. This reads the REGISTER
    instead, and it is the whole of the crash coverage: an entry past its
    expected_by is late whether or not anything is running, so simply looking
    is the detector. Nothing polls for this — it becomes true on its own and is
    noticed by whoever next asks.

    A missing register is reported as exactly that, never as "none outstanding".
    """
    dispatches_mod = importlib.import_module("aipass.devpulse.apps.handlers.watchdog.dispatches")
    try:
        open_now = dispatches_mod.outstanding()
        late = dispatches_mod.overdue()
    except dispatches_mod.RegisterUnavailable as exc:
        # Printed AND logged: the print tells whoever ran `status` right now,
        # the log is what remains if the crash coverage was blind for a week
        # and nobody was watching the terminal when it went blind.
        logger.warning("[watchdog] dispatch register unavailable: %s", exc)
        console.print(f"[dim]Dispatch register unavailable: {exc}[/dim]")
        return

    # Recorded because looking IS the detector. Crash coverage here is not a
    # process that watches — an entry past expected_by becomes late on its own
    # and is only noticed when someone asks. This is the record of who asked,
    # when, and what the answer was; without it there is no way to tell a week
    # of "nothing was overdue" from a week of nobody looking.
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
