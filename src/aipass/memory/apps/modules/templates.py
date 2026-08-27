# =================== AIPass ====================
# Name: templates.py
# Description: Gold-source template lane — spawn scaffold propagation, receipt status, and the bump site
# Version: 1.0.0
# Created: 2026-02-14
# Modified: 2026-08-27
# =============================================

"""Template Lane

@memory owns the gold-source memory templates in ``memory/templates/``. This
module is the CLI over them: propagate them into @spawn's scaffold sets, report
who carries which version, and be the site where a version bump heals the fleet.

WHAT WAS RETIRED HERE, AND WHY IT MATTERS (2026-08-27, DPLAN-0318 marker 7)
--------------------------------------------------------------------------
``push-templates`` and ``diff-templates`` scanned each branch's ROOT directory
for files ending ``.local.json`` / ``.observations.json`` — a naming convention
that predates ``.trinity/``. The live layout is ``<branch>/.trinity/local.json``,
which does not end in ``.local.json`` and is not in the directory being scanned,
so **zero real matches were possible**. Measured before retirement,
``diff-templates`` announced "16 branches have template differences" and not one
was a memory file; the only thing it ever matched was an unrelated
``CLOSED_PLANS.local.json``.

A lane aimed at a dead layout is worse than a missing one: it answers, it looks
like it worked, and it is a silent no-op waiting to be trusted. Both verbs now
REFUSE and name the live lane; the handlers are in
``tests/parked/dead_template_lane_20260827/`` with the measurement written down.

The half that always worked — propagating the templates into @spawn's scaffold
sets, which really do use the ``.trinity/`` layout — survives under its own
honest name, ``spawn-templates``. It used to run as a side effect of the dead
verb, which is why it went unnoticed.

``template-status`` survives too, repointed. It used to read a fleet-side push
log whose ``last_push`` only the retired lane could ever move; it now reads the
per-branch ``.trinity/.template_version.json`` receipts, written by lanes that
are alive.
"""

import json
import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.templates.spawn_pusher import push_to_spawn_templates
from aipass.memory.apps.handlers.templates import template_bump

_SUBCOMMANDS = {
    "spawn-templates": "Propagate the gold templates into @spawn's scaffold sets",
    "template-status": "Who carries which template version, from the live receipts",
    "bump": "Heal the fleet after a template version bump (dry run unless --confirm)",
}

# Verbs retired 2026-08-27 -> what to run instead. They still ROUTE: a removed
# verb tells a caller nothing about its replacement, and these two spent months
# reporting confident results about a layout that does not exist.
RETIRED_VERBS = {
    "push-templates": (
        "it pushed into a pre-.trinity layout and matched nothing",
        "drone @memory push            (branch memory files, gated)\n"
        "  drone @memory templates spawn-templates   (spawn's scaffold sets)",
    ),
    "diff-templates": (
        "it diffed a pre-.trinity layout and reported phantom drift",
        "drone @memory push --dry-run",
    ),
}


# =============================================================================
# COMMAND ROUTING
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """Route the templates verbs.

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if command handled, False otherwise.
    """
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "templates":
        if not args:
            print_introspection()
            return True
        # A help flag ANYWHERE wins — asking about a verb must never run it.
        if wants_help(args, allow_bare_word=True):
            print_help()
            return True
        return _route(args[0], args[1:])

    # Backward-compatible top-level commands (entry point still routes these)
    if command in RETIRED_VERBS or command in _SUBCOMMANDS:
        return _route(command, args)

    return False


def _route(sub: str, remaining: List[str]) -> bool:
    """Dispatch one templates subcommand."""
    if sub in RETIRED_VERBS:
        _announce_retired(sub)
        return True

    if sub == "spawn-templates":
        _run_spawn_push("--dry-run" in remaining)
        return True

    if sub == "template-status":
        _show_status()
        return True

    if sub == "bump":
        _run_bump("--confirm" in remaining)
        return True

    error(
        f"Unknown subcommand: '{sub}'",
        suggestion="Available: " + ", ".join(_SUBCOMMANDS.keys()),
    )
    return True


def _announce_retired(verb: str) -> None:
    """Refuse a retired verb and name the lane that replaced it."""
    reason, replacement = RETIRED_VERBS[verb]
    console.print()
    warning(f"'{verb}' was retired on 2026-08-27 — {reason}.")
    console.print()
    console.print("[bold]Run instead:[/bold]")
    console.print(f"  {replacement}")
    console.print()
    console.print("[dim]Handlers archived at tests/parked/dead_template_lane_20260827/ with the measurement.[/dim]")
    console.print()
    json_handler.log_operation("retired_verb_called", {"verb": verb}, module_name="templates")


