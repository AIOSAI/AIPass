# =================== AIPass ====================
# Name: roots.py
# Description: Declared-roots module — the operator lane for AIPASS_ROOTS.json
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""
Declared Roots Module — the operator lane for the fleet anchor

``drone @memory roots init | add | remove | list | heal``

WHY NOT ON ``modules/fleet.py``. That module is the cross-branch library
gateway, and it carries a test asserting its command surface DESCRIBES the
contract and computes nothing — a gateway whose CLI starts doing work is a
second public surface. These verbs are the opposite job: an operator writing a
machine-managed file. Different job, different module.

WHY VERBS AT ALL. Patrick's ruling, on seeing a hand-made AIPASS_ROOTS.json:
"jsons are normally created by code, so if they corrupt or get deleted they are
always rebuilt from default settings from a template directory." The verbs are
how a declaration gets made without anyone opening an editor, and they refuse at
WRITE time exactly what the reader refuses at READ time — against the reader's
own predicate, not a copy of it — so the file cannot carry a row that will be
silently dropped.

``heal`` is deliberate and never automatic; see ``handlers/monitor/roots_file.py``
for the ruling and its reasoning.
"""

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.monitor import roots_file


def _report(ok: bool, message: str) -> None:
    from aipass.cli.apps.modules import console, warning

    if ok:
        console.print(f"[green]roots:[/green] {message}")
    else:
        warning(f"roots: {message}")


def show_roots() -> None:
    """Print every declared row and what it actually resolves to."""
    from aipass.cli.apps.modules import console

    rows = roots_file.list_roots()
    if not rows:
        console.print(f"[dim]no roots declared ({roots_file.ROOTS_FILE} absent or empty)[/dim]")
        return
    console.print()
    console.print(f"[bold cyan]{roots_file.ROOTS_FILE}[/bold cyan]")
    for row in rows:
        # UNREACHABLE is the reason this verb exists: in the file a dead row
        # looks exactly like a live one, and the only other place it shows up
        # is a log line nobody reads.
        mark = "[green]reachable[/green]" if row["reachable"] else "[yellow]UNREACHABLE[/yellow]"
        console.print(f"  {row['path']:<24} {row['label']:<18} {row['status']:<10} {mark}")
        if not row["reachable"]:
            console.print(f"    [dim]resolves to {row['resolves']} — the reader will refuse this row[/dim]")
    console.print()


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]roots Module[/bold cyan]")
    console.print("The declared-roots anchor — which repo roots on this machine join the fleet")
    console.print()
    console.print("[yellow]Commands:[/yellow]")
    console.print("  roots init              render AIPASS_ROOTS.json from the template (refuses if present)")
    console.print("  roots add PATH [LABEL]  declare a root, validated at write time")
    console.print("  roots remove PATH       retire a declaration")
    console.print("  roots list              every row, and whether the reader can use it")
    console.print("  roots heal              rebuild a corrupt file as an EMPTY scaffold, loudly")
    console.print()
    console.print("[dim]heal never restores declarations — a rebuild that repopulates has re-declared[/dim]")
    console.print(f"[dim]template: {roots_file.template_path()}[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery."""
    if command != "roots":
        return False

    json_handler.log_operation("roots_command", {"args": args})

    if not args:
        print_introspection()
        return True

    # Help anywhere, not only in first position: `roots add --help` is what a
    # person actually types when they cannot remember the argument order, and a
    # gate that reads args[0] alone would treat it as a path and refuse.
    if any(token in ("--help", "-h", "help") for token in args):
        print_introspection()
        return True

    verb, rest = args[0], args[1:]

    if verb == "list":
        show_roots()
        return True

    if verb == "init":
        _report(*roots_file.init_roots())
        return True

    if verb == "add":
        if not rest:
            _report(False, "add needs a path: roots add ../wren [label]")
            return True
        _report(*roots_file.add_root(raw_path=rest[0], label=rest[1] if len(rest) > 1 else ""))
        return True

    if verb == "remove":
        if not rest:
            _report(False, "remove needs a path: roots remove ../wren")
            return True
        _report(*roots_file.remove_root(raw_path=rest[0]))
        return True

    if verb == "heal":
        ok, message, salvaged = roots_file.heal()
        _report(ok, message)
        if salvaged:
            from aipass.cli.apps.modules import console, warning

            # Printed, never written back. A salvaged path is a guess about
            # intent, and a guess that installs itself is a declaration. The
            # heading goes to stderr because it is a warning; the commands go to
            # stdout so they can be piped straight into a shell.
            warning("declarations NOT restored — re-add them yourself:")
            for path in salvaged:
                console.print(f"  drone @memory roots add {path}")
        return True

    logger.info(f"[roots] Unknown subcommand {verb!r}")
    _report(False, f"unknown subcommand '{verb}'")
    print_introspection()
    return True
