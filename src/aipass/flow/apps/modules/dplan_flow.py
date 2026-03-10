# =================== AIPass ====================
# Name: dplan_flow.py
# Description: Plan management module (thin orchestrator)
# Version: 5.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
Plan Management Module - Thin Orchestrator

Routes commands to handlers in handlers/dplan/.
Manages numbered, dated planning documents (DPLAN, BPLAN) in dev_planning/.
Supports @ branch resolution for creating plans in other branches.
"""

import sys
from pathlib import Path
from typing import List

# Infrastructure imports (module does the logging)
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error

# Handler imports (local handlers in handlers/dplan/)
from aipass.flow.apps.handlers.dplan.create import create_plan
from aipass.flow.apps.handlers.dplan.list import list_plans
from aipass.flow.apps.handlers.dplan.status import get_status_summary, get_status_icon, VALID_TAGS
from aipass.flow.apps.handlers.dplan.display import show_help, print_introspection
from aipass.flow.apps.handlers.dplan.close import (
    normalize_plan_number, close_plan, get_open_plans
)
from aipass.flow.apps.handlers.dplan.counter import VALID_PLAN_TYPES
from aipass.flow.apps.handlers.dplan.registry import (
    register_plan, update_plan_status, populate_from_filesystem,
    get_summary, save_plan_summary, generate_description_summary
)
from aipass.flow.apps.handlers.dplan.dashboard import push_all as _push_dashboard_raw
from aipass.prax.apps.handlers.dashboard.operations import write_section

# Local handlers (file I/O extracted from this module)
from aipass.flow.apps.handlers.dplan.branch_resolve import resolve_branch_target as _resolve_branch
from aipass.flow.apps.handlers.dplan.closed_plans_registry import append_closed_dplan
from aipass.flow.apps.handlers.dplan.log_setup import prepare_log_file
from aipass.flow.apps.handlers.dplan.background_spawn import spawn_post_close


def push_dashboard(activity: str | None = None) -> dict:
    """Module-level wrapper: injects write_section into handler."""
    return _push_dashboard_raw(activity=activity, write_fn=write_section)


# =============================================================================
# @ BRANCH RESOLUTION (thin wrapper around handler)
# =============================================================================

def resolve_branch_target(branch_ref: str):
    """Resolve @branch reference — delegates to handler, logs result."""
    result = _resolve_branch(branch_ref)
    if not result["success"]:
        logger.warning(f"[dev_flow] {result['error']}")
        return None
    return result["path"]


# =============================================================================
# MODULE INTERFACE
# =============================================================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("dplan_flow Module")
    console.print("Plan management orchestrator — routes plan commands to handlers")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/dplan/")
    console.print("    - create.py (create_plan — create new plans)")
    console.print("    - list.py (list_plans — list plans with filters)")
    console.print("    - status.py (get_status_summary — plan status aggregation)")
    console.print("    - display.py (show_help — help text display)")
    console.print("    - close.py (close_plan, get_open_plans — close plans)")
    console.print("    - counter.py (VALID_PLAN_TYPES — plan type definitions)")
    console.print("    - registry.py (register_plan, update_plan_status — registry ops)")
    console.print("    - dashboard.py (push_all — dashboard updates)")
    console.print("    - branch_resolve.py (resolve_branch_target — @ branch resolution)")
    console.print("    - closed_plans_registry.py (append_closed_dplan — closed plan tracking)")
    console.print("    - log_setup.py (prepare_log_file — log file preparation)")
    console.print("    - background_spawn.py (spawn_post_close — background archival)")
    console.print()
    console.print("  External:")
    console.print("    - aipass.prax (write_section — dashboard section writer)")
    console.print()


def print_help():
    """Display D-PLAN help text — thin wrapper around handler's show_help()."""
    header("D-PLAN - Development Planning")
    console.print(show_help())


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle D-PLAN commands - routes to handlers.

    Args:
        command: Command to execute ('plan')
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    if command != 'plan':
        return False

    # Handle --help / -h flag
    if not args or (args[0] in ('--help', '-h')):
        print_help()
        return True

    subcommand = args[0]

    if subcommand == 'create':
        return _handle_create(args[1:])
    elif subcommand == 'list':
        return _handle_list(args[1:])
    elif subcommand == 'status':
        return _handle_status(args[1:])
    elif subcommand == 'close':
        return _handle_close(args[1:])
    elif subcommand == 'sync':
        return _handle_sync()
    else:
        error(f"Unknown subcommand: {subcommand}")
        console.print("Run 'plan --help' for usage")
        return True


