# =================== AIPass ====================
# Name: front_door.py
# Description: The front-door verb: counts every cross-branch import reaching under another branch's apps/
# Version: 1.0.0
# Created: 2026-11-16
# Modified: 2026-11-16
# =============================================

"""The `front-door` verb, counting mode. A measurement, not yet a rule: no finding fails
anything, nothing scores, no bypass row is read.

A bare call describes the verb; `scan` runs it over the tracked tree. `--sites` also prints
every cross-branch import site with its call. A tree git cannot list or an unreadable file
exits 2, because "could not measure" is not a count; an unparseable file is named and not
counted; an unknown argument exits 7.
"""

from pathlib import Path
from typing import Dict, List, Tuple

from aipass.cli import console
from aipass.cli.apps.modules import error
from aipass.sentry.apps.handlers.aipass_standards import front_door_count
from aipass.sentry.apps.handlers.audit_tests import refusal
from aipass.sentry.apps.handlers.bypass.ignore_handler import find_repo_root
from aipass.sentry.apps.handlers.cli.help_flags import wants_help
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.modules import CommandRefused

COMMANDS: tuple = ("front-door", "front_door")
SCAN_TOKEN = "scan"
SITES_FLAG = "--sites"
_COLUMNS = (
    ("out prod", "out:prod"),
    ("out tests", "out:tests"),
    ("in prod", "in:prod"),
    ("in tests", "in:tests"),
    ("modules", "in:modules"),
    ("handlers", "in:handlers"),
    ("other", "in:other"),
    ("stmt", "in:statement"),
    ("type", "in:type_only"),
    ("string", "in:string"),
    ("door prod", "in:door:prod"),
    ("door tests", "in:door:tests"),
    ("elsew prod", "in:elsewhere:prod"),
)


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `front-door` and run it. An unusable argument or an unmeasured tree raises CommandRefused."""
    if command not in COMMANDS:
        return False
    if not args:
        print_introspection()
        return True
    if wants_help(None, args):
        print_help()
        return True
    if args[0] != SCAN_TOKEN:
        _refuse(args[0], f"front-door does not know '{args[0]}' - the word that runs it is '{SCAN_TOKEN}'")
    for token in args[1:]:
        if token != SITES_FLAG:
            _refuse(token, f"front-door scan does not know '{token}' - it accepts {SITES_FLAG}")
    root = find_repo_root(Path(__file__).resolve().parent)
    if root is None:
        _refuse(SCAN_TOKEN, "no git repository holds this branch")
    _scan(root, sites=SITES_FLAG in args)  # type: ignore[arg-type]
    return True


def _refuse(token: str, message: str) -> None:
    error(message, suggestion="drone @sentry front-door --help")
    raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, token)


def _plain(text: str) -> None:
    console.print(text, markup=False, highlight=False, soft_wrap=True)


def _scan(root: Path, sites: bool) -> None:
    """Scan, print the per-branch table, the target lists, the doors and the fleet totals."""
    result = front_door_count.scan_tracked(root)
    counted = front_door_count.tally(result["sites"])
    if sites:
        _print_sites(result["sites"])
    _print_table(counted["rows"])
    _print_targets(counted["modules"])
    _print_doors(result["doors"], counted["rows"])
    _print_fleet(counted["fleet"], result)
    json_handler.log_operation("front_door_reported", {"sites": len(result["sites"]), "errors": len(result["errors"])})
    # A spawn template carries placeholders until rendered: named, never counted, never a failed scan.
    for rel in result["unparseable"]:
        _plain(f"not counted, not Python as tracked: {rel}")
    for problem in result["errors"]:
        error(f"cannot measure: {problem}")
    if result["errors"]:
        raise CommandRefused(refusal.EXIT_UNPROVEN, "front-door")


def _print_sites(found: List[front_door_count.Site]) -> None:
    """One line per cross-branch site: FOUND under apps, clean through the door or elsewhere."""
    for site in found:
        r = site.reading
        call = "FOUND" if r.kind in front_door_count.APPS_KINDS else "clean"
        scope = "tests" if site.test else "prod"
        _plain(f"{site.rel}:{r.line}  {call:5} {scope:5} {r.kind:9} {r.via:9} {r.target} {' '.join(r.names)}")
    console.print()


def _print_table(rows: Dict) -> None:
    """Per branch: findings as importer (out) and as target (in), then the clean cross-branch counts."""
    console.print("[bold cyan]Front door, counting mode[/bold cyan] - findings reach under another branch's apps/")
    header = f"{'branch':16}" + "".join(f"{label:>11}" for label, _ in _COLUMNS)
    _plain(header)
    for branch in sorted(rows):
        counts = rows[branch]
        _plain(f"{branch:16}" + "".join(f"{counts[key]:>11}" for _, key in _COLUMNS))
    console.print("[dim]in = lines reaching into the branch; door/elsewhere in = clean cross-branch lines[/dim]")
    console.print()


def _print_targets(modules: Dict) -> None:
    """What each branch's public list would have to hold: every module reached under its apps/."""
    console.print("[bold cyan]Reached under apps/, per target[/bold cyan] (what a door would hand out)")
    for branch in sorted(modules):
        listed = ", ".join(f"{name} {n}" for name, n in modules[branch].most_common())
        _plain(f"{branch}: {listed}")
    console.print()