# =============================================================================
# THE LIVE LANES
# =============================================================================


def _run_spawn_push(dry_run: bool) -> None:
    """Propagate the gold templates into @spawn's scaffold sets."""
    console.print()
    mode = "DRY RUN" if dry_run else "PUSH"
    console.print(
        Panel.fit(f"[bold cyan]Memory - Spawn Templates · {mode}[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()

    try:
        result = push_to_spawn_templates(dry_run=dry_run)
    except Exception as exc:
        logger.error(f"[templates] Spawn template push crashed: {exc}", exc_info=True)
        error(f"Spawn template push crashed: {exc}")
        return

    if not result.get("success"):
        for message in result.get("errors", []):
            error(f"Spawn push: {message}")
        return

    sets_found = result.get("template_sets_found", [])
    sets_updated = result.get("template_sets_updated", 0)
    files_modified = result.get("files_modified", 0)

    if files_modified == 0 and not result.get("changes"):
        console.print("[green]>[/green] Spawn templates already up to date")
    else:
        verb = "would update" if dry_run else "updated"
        console.print(f"[green]>[/green] {sets_updated}/{len(sets_found)} sets {verb}, {files_modified} files")
        for change in result.get("changes", []):
            console.print(
                f"  [green]+[/green] {change.get('template_set')}/{change.get('file')} "
                f"[dim]({change.get('action')})[/dim]"
            )

    console.print()
    logger.info(
        f"[templates] Spawn push {'(dry run) ' if dry_run else ''}complete: "
        f"{sets_updated}/{len(sets_found)} sets, {files_modified} files"
    )
    json_handler.log_operation(
        "spawn_templates_push",
        {"dry_run": dry_run, "sets": sets_updated, "files": files_modified},
        module_name="templates",
    )


def _show_status() -> None:
    """Report which branches carry the current template version."""
    console.print()
    console.print(
        Panel.fit("[bold cyan]Memory - Template Version Status[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()

    try:
        status = template_bump.receipt_status()
    except Exception as exc:
        logger.error(f"[templates] Template status crashed: {exc}", exc_info=True)
        error(f"Template status crashed: {exc}")
        return

    gold = status["gold"]
    console.print(
        f"[bold]Gold source:[/bold] local {gold.get('local', '?')} · observations {gold.get('observations', '?')}"
    )

    stale = [row for row in status["branches"] if not row["current"]]
    current_count = len(status["branches"]) - len(stale)
    console.print(f"[bold]Branches:[/bold] {current_count}/{len(status['branches'])} carry the current version")
    console.print()
    for row in stale:
        carries = row["carries"]
        detail = "NO RECEIPT" if carries is None else ", ".join(f"{k} {v}" for k, v in sorted(carries.items()))
        console.print(f"  [yellow]![/yellow] {row['branch']}: {detail}")
    if not stale:
        console.print("  [green]>[/green] every branch is current")

    console.print()
    pending = template_bump.bump_pending()
    marker = "[yellow]BUMP PENDING[/yellow]" if pending["pending"] else "[green]no bump pending[/green]"
    console.print(f"[bold]Fleet ledger:[/bold] {marker} — {pending['reason']}")
    if pending["pending"]:
        console.print("  Run: [cyan]drone @memory templates bump[/cyan] (dry run; add --confirm to execute)")
    console.print()


def _announce_bump(outcome: dict) -> None:
    """Announce a bump on @trigger's bus. Best effort — the bus never gates a heal.

    Lives in the module layer, not beside the bump's domain logic: reaching the
    bus means importing @trigger's module layer, and a handler doing that is
    orchestration in a handler's clothing. The handler owns the event's NAME
    (`template_bump.BUMP_EVENT`); this owns the sending.

    Fired AFTER the outcome is known, so the event carries what happened rather
    than what was about to be attempted — a listener cannot influence the push's
    gates anyway, and should not be told a heal ran when it was refused.

    The two failures are logged DIFFERENTLY on purpose. An ImportError means
    @trigger is not installed here — an environment fact, nothing to repair.
    Anything else raised on this path is OUR bug (this exact call shipped for a
    few hours with `json` unimported, and a broad "bus unavailable" line made a
    NameError read as a missing dependency: the announcement never fired and
    nothing in the log said so). One catch, two sentences, two repairs.
    """
    try:
        from aipass.trigger.apps.modules.core import trigger
    except ImportError as exc:
        logger.info(f"[templates] Event bus unavailable, bump not announced: {exc}")
        return

    try:
        trigger.fire(
            template_bump.BUMP_EVENT,
            pending=outcome.get("pending", False),
            dry_run=outcome.get("dry_run", True),
            stamped=outcome.get("stamped", False),
            versions=json.dumps(outcome.get("now") or {}, sort_keys=True),
        )
    except Exception as exc:
        logger.error(f"[templates] Bump announcement FAILED ({type(exc).__name__}): {exc}", exc_info=True)


def _run_bump(confirm: bool) -> None:
    """The bump site: announce the template bump and heal the fleet."""
    console.print()
    mode = "EXECUTE" if confirm else "DRY RUN"
    console.print(
        Panel.fit(f"[bold cyan]Memory - Template Bump · {mode}[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()

    try:
        outcome = template_bump.on_bump(confirm=confirm)
    except Exception as exc:
        logger.error(f"[templates] Template bump crashed: {exc}", exc_info=True)
        error(f"Template bump crashed: {exc}")
        return

    _announce_bump(outcome)

    if not outcome["pending"]:
        console.print(f"[green]>[/green] No bump to act on — {outcome['reason']}")
        console.print()
        return

    was = outcome["was"] or "no ledger"
    console.print(f"[bold]Bump detected:[/bold] {was} -> {outcome['now']}")
    console.print(f"[dim]{outcome['reason']}[/dim]")
    console.print()

    from aipass.memory.apps.handlers.templates import push_report

    result = outcome["push"]
    if isinstance(result, dict):
        for line in push_report.render(result, "FLEET"):
            console.print(line, markup=False, highlight=False)

    console.print()
    if outcome["stamped"]:
        console.print("[green]>[/green] Fleet ledger stamped at the new version")
    elif confirm:
        error("Ledger NOT stamped — the push did not succeed; the fleet is still on the old version")
    else:
        console.print("[cyan]Dry run — nothing written.[/cyan] Re-run with --confirm to heal the fleet.")
    console.print()


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_introspection() -> None:
    """Level 2 introspection — what this module is wired to."""
    console.print()
    console.print(
        Panel.fit("[bold cyan]Templates Module - The Gold Source[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()
    console.print("[bold]PURPOSE:[/bold]")
    console.print("  @memory owns the gold-source memory templates. Propagate them into")
    console.print("  @spawn's scaffold sets, report who carries which version, and heal the")
    console.print("  fleet through the trinity push when the version is bumped.")
    console.print()
    console.print("[bold]HANDLERS:[/bold]")
    console.print("  handlers/templates/spawn_pusher.py    scaffold-set propagation")
    console.print("  handlers/templates/template_bump.py   bump detection, ledger, receipt status")
    console.print("  handlers/templates/trinity_push.py    the lane a bump heals through")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    for name, description in _SUBCOMMANDS.items():
        console.print(f"  [cyan]{name:<18}[/cyan] {description}")
    console.print()
    console.print("[bold]RETIRED 2026-08-27:[/bold] push-templates, diff-templates — both scanned a")
    console.print("  pre-.trinity layout and could never match a real memory file. They still")
    console.print("  route, and name the live lane instead of failing silently.")
    console.print()


def print_help() -> None:
    """Full usage."""
    console.print()
    console.print(Panel.fit("[bold cyan]drone @memory templates[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory templates spawn-templates --dry-run   Preview scaffold propagation")
    console.print("  drone @memory templates spawn-templates             Write @spawn's scaffold sets")
    console.print("  drone @memory templates template-status             Who carries which version")
    console.print("  drone @memory templates bump                        Bump dry run (the gate report)")
    console.print("  drone @memory templates bump --confirm              Heal the fleet for real")
    console.print()
    console.print("[bold]THE BUMP LANE:[/bold]")
    console.print("  A bump is trigger-driven, never polled: nothing watches the templates.")
    console.print("  `bump` compares the gold templates against the fleet ledger, announces")
    console.print("  trinity_template_bumped on @trigger's bus, then runs the trinity push")
    console.print("  with every gate intact — DRY RUN unless you pass --confirm. The ledger")
    console.print("  is stamped only by a push that actually ran and actually succeeded.")
    console.print()
    console.print("[bold]NOT THIS LANE:[/bold] a branch's own memory files are pushed by")
    console.print("  [cyan]drone @memory push[/cyan]. This module owns the TEMPLATES they are built from.")
    console.print()
    console.print("[bold]RETIRED:[/bold] push-templates, diff-templates (2026-08-27) — see")
    console.print("  tests/parked/dead_template_lane_20260827/README.md for the measurement.")
    console.print()