# =============================================================================
# COMMAND HANDLERS (orchestration only)
# =============================================================================

def _handle_create(args: List[str]) -> bool:
    """Orchestrate plan creation - delegates to handler"""
    if args and args[0] in ('--help', '-h'):
        console.print("\n[bold]USAGE:[/bold]")
        console.print("  plan create \"topic name\" [--type type] [--tag tag] [--dir subdir] [@branch]")
        console.print("\n[bold]OPTIONS:[/bold]")
        console.print("  --type <type> Plan type: dplan (default), bplan")
        console.print("  --tag <tag>   Set plan tag (default: idea)")
        console.print("  --dir <name>  Create plan in dev_planning/<name>/ subdirectory")
        console.print("  @<branch>     Create in target branch's dev_planning/")
        console.print(f"\n[bold]TAGS:[/bold] {', '.join(VALID_TAGS)}")
        console.print("\n[bold]EXAMPLES:[/bold]")
        console.print("  plan create \"new feature design\"")
        console.print("  plan create \"API upgrade\" --tag upgrade")
        console.print("  plan create \"revenue model\" --type bplan")
        console.print("  plan create \"vera improvements\" @vera\n")
        return True

    if len(args) < 1:
        error("Usage: plan create \"topic name\" [--type type] [--tag tag] [@branch]")
        return True

    # Parse arguments: topic and optional flags
    topic = args[0]
    subdir = None
    tag = "idea"
    plan_type = "dplan"
    target_path = None
    target_branch_name = None

    if '--dir' in args:
        dir_idx = args.index('--dir')
        if dir_idx + 1 < len(args):
            subdir = args[dir_idx + 1]
        else:
            error("--dir requires a subdirectory name")
            return True

    if '--tag' in args:
        tag_idx = args.index('--tag')
        if tag_idx + 1 < len(args):
            tag = args[tag_idx + 1].lower()
            if tag not in VALID_TAGS:
                error(f"Invalid tag '{tag}'. Valid tags: {', '.join(VALID_TAGS)}")
                return True
        else:
            error("--tag requires a tag name")
            return True

    if '--type' in args:
        type_idx = args.index('--type')
        if type_idx + 1 < len(args):
            plan_type = args[type_idx + 1].lower()
            if plan_type not in VALID_PLAN_TYPES:
                valid = ", ".join(VALID_PLAN_TYPES.keys())
                error(f"Invalid plan type '{plan_type}'. Valid types: {valid}")
                return True
        else:
            error("--type requires a plan type (dplan, bplan)")
            return True

    # Check for @branch target or pre-resolved path
    for arg in args[1:]:
        if arg.startswith("@") and not arg.startswith("--"):
            target_branch_name = arg
            target_path = resolve_branch_target(arg)
            if target_path is None:
                error(f"Could not resolve branch target '{arg}'")
                return True
            break
        elif arg.startswith("/") and Path(arg).exists():
            target_branch_name = f"@{Path(arg).name}"
            target_path = Path(arg)
            break

    prefix = VALID_PLAN_TYPES[plan_type]

    # Delegate to handler
    ok, result, err = create_plan(
        topic, tag=tag, plan_type=plan_type,
        target_path=target_path, subdir=subdir
    )

    if not ok:
        logger.error(f"[dev_flow] Failed to create plan: {err}")
        error(f"Failed to create plan: {err}")
        return True

    logger.info(f"[dev_flow] Created {prefix}-{result['plan_number']:03d}: {result['filename']}")

    if result.get('cache_warning'):
        logger.warning(f"[dev_flow] {result['cache_warning']}")

    # Register in registry (only for local plans, not @ targets)
    if not target_path:
        try:
            register_plan(
                plan_number=result['plan_number'],
                topic=result['topic'],
                status="planning",
                tag=tag,
                file_path=result['path'],
                date=result['date']
            )
            logger.info(f"[dev_flow] Registered {prefix}-{result['plan_number']:03d} in registry")
        except Exception as e:
            logger.warning(f"[dev_flow] Failed to register plan: {e}")

        try:
            activity = f"DPLAN-{result['plan_number']:03d} created ({result['topic'][:30]})"
            push_dashboard(activity=activity)
        except Exception as e:
            logger.warning(f"[dev_flow] Dashboard push failed: {e}")

    # Display result
    console.print()
    success(f"Created {prefix}-{result['plan_number']:03d}")
    console.print(f"  [dim]Topic:[/dim] {result['topic']}")
    console.print(f"  [dim]Type:[/dim] {plan_type.upper()}")
    console.print(f"  [dim]Tag:[/dim] {tag}")
    if target_branch_name:
        console.print(f"  [dim]Target:[/dim] {target_branch_name}")
    console.print(f"  [dim]File:[/dim] {result['path']}")
    console.print()

    return True