def _print_doors(doors: Dict[str, Tuple[str, ...]], rows: Dict) -> None:
    """The names each door hands out today, the short-form lines it already serves, and the empty doors."""
    console.print("[bold cyan]Doors today[/bold cyan] (names handed out; short-form cross-branch lines)")
    empty = [branch for branch, names in sorted(doors.items()) if not names]
    for branch, names in sorted(doors.items()):
        if names:
            counts = rows.get(branch, {})
            used = counts.get("in:door:prod", 0) + counts.get("in:door:tests", 0)
            _plain(f"{branch}: {', '.join(names)}  ({used} lines)")
    _plain(f"empty doors: {', '.join(empty) or '-'}")
    console.print()


def _print_fleet(fleet: Dict, result: Dict) -> None:
    """Fleet totals by scope, kind and via; outside-branch files are their own row, counted here too."""
    console.print("[bold cyan]Fleet totals[/bold cyan]")
    for scope in ("prod", "tests"):
        parts = [f"findings {fleet.get(f'finding:{scope}', 0)}"]
        parts += [f"{kind} {fleet.get(f'{kind}:{scope}', 0)}" for kind in front_door_count.APPS_KINDS]
        parts += [f"{via} {fleet.get(f'{via}:{scope}', 0)}" for via in front_door_count.VIAS]
        parts += [f"clean door {fleet.get(f'door:{scope}', 0)}", f"elsewhere {fleet.get(f'elsewhere:{scope}', 0)}"]
        _plain(f"{scope:5}: " + " | ".join(parts))
    _plain(f"{result['files_read']} tracked .py files read")


def print_help() -> None:
    """Usage, what counts, and exit codes."""
    console.print()
    console.print("[bold cyan]sentry front-door[/bold cyan] - cross-branch imports reaching under apps/, counted")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drone @sentry front-door                 what the verb is")
    console.print("  drone @sentry front-door scan            the per-branch table, targets, doors, fleet totals")
    console.print("  drone @sentry front-door scan --sites    every cross-branch site first, FOUND or clean")
    console.print()
    console.print("[yellow]Counts[/yellow]")
    console.print("  import / from-import statements anywhere in the parse tree; TYPE_CHECKING ones as type")
    console.print("  string targets of import_module, resolve_name, patch, <x>.setattr as string")
    console.print("  never a docstring, comment or message; a file's own branch is never counted")
    console.print()
    console.print("[yellow]Exit codes[/yellow]")
    console.print("  0 measured (findings never fail)   2 could not measure   7 an unknown argument")
    console.print()


def print_introspection() -> None:
    """What this verb is, shown when it is called with no arguments."""
    console.print()
    console.print("[bold cyan]front-door[/bold cyan] - counting mode for the front-door import rule")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [dim]- aipass_standards/front_door_count.py (scan_tracked, tally)[/dim]")
    console.print("  [dim]- aipass_standards/string_imports.py (iter_string_imports)[/dim]")
    console.print()
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @sentry front-door scan[/green]      [dim]# Count the tracked tree[/dim]")
    console.print("  [green]drone @sentry front-door --help[/green]    [dim]# Full usage guide[/dim]")
    console.print()
