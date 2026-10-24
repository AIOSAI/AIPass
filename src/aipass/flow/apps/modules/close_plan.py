# =================== AIPass ====================
# Name: close_plan.py
# Description: PLAN closure module with registry cleanup
# Version: 3.7.0
# Created: 2025-11-25
# Modified: 2026-10-24
# =============================================

"""
Close PLAN Module

Thin orchestrator for plan closure workflow.
All business logic delegated to handlers.
Module handles all display output.

Usage:
    From flow.py: flow close <number>
    From flow.py: flow close --all
    Standalone: drone @flow close <number>
"""

import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from typing import List, Dict, Any

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

from aipass.prax import logger

from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler

from aipass.cli.apps.modules import console, error, warning

# handle_command binds a local `error` that shadows the helper; this alias still prints.
from aipass.cli.apps.modules import error as error_display

from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.save_registry import registry_lock, save_registry

from aipass.flow.apps.handlers.plan.get_open_plans import get_open_plans
from aipass.flow.apps.handlers.plan.validator import normalize_plan_number, validate_plan_exists
from aipass.flow.apps.handlers.plan.confirmation import confirm_plan_deletion
from aipass.flow.apps.handlers.plan.display import (
    format_plan_deletion_header,
    format_plan_error,
    format_plan_deletion_success,
    format_deletion_cancelled,
    format_delete_usage_error,
)

from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central
from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard

from aipass.flow.apps.handlers.mbank.process import is_template_content, archive_plan

from aipass.flow.apps.handlers.plan.close_ops import close_plan_impl, close_all_plans_impl

try:
    from aipass.trigger.apps.modules.core import trigger as _trigger_module

    _trigger_fire = _trigger_module.fire
except ImportError:
    logger.info("[close_plan] Trigger module not available, plan events will be skipped")
    _trigger_fire = None

MODULE_NAME = "close_plan"


def _display_messages(messages: List[Dict[str, Any]]):
    """Render handler result messages to console"""
    for msg in messages:
        msg_type = msg.get("type", "")

        if msg_type == "error":
            error_text = msg.get("text", "general")
            plan_num = msg.get("plan_num", "")
            details = msg.get("details", None)
            console.print(format_plan_error(error_text, plan_num, details=details, prefix=msg.get("prefix", "FPLAN")))

        elif msg_type == "warning":
            warning(msg["text"])

        elif msg_type == "dim":
            console.print(f"[dim]{msg['text']}[/dim]")

        elif msg_type == "step":
            console.print(f"[dim]{msg['text']}[/dim]")

        elif msg_type == "success":
            console.print(f"[green]{msg['text']}[/green]")

        elif msg_type == "error_text":
            error(msg["text"])

        elif msg_type == "header":
            console.print(
                format_plan_deletion_header(msg["plan_key"], msg["plan_info"], prefix=msg.get("prefix", "FPLAN"))
            )

        elif msg_type == "cancelled":
            console.print(format_deletion_cancelled())

        elif msg_type == "close_success":
            console.print(format_plan_deletion_success(msg["plan_key"], prefix=msg.get("prefix", "FPLAN")))

        elif msg_type == "dry_run_row":
            # plan_id is never re-derived here, or the preview could drift from the run.
            # Location is width-capped: a long path would overflow into the subject.
            location = str(msg.get("location", "unknown"))
            if len(location) > 44:
                location = f"...{location[-41:]}"
            console.print(f"[dim]  {msg.get('plan_id', '?'):<14}  {location:<44}  {msg.get('subject', '')}[/dim]")

        elif msg_type == "close_all_scope":
            # Held-back rows (the fence working) are counted apart from refusals (a broken row).
            console.print()
            console.print(f"[bold]Project:[/bold] {msg['project']}")
            console.print(f"  [dim]open plans considered:[/dim] {msg['considered']}")
            console.print(f"  [dim]in scope:[/dim] {msg['in_scope']}")
            if msg.get("excluded_types"):
                console.print(
                    f"  [dim]held back by type ({', '.join(msg['excluded_types'])}):[/dim] {msg['held_by_type']}"
                )
            console.print(f"  [dim]held back, another project:[/dim] {msg['held_out_of_scope']}")
            if msg.get("refused"):
                error(f"  refused (untyped registry row): {msg['refused']}")
            console.print()

        elif msg_type == "held_row":
            console.print(f"[dim]  {msg.get('plan_id', '?'):<14}  held: {msg.get('reason', '')}[/dim]")

        elif msg_type == "plan_list":
            warning(f"Found {msg['count']} open plan(s) to close:")
            for plan in msg.get("plans", []):
                # plan_num is already the typed ID; never prefix it.
                console.print(f"  * {plan['plan_num']}: {plan['subject']}")

        elif msg_type == "confirm_warning":
            error(f"WARNING: This will close all {msg['count']} plans!")

        elif msg_type == "closing_all":
            console.print(f"\n[bold]Closing all {msg['count']} plan(s)...[/bold]")
            console.print("-" * 60)

        elif msg_type == "closing_single":
            # A silent multi-minute bulk close reads as a hang.
            position = msg.get("position")
            counter = f"[{position}/{msg.get('total', '?')}] " if position else ""
            console.print(f"\n[dim]{counter}Closing {msg['plan_num']}...[/dim]")

        elif msg_type == "close_all_summary":
            console.print("\n" + "=" * 60)
            console.print("[bold green]CLOSE ALL COMPLETE[/bold green]")
            console.print(f"  * Successfully closed: {msg['success_count']}")
            console.print(f"  * Failed to close: {msg['failure_count']}")
            console.print(f"  * Held back by the fences: {msg.get('held_count', 0)}")
            console.print(f"  * Total open plans considered: {msg['total']}")
            console.print("=" * 60 + "\n")