def _handle_list(args: List[str]) -> bool:
    """Orchestrate plan listing with optional filters"""
    filter_tag = None
    filter_status = None
    filter_type = None

    if '--tag' in args:
        tag_idx = args.index('--tag')
        if tag_idx + 1 < len(args):
            filter_tag = args[tag_idx + 1].lower()

    if '--status' in args:
        status_idx = args.index('--status')
        if status_idx + 1 < len(args):
            filter_status = args[status_idx + 1].lower()

    if '--type' in args:
        type_idx = args.index('--type')
        if type_idx + 1 < len(args):
            filter_type = args[type_idx + 1].lower()

    plans, err = list_plans(filter_type=filter_type)

    if err:
        logger.error(f"[dev_flow] Failed to list plans: {err}")
        error(f"Failed to list plans: {err}")
        return True

    if filter_tag:
        plans = [p for p in plans if p.get("tag") == filter_tag]
    if filter_status:
        plans = [p for p in plans if p.get("status") == filter_status]

    console.print()
    title = "Plans"
    if filter_type:
        title = f"{filter_type.upper()}s"
    filters = []
    if filter_tag:
        filters.append(f"tag: {filter_tag}")
    if filter_status:
        filters.append(f"status: {filter_status}")
    if filters:
        title += f" ({', '.join(filters)})"
    header(title)
    console.print()

    if not plans:
        console.print("[dim]No plans found[/dim]")
        console.print()
        return True

    for p in plans:
        status_icon = get_status_icon(p["status"])
        tag_display = f"({p['tag']})" if p.get("tag") else ""
        prefix = p.get("prefix", "DPLAN")

        summary = get_summary(p["number"])
        if not summary:
            summary = p.get("description", "")

        line = f"  {status_icon} [cyan]{prefix}-{p['number']:03d}[/cyan] | {p['topic'][:30]:<30}"
        if tag_display:
            line += f" | [dim]{tag_display}[/dim]"
        if summary:
            line += f" — [dim italic]{summary[:50]}[/dim italic]"

        console.print(line)

    console.print()
    console.print(f"[dim]Total: {len(plans)} plans[/dim]")
    console.print()

    return True


def _handle_status(args: List[str]) -> bool:
    """Orchestrate status display - delegates to handler"""
    filter_type = None
    if '--type' in args:
        type_idx = args.index('--type')
        if type_idx + 1 < len(args):
            filter_type = args[type_idx + 1].lower()

    status_counts, total, err = get_status_summary(filter_type=filter_type)

    if err:
        logger.error(f"[dev_flow] Failed to get status: {err}")
        error(f"Failed to get status: {err}")
        return True

    console.print()
    title = "Plan Status"
    if filter_type:
        title = f"{filter_type.upper()} Status"
    header(title)
    console.print()

    console.print(f"  [yellow]Planning:[/yellow]        {status_counts['planning']}")
    console.print(f"  [blue]In Progress:[/blue]      {status_counts['in_progress']}")
    console.print(f"  [green]Ready:[/green]            {status_counts['ready']}")
    console.print(f"  [dim]Complete:[/dim]         {status_counts['complete']}")
    console.print(f"  [red]Abandoned:[/red]        {status_counts['abandoned']}")

    if status_counts["unknown"] > 0:
        console.print(f"  [dim]Unknown:[/dim]          {status_counts['unknown']}")

    console.print()
    console.print(f"[dim]Total: {total} plans[/dim]")
    console.print()

    return True


