# =================== AIPass ====================
# Name: roots.py
# Description: Declared-roots module — the operator lane for AIPASS_ROOTS.json
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""
Declared Roots Module — the operator lane for the fleet anchor

Kept off modules/fleet.py: that gateway's CLI must describe, never compute.
Verbs refuse at write time what the reader refuses at read time, via the reader's own predicate.
"""

from aipass.prax import logger

from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.monitor import roots_file


def _report(ok: bool, message: str) -> None:
    from aipass.cli.apps.modules import console, error

    if ok:
        console.print(f"[green]roots:[/green] {message}")
    else:
        error(f"roots: {message}")


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
        # A dead row looks like a live one in the file; this mark is the only visible signal.
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

        # Help anywhere: `roots add --help` must not be read as a path.
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

            # Printed, never written back: a salvaged path that installs itself is a declaration.
            # Heading to stderr, commands to stdout so they pipe into a shell.
            warning("declarations NOT restored — re-add them yourself:")
            for path in salvaged:
                console.print(f"  drone @memory roots add {path}")
        return True

    logger.info(f"[roots] Unknown subcommand {verb!r}")
    _report(False, f"unknown subcommand '{verb}'")
    print_introspection()
    return True