def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]close_plan Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- close_ops.py (implementation)[/dim]")
    console.print("    [dim]- get_open_plans.py[/dim]")
    console.print("    [dim]- command_parser.py[/dim]")
    console.print("    [dim]- confirmation.py[/dim]")
    console.print("    [dim]- validator.py[/dim]")
    console.print("    [dim]- display.py[/dim]")
    console.print("    [dim]- file_ops.py[/dim]")
    console.print("    [dim]- update_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]- load_registry.py[/dim]")
    console.print("    [dim]- save_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/dashboard/[/cyan]")
    console.print("    [dim]- update_local.py[/dim]")
    console.print("    [dim]- push_central.py[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow close --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for close_plan module"""
    console.print()
    console.print("[bold cyan]close_plan[/bold cyan] — Close PLAN files")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow close <PLAN-ID> \\[options]")
    console.print()
    console.print("[yellow]OPTIONS:[/yellow]")
    console.print("  --all                  Close all open plans in THIS project")
    console.print("  --confirm              Interactive confirmation prompt")
    console.print("  --dry-run              Preview what would be closed (no action taken)")
    console.print("  --exclude-type <TYPE>  Hold a plan type back from --all (repeatable)")
    console.print()
    console.print("[yellow]SCOPE:[/yellow]")
    console.print("  [dim]--all means every open plan of the project you are standing in.[/dim]")
    console.print("  [dim]A project is a directory holding a sealed project register.[/dim]")
    console.print("  [dim]Plans belonging to another project are never touched.[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow close FPLAN-0042[/dim]                    # Close specific plan")
    console.print("  [dim]drone @flow close DPLAN-0005[/dim]                    # Close a DPLAN")
    console.print("  [dim]drone @flow close --all --dry-run[/dim]               # Preview close-all")
    console.print("  [dim]drone @flow close --all --exclude-type APLAN[/dim]    # Sweep, keep audits open")
    console.print()
    console.print("[dim]Unrecognised arguments refuse the whole run — they are never ignored.[/dim]")
    console.print()


def close_plan(
    plan_num: str | None = None,
    confirm: bool = False,
    all_plans: bool = False,
    spawn_background: bool = True,
    dry_run: bool = False,
    exclude_types: List[str] | None = None,
    refresh_dashboards: bool = True,
) -> bool:
    """
    Orchestrate plan closure workflow (thin orchestrator)

    Auto-confirms by default: running 'close' IS the intent.
    spawn_background and refresh_dashboards are False from close_all_plans(): it does both once.
    """
    # One lock over the whole close: it resolves, writes, archives and writes again.
    try:
        with registry_lock():
            result = close_plan_impl(
                plan_num=plan_num,
                confirm=confirm,
                all_plans=all_plans,
                spawn_background=spawn_background,
                dry_run=dry_run,
                exclude_types=exclude_types,
                refresh_dashboards=refresh_dashboards,
                normalize_plan_number=normalize_plan_number,
                load_registry=load_registry,
                save_registry=save_registry,
                validate_plan_exists=validate_plan_exists,
                confirm_plan_deletion=confirm_plan_deletion,
                is_template_content=is_template_content,
                update_dashboard_local=update_dashboard_local,
                push_to_plans_central=push_to_plans_central,
                push_flow_to_branch_dashboard=push_flow_to_branch_dashboard,
                close_all_plans_fn=close_all_plans,
                archive_plan_fn=archive_plan,
                trigger_fire_fn=_trigger_fire,
            )
    except TimeoutError as exc:
        error_display(str(exc))
        return False

    if isinstance(result, dict):
        _display_messages(result.get("messages", []))
        return result.get("success", False)

    return bool(result)


def close_all_plans(confirm: bool = False, dry_run: bool = False, exclude_types: List[str] | None = None) -> bool:
    """
    Close all open plans in one operation (thin orchestrator)

    Scope is resolved only in the handler, from the caller's location; nothing is passed in.
    """
    result = close_all_plans_impl(
        confirm=confirm,
        dry_run=dry_run,
        exclude_types=exclude_types,
        get_open_plans=get_open_plans,
        close_plan_fn=close_plan,
        update_dashboard_local=update_dashboard_local,
        push_to_plans_central=push_to_plans_central,
        push_flow_to_branch_dashboard=push_flow_to_branch_dashboard,
    )

    if isinstance(result, dict):
        _display_messages(result.get("messages", []))
        return result.get("success", False)

    return bool(result)


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for close_plan module (thin orchestrator)

    Raises SystemExit(1) on a refusal or failed close; False means only "not my command".
    """
    if command != "close":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere in args wins: a help question must never close a plan.
    if wants_help(args):
        print_help()
        return True

    from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

    json_handler.log_operation("plan_closed", {"command": command, "args": args})

    plan_num, confirm, all_plans, dry_run, exclude_types, error = parse_close_command_args(args)

    if error:
        # The parser's own message and nothing else: a generic usage block would hide the real reason.
        console.print()
        error_display(error)
        console.print()
        console.print("[dim]Run 'drone @flow close --help' for usage[/dim]")
        console.print()
        # A refusal must exit non-zero so `&&` chains stop.
        raise SystemExit(1)

    closed = close_plan(
        plan_num=plan_num, confirm=confirm, all_plans=all_plans, dry_run=dry_run, exclude_types=exclude_types
    )

    # Handled is not succeeded: exit 1. Never return False, which flow.py reads as "Unknown command".
    if not closed:
        raise SystemExit(1)

    return True


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        import argparse

        PARSER = argparse.ArgumentParser(
            description="Close PLAN file",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
COMMANDS:
  close, close_plan      Close a single plan
  close --all            Close all open plans

USAGE:
  drone @flow close <PLAN-ID>
  drone @flow close <PLAN-ID> --confirm
  drone @flow close --all
  drone @flow close --help

OPTIONS:
  --confirm, --interactive   Request confirmation prompt (off by default)
  --yes, -y                  Backwards compat (redundant, already auto-confirms)
  --all                      Close all open plans

EXAMPLES:
  # Close plan (auto-confirms)
  drone @flow close FPLAN-0042

  # Close with interactive confirmation prompt
  drone @flow close FPLAN-0042 --confirm

  # Close all open plans (auto-confirms)
  drone @flow close --all
            """,
        )
        PARSER.print_help()
        sys.exit(0)

    logger.info("Prax logger connected to close_plan")

    json_handler.log_operation("plan_closed", {"command": "standalone"})

    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args:
        console.print(format_delete_usage_error())
        console.print("Run with --help for usage information")
        console.print()
        sys.exit(1)

    # A bare plan number (no verb) is still accepted.
    if args[0] not in ["close", "close_plan"]:
        args.insert(0, "close")

    result = handle_command(args[0], args[1:])
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