def _handle_close(args: List[str]) -> bool:
    """Orchestrate plan closing - delegates to handler, spawns background archival"""
    if args and args[0] in ('--help', '-h'):
        console.print("\n[bold]USAGE:[/bold]")
        console.print("  plan close <number>")
        console.print("  plan close --all")
        console.print("\n[bold]EXAMPLES:[/bold]")
        console.print("  plan close 3")
        console.print("  plan close DPLAN-003")
        console.print("  plan close --all\n")
        return True

    if args and args[0] == '--all':
        return _handle_close_all()

    if len(args) < 1:
        error("Usage: plan close <number>")
        return True

    plan_num, err = normalize_plan_number(args[0])
    if err:
        logger.warning(f"[dev_flow] {err}")
        error(err)
        return True

    # Step 1/3: Close plan (mark as complete)
    console.print(f"\n[dim][1/3][/dim] Closing DPLAN-{plan_num:03d}...")
    ok, result, err = close_plan(plan_num)

    if not ok:
        logger.warning(f"[dev_flow] Failed to close DPLAN-{plan_num:03d}: {err}")
        error(err)
        return True

    logger.info(f"[dev_flow] Closed DPLAN-{plan_num:03d}: {result['topic']}")
    console.print(f"[green]  Marked as complete[/green]")

    # Update registry
    try:
        update_plan_status(plan_num, "complete")

        plan_file = Path(result.get('plan_file', ''))
        if plan_file.exists():
            summary = generate_description_summary(plan_file)
            if summary:
                save_plan_summary(plan_num, summary, "complete", result['topic'], str(plan_file))
    except Exception as e:
        logger.warning(f"[dev_flow] Registry update failed: {e}")

    # Push dashboard update
    try:
        activity = f"DPLAN-{plan_num:03d} closed ({result['topic'][:30]})"
        push_dashboard(activity=activity)
    except Exception as e:
        logger.warning(f"[dev_flow] Dashboard push failed: {e}")

    # Append to CLOSED_PLANS.local.json via handler
    reg_result = append_closed_dplan(plan_num, result.get("topic", ""))
    if reg_result["success"]:
        logger.info(f"[dev_flow] Updated CLOSED_PLANS registry with {reg_result['plan_id']}")
    else:
        logger.warning(f"[dev_flow] CLOSED_PLANS update failed (non-critical): {reg_result['error']}")

    # Step 2/3: Spawn background processing
    console.print(f"[dim][2/3][/dim] Starting background archival...")
    try:
        log_result = prepare_log_file("post_close_runner.log")
        if not log_result["success"]:
            raise RuntimeError(log_result["error"])
        spawn_result = spawn_post_close(log_file_handle=log_result["file_handle"])
        if not spawn_result["success"]:
            raise RuntimeError(spawn_result["error"])
        logger.info(f"[dev_flow] Spawned background post-processing for DPLAN-{plan_num:03d}")
        console.print(f"[dim]  Memory Bank archival running in background[/dim]")
    except Exception as e:
        logger.warning(f"[dev_flow] Failed to spawn background processing: {e}")
        console.print(f"[yellow]  Background archival failed to start - will retry on next close[/yellow]")

    # Step 3/3: Done
    console.print(f"[dim][3/3][/dim] Finalizing...")
    console.print()
    success(f"DPLAN-{plan_num:03d} closed ({result['topic']})")
    console.print(f"  [dim]Previous status:[/dim] {result['old_status']}")
    console.print(f"  [dim]Archive:[/dim] Memory Bank processing in background")
    console.print()

    return True


