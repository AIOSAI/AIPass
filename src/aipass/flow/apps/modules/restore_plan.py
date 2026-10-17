# =================== AIPass ====================
# Name: restore_plan.py
# Description: PLAN restore module (reopen closed plans)
# Version: 1.5.0
# Created: 2025-11-22
# Modified: 2026-10-17
# =============================================

"""
Restore PLAN Module

Thin orchestrator for plan restore workflow (reopening closed plans).
All business logic delegated to handlers.
Module handles all display output.

Usage:
    From flow.py: flow restore <number>
    Standalone: drone @flow restore <number>
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

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler

from aipass.cli.apps.modules import console, warning

from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.save_registry import save_registry

from aipass.flow.apps.handlers.plan.validator import normalize_plan_number, validate_plan_exists
from aipass.flow.apps.handlers.plan.display import (
    format_restore_header,
    format_restore_error,
    format_restore_success,
    format_restore_usage_error,
)

from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central

from aipass.flow.apps.handlers.plan.restore_ops import (
    recover_plan_from_backup as _recover_plan_from_backup_impl,
    restore_plan_impl,
)

MODULE_NAME = "restore_plan"


def _display_messages(messages: List[Dict[str, Any]]):
    """Render handler result messages to console"""
    for msg in messages:
        msg_type = msg.get("type", "")

        if msg_type == "error":
            error_type = msg.get("error_type", "general")
            plan_key = msg.get("plan_key", "")
            details = msg.get("details", None)
            prefix = msg.get("prefix", "FPLAN")
            console.print(format_restore_error(error_type, plan_key, details=details, prefix=prefix))

        elif msg_type == "warning":
            warning(msg["text"])

        elif msg_type == "dim":
            console.print(f"[dim]{msg['text']}[/dim]")

        elif msg_type == "success":
            console.print(f"[green]{msg['text']}[/green]")

        elif msg_type == "restore_header":
            console.print(format_restore_header(msg["plan_key"], msg["plan_info"], prefix=msg.get("prefix", "FPLAN")))

        elif msg_type == "restore_success":
            console.print(
                format_restore_success(msg["plan_key"], msg.get("location"), prefix=msg.get("prefix", "FPLAN"))
            )


def print_introspection():
    """Display module info and connected handlers"""
    console.print()
    console.print("[bold cyan]restore_plan Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- restore_ops.py (implementation)[/dim]")
    console.print("    [dim]- command_parser.py[/dim]")
    console.print("    [dim]- validator.py[/dim]")
    console.print("    [dim]- display.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/registry/[/cyan]")
    console.print("    [dim]- load_registry.py[/dim]")
    console.print("    [dim]- save_registry.py[/dim]")
    console.print()

    console.print("  [cyan]handlers/dashboard/[/cyan]")
    console.print("    [dim]- update_local.py[/dim]")
    console.print("    [dim]- push_central.py[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow restore --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for restore_plan module"""
    console.print()
    console.print("[bold cyan]restore_plan[/bold cyan] — Reopen closed PLAN files")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow restore <PLAN-ID>")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow restore FPLAN-0042[/dim]        # Reopen a closed plan")
    console.print("  [dim]drone @flow restore DPLAN-0005[/dim]        # Reopen a closed DPLAN")
    console.print()
    console.print("[yellow]NOTES:[/yellow]")
    console.print("  Plan must be closed. File must exist at registered location.")
    console.print()


def recover_plan_from_backup(plan_key: str, plan_num_raw: str | None = None) -> tuple[bool, str]:
    """
    Attempt to recover a plan from processed_plans backup (thin orchestrator)

    plan_num_raw keeps the caller's prefix (e.g. "PPLAN-0165") to scope recovery to that type.
    """
    return _recover_plan_from_backup_impl(
        plan_key,
        plan_num_raw=plan_num_raw,
        load_registry=load_registry,
        save_registry=save_registry,
    )


def restore_plan(plan_num: str | None) -> bool:
    """Orchestrate plan restore workflow (thin orchestrator)"""
    # Lazy: a module-level import is circular.
    from aipass.flow.apps.modules.registry_monitor import scan_plan_files

    result = restore_plan_impl(
        plan_num=plan_num,
        normalize_plan_number=normalize_plan_number,
        load_registry=load_registry,
        save_registry=save_registry,
        validate_plan_exists=validate_plan_exists,
        recover_plan_from_backup_fn=recover_plan_from_backup,
        scan_plan_files=scan_plan_files,
        update_dashboard_local=update_dashboard_local,
        push_to_plans_central=push_to_plans_central,
    )

    _display_messages(result.get("messages", []))
    return result.get("success", False)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle command routing for restore_plan module (thin orchestrator)"""
    if command != "restore":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere in args: a help question must never restore a plan.
    if wants_help(args):
        print_help()
        return True

    from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

    json_handler.log_operation("plan_restored", {"command": command, "args": args})

    plan_num, error = parse_restore_command_args(args)

    if error:
        console.print(format_restore_usage_error())
        # Exiting 0 after refusing would tell a caller the plan was reopened.
        raise SystemExit(1)

    restored = restore_plan(plan_num=plan_num)

    # Not return False: flow.py reads that as "no module claimed this command".
    if not restored:
        raise SystemExit(1)

    return True


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        import argparse

        PARSER = argparse.ArgumentParser(
            description="Restore PLAN file to open status",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
COMMANDS:
  restore, restore_plan      Restore a closed plan to open status

USAGE:
  drone @flow restore <PLAN-ID>
  drone @flow restore --help

EXAMPLES:
  # Restore a closed plan
  drone @flow restore FPLAN-0042

  # Using plan number directly
  drone @flow restore FPLAN-0042

NOTES:
  - Plan must be closed to restore
  - Plan file must exist at registered location
  - Only updates registry metadata (does not move files)
            """,
        )
        PARSER.print_help()
        sys.exit(0)

    logger.info("Prax logger connected to restore_plan")

    json_handler.log_operation("plan_restored", {"command": "standalone"})

    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args:
        console.print(format_restore_usage_error())
        console.print("Run with --help for usage information")
        console.print()
        sys.exit(1)

    if args[0] not in ["restore", "restore_plan"]:
        args.insert(0, "restore")

    result = handle_command(args[0], args[1:])
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
