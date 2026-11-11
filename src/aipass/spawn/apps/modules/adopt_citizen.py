# =================== AIPass ====================
# Name: adopt_citizen.py
# Description: adopt-citizen CLI — preview or apply moving a citizen into another project
# Version: 1.0.0
# Created: 2026-11-08
# Modified: 2026-11-08
# =============================================

"""adopt-citizen orchestrator: parse, plan, apply on --apply, print the stable preview."""

import json

from aipass.prax import logger

from aipass.cli.apps.modules import console, error, escape

from aipass.spawn.apps.handlers.adopt_citizen_ops import apply_adoption, plan_adoption
from aipass.spawn.apps.handlers.json import json_handler

USAGE = "drone @spawn adopt-citizen @<name> <target_root> [--apply] [--json]"


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]adopt_citizen Module[/bold cyan]")
    console.print("Move an existing citizen whole into another project root, preview first")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- adopt_citizen_ops.py (plan_adoption, apply_adoption)[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command != "adopt-citizen":
        return False
    if not args:
        print_introspection()
        return True
    if "--help" in args or "-h" in args:
        _print_help()
        return True
    return handle_adopt_citizen(args) == 0


def _print_help():
    """Display adopt-citizen help."""
    console.print(f"[bold cyan]Usage:[/bold cyan] {escape(USAGE)}")
    console.print()
    console.print("  Preview by default: every path as create, move, append, edit, skip or clash. Writes nothing.")
    console.print("  [green]--apply[/green]  Execute the writes listed, then prove the citizen's identity")
    console.print("  [green]--json[/green]   Machine-readable result")
    console.print("  Exit 0 ready or done, 1 refused or blocked (nothing written), 2 usage.")
    console.print()


def handle_adopt_citizen(args: list[str]) -> int:
    """Parse args, plan, apply on --apply, print. Returns the exit code."""
    if "--help" in args or "-h" in args:
        _print_help()
        return 0
    positional = [a for a in args if a not in {"--apply", "--json"}]
    if len(positional) != 2 or any(a.startswith("--") for a in positional):
        error("adopt-citizen takes @<name> and <target_root>", suggestion=USAGE)
        return 2

    apply = "--apply" in args
    try:
        plan = plan_adoption(positional[0], positional[1])
        if apply and not plan["blocked"]:
            plan = apply_adoption(plan)
    except Exception as exc:
        logger.error("[adopt-citizen] Unexpected error for %s: %s", positional[0], exc)
        raise
    plan.pop("_apply", None)
    if plan["applied"]:
        json_handler.log_operation("adopt_citizen", data={"citizen": plan["citizen"], "dest": plan["dest_dir"]})

    if "--json" in args:
        console.print(json.dumps(plan, indent=2), markup=False, highlight=False, soft_wrap=True)
    else:
        _print_text(plan, apply)
    if plan["blocked"]:
        if "--json" not in args:
            error("blocked: " + "; ".join(plan["blocked"]))
        return 1
    return 0


def _print_text(plan, apply):
    """The stable text shape @aipass embeds verbatim."""
    mode = "applied" if plan["applied"] else "preview, nothing written"
    lines = [f"adopt-citizen @{plan['citizen']} -> {plan['target_root']} ({mode})"]
    if plan["source_dir"]:
        lines.append(f"  from      {plan['source_dir']} ({plan['source_registry'].rsplit('/', 1)[-1]})")
    lines.append(f"  to        {plan['dest_dir']}")
    if plan["registry"]["path"]:
        lines.append(f"  registry  {plan['registry']['path']} ({plan['registry']['action']})")
        old, new = plan["class"]["from"], plan["class"]["to"]
        lines.append(f"  class     {old} -> {new} (target has no owner)" if old != new else f"  class     {old}")
    lines.append("paths")
    lines.extend(f"  {p['action']:<7} {p['path']}  {p['reason']}" for p in plan["paths"])
    lines.append("follow-ups (spawn does not write these)")
    lines.extend(f"  {f['owner']:<9} {f['what']}" for f in plan["follow_ups"])
    if plan["applied"]:
        proof = plan["proof"]
        lines.append(f"proof     citizen_id == row registry_id: {proof['citizen_id_matches_row']}")
        lines.append(f"          registry resolves the name to the destination: {proof['registry_resolves_dest']}")
        lines.append(f"          drone: {proof['drone_resolution']}")
    blocked = "; ".join(plan["blocked"])
    lines.append(f"result    {'blocked: ' + blocked if blocked else ('done' if apply else 'ready')}")
    console.print("\n".join(lines), markup=False, highlight=False, soft_wrap=True)