def _handle_close_all() -> bool:
    """Close all open plans"""
    open_plans = get_open_plans()

    if not open_plans:
        console.print("\n[yellow]No open plans to close[/yellow]\n")
        return True

    console.print(f"\n[bold yellow]Found {len(open_plans)} open plan(s) to close:[/bold yellow]")
    for p in open_plans:
        console.print(f"  - DPLAN-{p['number']:03d}: {p['topic']}")

    console.print(f"\n[bold]Closing all {len(open_plans)} plan(s)...[/bold]")
    console.print("─" * 60)

    success_count = 0
    failure_count = 0

    for p in open_plans:
        console.print(f"\n[dim]Closing DPLAN-{p['number']:03d}...[/dim]")
        ok, result, err = close_plan(p['number'])
        if ok:
            success_count += 1
            logger.info(f"[dev_flow] Closed DPLAN-{p['number']:03d}")
            console.print(f"[green]  Marked as complete[/green]")

            try:
                update_plan_status(p['number'], "complete")
            except Exception as reg_err:
                logger.warning(f"[dev_flow] Registry update failed for DPLAN-{p['number']:03d}: {reg_err}")

            # Append to CLOSED_PLANS.local.json via handler
            reg_result = append_closed_dplan(p['number'], result.get("topic", ""))
            if reg_result["success"]:
                logger.info(f"[dev_flow] Updated CLOSED_PLANS registry with {reg_result['plan_id']}")
            else:
                logger.warning(f"[dev_flow] CLOSED_PLANS update failed (non-critical): {reg_result['error']}")
        else:
            failure_count += 1
            logger.warning(f"[dev_flow] Failed to close DPLAN-{p['number']:03d}: {err}")
            console.print(f"[red]  Failed: {err}[/red]")

    # Push dashboard
    try:
        activity = f"{success_count} plan(s) closed (batch)"
        push_dashboard(activity=activity)
    except Exception as e:
        logger.warning(f"[dev_flow] Dashboard push failed: {e}")

    # Spawn ONE background process for all closed plans
    if success_count > 0:
        try:
            spawn_result = spawn_post_close()
            if not spawn_result["success"]:
                raise RuntimeError(spawn_result["error"])
            logger.info(f"[dev_flow] Spawned background processing for {success_count} closed plan(s)")
            console.print(f"\n[dim]Background processing started for {success_count} plan(s)[/dim]")
        except Exception as e:
            logger.warning(f"[dev_flow] Failed to spawn background processing: {e}")
            console.print(f"\n[yellow]Background processing failed to start[/yellow]")

    console.print("\n" + "=" * 60)
    console.print("[bold green]CLOSE ALL COMPLETE[/bold green]")
    console.print(f"  - Successfully closed: {success_count}")
    console.print(f"  - Failed: {failure_count}")
    console.print("=" * 60 + "\n")

    return True


def _handle_sync() -> bool:
    """Sync registry from filesystem and push dashboard"""
    console.print("\n[dim]Syncing registry from filesystem...[/dim]")

    try:
        registry = populate_from_filesystem()
        plan_count = len(registry.get("plans", {}))
        success(f"Registry synced: {plan_count} plans")
    except Exception as e:
        logger.warning(f"[dev_flow] Registry sync failed: {e}")
        error(f"Registry sync failed: {e}")
        return True

    try:
        activity = f"Registry synced ({plan_count} plans)"
        summary = push_dashboard(activity=activity)
        total = summary.get("dplan_counts", {}).get("total", 0)
        console.print(f"[dim]Dashboard updated: {total} plans[/dim]")
    except Exception as e:
        logger.warning(f"[dev_flow] Dashboard push failed: {e}")

    console.print()
    return True


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) == 1:
        console.print(print_introspection())
        sys.exit(0)

    if sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    subcommand = sys.argv[1]
    remaining_args = sys.argv[2:] if len(sys.argv) > 2 else []

    if handle_command('plan', [subcommand] + remaining_args):
        sys.exit(0)
    else:
        console.print()
        console.print("[red]Failed to handle command[/red]")
        console.print()
        sys.exit(1)
