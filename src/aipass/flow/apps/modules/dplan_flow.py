#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: dev_flow.py - Plan management module (thin orchestrator)
# Date: 2025-12-02
# Version: 4.0.0
# Category: Module
#
# CHANGELOG (Max 5 entries):
#   - v4.0.0 (2026-02-19): Multi-type (DPLAN/BPLAN), --type flag, @ branch resolution
#   - v3.0.0 (2026-02-18): Tags, filters, registry, dashboard per FPLAN-0355
#   - v2.0.0 (2025-12-02): Refactored to thin orchestrator - all logic in handlers
#   - v1.0.0 (2025-12-02): Initial version - plan create/list/status commands
#
# CONNECTS:
#   - handlers/plan/ (all plan handlers)
#   - registry.py (plan tracking)
#   - dashboard.py (DASHBOARD.local.json + DEVPULSE.central.json push)
#   - BRANCH_REGISTRY.json (@ resolution)
#
# CODE STANDARDS:
#   - Modules orchestrate, handlers implement (3-tier architecture)
#   - handle_command() interface for drone routing
#   - Module does the logging, handlers return errors
#   - CLI services for output (no print())
# ==============================================

"""
Plan Management Module - Thin Orchestrator

Routes commands to handlers in handlers/plan/.
Manages numbered, dated planning documents (DPLAN, BPLAN) in dev_planning/.
Supports @ branch resolution for creating plans in other branches.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
import json
from pathlib import Path
from typing import List, Optional

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# Infrastructure imports (module does the logging)
from prax.apps.modules.logger import system_logger as logger
from cli.apps.modules import console, header, success, error

# Handler imports
from aipass_os.dev_central.devpulse.apps.handlers.plan.create import create_plan
from aipass_os.dev_central.devpulse.apps.handlers.plan.list import list_plans
from aipass_os.dev_central.devpulse.apps.handlers.plan.status import get_status_summary, get_status_icon, VALID_TAGS
from aipass_os.dev_central.devpulse.apps.handlers.plan.display import show_help, print_introspection
from aipass_os.dev_central.devpulse.apps.handlers.plan.close import (
    normalize_plan_number, close_plan, get_open_plans
)
from aipass_os.dev_central.devpulse.apps.handlers.plan.counter import VALID_PLAN_TYPES
from aipass_os.dev_central.devpulse.apps.handlers.plan.registry import (
    register_plan, update_plan_status, populate_from_filesystem,
    get_summary, save_plan_summary, generate_description_summary
)
from aipass_os.dev_central.devpulse.apps.handlers.plan.dashboard import push_all as _push_dashboard_raw
from aipass_os.dev_central.devpulse.apps.handlers.dashboard.operations import write_section


def push_dashboard(activity: str | None = None) -> dict:
    """Module-level wrapper: injects write_section into handler."""
    return _push_dashboard_raw(activity=activity, write_fn=write_section)

# =============================================================================
# CONFIGURATION
# =============================================================================

BRANCH_REGISTRY_PATH = Path.home() / "BRANCH_REGISTRY.json"


# =============================================================================
# @ BRANCH RESOLUTION
# =============================================================================

def resolve_branch_target(branch_ref: str) -> Optional[Path]:
    """
    Resolve @branch reference to a filesystem path via BRANCH_REGISTRY.json.

    Args:
        branch_ref: Branch reference like "@vera" or "@team_1"

    Returns:
        Path to the branch directory, or None if not found
    """
    name = branch_ref.lstrip("@").upper()

    if not BRANCH_REGISTRY_PATH.exists():
        logger.warning(f"[dev_flow] BRANCH_REGISTRY.json not found at {BRANCH_REGISTRY_PATH}")
        return None

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)

        for branch in registry.get("branches", []):
            if branch.get("name", "").upper() == name:
                branch_path = Path(branch["path"])
                if branch_path.exists():
                    return branch_path
                else:
                    logger.warning(f"[dev_flow] Branch path does not exist: {branch_path}")
                    return None

        logger.warning(f"[dev_flow] Branch '{name}' not found in registry")
        return None

    except Exception as e:
        logger.warning(f"[dev_flow] Failed to read branch registry: {e}")
        return None


# =============================================================================
# MODULE INTERFACE
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle D-PLAN commands - routes to handlers

    Args:
        command: Command to execute ('plan')
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    if command != 'plan':
        return False

    # Handle --help flag
    if args and args[0] == '--help':
        header("D-PLAN - Development Planning")
        console.print(show_help())
        return True

    # Parse subcommand
    if not args:
        header("D-PLAN - Development Planning")
        console.print(show_help())
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
    # Handle --help flag
    if args and args[0] == '--help':
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

    # Check for --dir flag
    if '--dir' in args:
        dir_idx = args.index('--dir')
        if dir_idx + 1 < len(args):
            subdir = args[dir_idx + 1]
        else:
            error("--dir requires a subdirectory name")
            return True

    # Check for --tag flag
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

    # Check for --type flag
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

    # Check for @branch target or pre-resolved path (drone resolves @vera to /path)
    for arg in args[1:]:
        if arg.startswith("@") and not arg.startswith("--"):
            target_branch_name = arg
            target_path = resolve_branch_target(arg)
            if target_path is None:
                error(f"Could not resolve branch target '{arg}'")
                return True
            break
        elif arg.startswith("/") and Path(arg).exists():
            # Drone pre-resolved @branch to absolute path
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

    # Log success (module does logging)
    logger.info(f"[dev_flow] Created {prefix}-{result['plan_number']:03d}: {result['filename']}")

    # Log cache warning if any
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

        # Push dashboard update with activity context
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
    # Parse filter flags
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

    # Delegate to handler (pass type filter for scanning)
    plans, err = list_plans(filter_type=filter_type)

    if err:
        logger.error(f"[dev_flow] Failed to list plans: {err}")
        error(f"Failed to list plans: {err}")
        return True

    # Apply tag/status filters
    if filter_tag:
        plans = [p for p in plans if p.get("tag") == filter_tag]
    if filter_status:
        plans = [p for p in plans if p.get("status") == filter_status]

    # Display results
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

        # Get summary from cache or description
        summary = get_summary(p["number"])
        if not summary:
            summary = p.get("description", "")

        # Format: icon PREFIX-NNN | Topic | (tag) | summary
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
    # Parse --type filter
    filter_type = None
    if '--type' in args:
        type_idx = args.index('--type')
        if type_idx + 1 < len(args):
            filter_type = args[type_idx + 1].lower()

    # Delegate to handler
    status_counts, total, err = get_status_summary(filter_type=filter_type)

    if err:
        logger.error(f"[dev_flow] Failed to get status: {err}")
        error(f"Failed to get status: {err}")
        return True

    # Display results
    console.print()
    title = "Plan Status"
    if filter_type:
        title = f"{filter_type.upper()} Status"
    header(title)
    console.print()

    console.print(f"  [yellow]📋 Planning:[/yellow]        {status_counts['planning']}")
    console.print(f"  [blue]🔄 In Progress:[/blue]      {status_counts['in_progress']}")
    console.print(f"  [green]✅ Ready:[/green]            {status_counts['ready']}")
    console.print(f"  [dim]✓ Complete:[/dim]         {status_counts['complete']}")
    console.print(f"  [red]❌ Abandoned:[/red]        {status_counts['abandoned']}")

    if status_counts["unknown"] > 0:
        console.print(f"  [dim]? Unknown:[/dim]          {status_counts['unknown']}")

    console.print()
    console.print(f"[dim]Total: {total} plans[/dim]")
    console.print()

    return True


def _handle_close(args: List[str]) -> bool:
    """Orchestrate plan closing - delegates to handler, spawns background archival"""
    import subprocess

    # Handle --help flag
    if args and args[0] == '--help':
        console.print("\n[bold]USAGE:[/bold]")
        console.print("  plan close <number>")
        console.print("  plan close --all")
        console.print("\n[bold]EXAMPLES:[/bold]")
        console.print("  plan close 3")
        console.print("  plan close DPLAN-003")
        console.print("  plan close --all\n")
        return True

    # Handle --all flag
    if args and args[0] == '--all':
        return _handle_close_all()

    if len(args) < 1:
        error("Usage: plan close <number>")
        return True

    # Parse plan number
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

        # Generate and cache summary from description
        plan_file = Path(result.get('plan_file', ''))
        if plan_file.exists():
            summary = generate_description_summary(plan_file)
            if summary:
                save_plan_summary(plan_num, summary, "complete", result['topic'], str(plan_file))
    except Exception as e:
        logger.warning(f"[dev_flow] Registry update failed: {e}")

    # Push dashboard update with activity context
    try:
        activity = f"DPLAN-{plan_num:03d} closed ({result['topic'][:30]})"
        push_dashboard(activity=activity)
    except Exception as e:
        logger.warning(f"[dev_flow] Dashboard push failed: {e}")

    # Append to branch's CLOSED_PLANS.local.json
    try:
        from datetime import datetime as _dt
        _closed_plans_path = Path("/home/aipass/aipass_os/dev_central/CLOSED_PLANS.local.json")
        _entry = {
            "plan_id": f"DPLAN-{plan_num:03d}",
            "type": "DPLAN",
            "subject": result.get("topic", ""),
            "date_closed": _dt.now().strftime("%Y-%m-%d"),
            "location": "dev_central"
        }
        if _closed_plans_path.exists():
            _data = json.loads(_closed_plans_path.read_text())
        else:
            _data = {"closed_plans": []}
        # Skip if already exists
        if not any(p["plan_id"] == _entry["plan_id"] for p in _data["closed_plans"]):
            _data["closed_plans"].insert(0, _entry)
            _closed_plans_path.write_text(json.dumps(_data, indent=2) + "\n")
        logger.info(f"[dev_flow] Updated CLOSED_PLANS registry with DPLAN-{plan_num:03d}")
    except Exception as _e:
        logger.warning(f"[dev_flow] CLOSED_PLANS update failed (non-critical): {_e}")

    # Step 2/3: Spawn background processing
    console.print(f"[dim][2/3][/dim] Starting background archival...")
    try:
        bg_runner = Path(__file__).parent / "post_close_runner.py"
        log_file = Path.home() / "aipass_os" / "logs" / "post_close_runner.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_file, "a")
        subprocess.Popen(
            [sys.executable, str(bg_runner)],
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True
        )
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
    import subprocess

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

            # Update registry
            try:
                update_plan_status(p['number'], "complete")
            except Exception as reg_err:
                logger.warning(f"[dev_flow] Registry update failed for DPLAN-{p['number']:03d}: {reg_err}")

            # Append to branch's CLOSED_PLANS.local.json
            try:
                from datetime import datetime as _dt
                _closed_plans_path = Path("/home/aipass/aipass_os/dev_central/CLOSED_PLANS.local.json")
                _entry = {
                    "plan_id": f"DPLAN-{p['number']:03d}",
                    "type": "DPLAN",
                    "subject": result.get("topic", ""),
                    "date_closed": _dt.now().strftime("%Y-%m-%d"),
                    "location": "dev_central"
                }
                if _closed_plans_path.exists():
                    _data = json.loads(_closed_plans_path.read_text())
                else:
                    _data = {"closed_plans": []}
                if not any(ep["plan_id"] == _entry["plan_id"] for ep in _data["closed_plans"]):
                    _data["closed_plans"].insert(0, _entry)
                    _closed_plans_path.write_text(json.dumps(_data, indent=2) + "\n")
                logger.info(f"[dev_flow] Updated CLOSED_PLANS registry with DPLAN-{p['number']:03d}")
            except Exception as _e:
                logger.warning(f"[dev_flow] CLOSED_PLANS update failed (non-critical): {_e}")
        else:
            failure_count += 1
            logger.warning(f"[dev_flow] Failed to close DPLAN-{p['number']:03d}: {err}")
            console.print(f"[red]  Failed: {err}[/red]")

    # Push dashboard update with activity context
    try:
        activity = f"{success_count} plan(s) closed (batch)"
        push_dashboard(activity=activity)
    except Exception as e:
        logger.warning(f"[dev_flow] Dashboard push failed: {e}")

    # Spawn ONE background process for all closed plans
    if success_count > 0:
        try:
            bg_runner = Path(__file__).parent / "post_close_runner.py"
            subprocess.Popen(
                [sys.executable, str(bg_runner)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            logger.info(f"[dev_flow] Spawned background processing for {success_count} closed plan(s)")
            console.print(f"\n[dim]Background processing started for {success_count} plan(s)[/dim]")
        except Exception as e:
            logger.warning(f"[dev_flow] Failed to spawn background processing: {e}")
            console.print(f"\n[yellow]Background processing failed to start[/yellow]")

    console.print("\n" + "═" * 60)
    console.print("[bold green]CLOSE ALL COMPLETE[/bold green]")
    console.print(f"  - Successfully closed: {success_count}")
    console.print(f"  - Failed: {failure_count}")
    console.print("═" * 60 + "\n")

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
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        console.print(print_introspection())
        sys.exit(0)

    # Handle help flag
    if sys.argv[1] in ['--help', '-h', 'help']:
        header("D-PLAN - Development Planning")
        console.print(show_help())
        sys.exit(0)

    # Route command: plan create "topic" -> handle_command("plan", ["create", "topic"])
    subcommand = sys.argv[1]
    remaining_args = sys.argv[2:] if len(sys.argv) > 2 else []

    if handle_command('plan', [subcommand] + remaining_args):
        sys.exit(0)
    else:
        console.print()
        console.print("[red]Failed to handle command[/red]")
        console.print()
        sys.exit(1)
