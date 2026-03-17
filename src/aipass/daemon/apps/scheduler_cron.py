# =================== AIPass ====================
# Name: scheduler_cron.py
# Description: DAEMON Scheduler Cron Trigger
# Version: 2.0.0
# Created: 2026-02-15
# Modified: 2026-03-10
# =============================================

"""
Cron trigger script for the DAEMON scheduled task system.

Called periodically by cron. Standalone script -- not imported as a module.

Flow:
  1. Acquire single-instance lock
  2. Recover stale dispatches
  3. Process all due tasks (send emails, mark complete)
  4. Process actions from registry
  5. Log summary
"""

# =============================================
# IMPORTS
# =============================================

import os
import sys
import time
import json
import subprocess
import importlib
from pathlib import Path
from datetime import datetime, timedelta

import fcntl

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler

# =============================================
# OPTIONAL IMPORTS (via module layer)
# =============================================

# Task registry (via module layer)
try:
    from aipass.daemon.apps.modules.scheduler_ops import (
        get_due_tasks,
        mark_dispatching,
        mark_completed,
        mark_pending,
        recover_stale_dispatches,
        TASK_REGISTRY_AVAILABLE,
    )
except ImportError:
    TASK_REGISTRY_AVAILABLE = False
    get_due_tasks = None
    mark_dispatching = None
    mark_completed = None
    mark_pending = None
    recover_stale_dispatches = None

# Email integration via drone subprocess
def _send_email_via_drone(to_branch, subject, message, from_branch='@daemon',
                          auto_execute=True, reply_to=None, **kwargs):
    """Send email via drone @ai_mail send subprocess."""
    cmd = ["drone", "@ai_mail", "send", to_branch, subject, message]
    if auto_execute:
        cmd.append("--dispatch")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False

AI_MAIL_AVAILABLE = True
send_email_direct = _send_email_via_drone

# Plugin discovery
try:
    from aipass.daemon.apps.plugins import discover_plugins
    PLUGINS_AVAILABLE = True
except ImportError:
    PLUGINS_AVAILABLE = False
    discover_plugins = None

# Action registry (DPLAN-043) (via module layer)
try:
    from aipass.daemon.apps.modules.scheduler_ops import (
        load_registry,
        is_action_due,
        update_last_run,
        mark_reminder_completed,
        migrate_plugins,
        next_due_str,
        ACTION_REGISTRY_AVAILABLE,
    )
except ImportError:
    ACTION_REGISTRY_AVAILABLE = False
    load_registry = None
    is_action_due = None
    update_last_run = None
    mark_reminder_completed = None
    migrate_plugins = None
    next_due_str = None

# =============================================
# CONSTANTS
# =============================================

_DAEMON_ROOT = Path(__file__).resolve().parents[2]  # src/aipass/daemon/
JSON_DIR = _DAEMON_ROOT / "daemon_json"

EVENT_NAME = "cron-run"
LOCK_FILE = JSON_DIR / "schedule.lock"
STALE_DISPATCH_MAX_AGE = 5  # minutes

# Wake script path (configurable via env var)
WAKE_SCRIPT = Path(os.environ.get('AIPASS_WAKE_SCRIPT', ''))

PLUGIN_LAST_RUN_FILE = Path(__file__).parent / "plugins" / ".last_run.json"

# =============================================
# LOGGING
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("scheduler_cron Module")
    console.print("Cron trigger for scheduled tasks and action registry processing")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - scheduler_ops.py (task registry ops + action registry ops, notifications archived)")
    console.print()
    console.print("  plugins/")
    console.print("    - discover_plugins (plugin discovery and scheduled execution)")
    console.print()


def print_help() -> None:
    """Display usage information for scheduler_cron."""
    console.print("\n[bold cyan]scheduler_cron.py - DAEMON Scheduler Cron Trigger[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  python scheduler_cron.py          Run the cron scheduler")
    console.print("  python scheduler_cron.py --help   Show this help message")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  Processes due scheduled tasks and actions from the registry.")
    console.print("  Intended to be called periodically by cron.")
    console.print()


def log(message: str) -> None:
    """Print timestamped log line to stdout (captured by cron redirect)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"[{timestamp}] {message}")


# =============================================
# TASK PROCESSING
# =============================================

def process_due_tasks() -> dict:
    """
    Process all due scheduled tasks.

    Recovers stale dispatches, then iterates due tasks:
    mark dispatching -> send email -> mark completed or reset to pending.

    Returns:
        Dict with keys: due, success, failed, errors (list of error strings)
    """
    results = {
        "due": 0,
        "success": 0,
        "failed": 0,
        "recovered": 0,
        "errors": [],
    }

    if not TASK_REGISTRY_AVAILABLE:
        log("WARNING: Task registry not available, skipping task processing")
        return results

    # Recover any stale dispatches (stuck > 5 minutes)
    try:
        recovered = recover_stale_dispatches(max_age_minutes=STALE_DISPATCH_MAX_AGE)  # type: ignore[misc]
        results["recovered"] = recovered
        if recovered:
            log(f"Recovered {recovered} stale dispatch(es)")
    except Exception as e:
        log(f"WARNING: Failed to recover stale dispatches: {e}")
        results["errors"].append(f"Stale recovery: {e}")

    # Get due tasks
    try:
        due_tasks = get_due_tasks()  # type: ignore[misc]
    except Exception as e:
        log(f"ERROR: Failed to load due tasks: {e}")
        results["errors"].append(f"Load tasks: {e}")
        return results

    results["due"] = len(due_tasks)

    if not due_tasks:
        log("No tasks due at this time.")
        return results

    log(f"Found {len(due_tasks)} due task(s)")

    # Process each due task
    for task in due_tasks:
        task_id = task.get("id", "")
        recipient = task.get("recipient", "")
        task_desc = task.get("task", "")
        message = task.get("message", "")

        log(f"Processing: {task_id[:8]} -> {recipient}: {task_desc[:50]}")

        # Mark as dispatching (prevents re-dispatch)
        try:
            mark_dispatching(task_id)  # type: ignore[misc]
        except Exception as e:
            log(f"WARNING: Failed to mark dispatching {task_id[:8]}: {e}")
            results["errors"].append(f"Mark dispatching {task_id[:8]}: {e}")
            results["failed"] += 1
            continue

        # Build email body
        email_body = f"{task_desc}"
        if message:
            email_body += f"\n\nDetails:\n{message}"

        # Send the email
        if not AI_MAIL_AVAILABLE:
            log(f"SKIP: ai_mail not available, cannot send to {recipient}")
            mark_pending(task_id)  # type: ignore[misc]
            results["failed"] += 1
            results["errors"].append(f"ai_mail unavailable for {task_id[:8]}")
            continue

        try:
            email_sent = send_email_direct(
                to_branch=recipient,
                subject=f"[SCHEDULED] {task_desc}",
                message=email_body,
                from_branch='@daemon',
                auto_execute=True,
                reply_to='@dev_central',
            )

            if email_sent:
                mark_completed(task_id)  # type: ignore[misc]
                log(f"OK: Sent to {recipient}: {task_desc[:40]}")
                results["success"] += 1
            else:
                mark_pending(task_id)  # type: ignore[misc]
                log(f"FAIL: Email returned False for {recipient}: {task_desc[:40]}")
                results["failed"] += 1
                results["errors"].append(f"Email failed: {task_id[:8]} -> {recipient}")

        except Exception as e:
            # Reset to pending for retry on next run
            try:
                mark_pending(task_id)  # type: ignore[misc]
            except Exception:
                pass  # Best effort reset
            log(f"ERROR: Exception sending to {recipient}: {e}")
            results["failed"] += 1
            results["errors"].append(f"Email error {task_id[:8]}: {e}")

        # Small delay between dispatches (prevents thundering herd)
        time.sleep(1.0)

    return results



# =============================================
# PLUGIN PROCESSING
# =============================================

def _load_last_run() -> dict:
    """Load plugin last-run timestamps from disk."""
    if PLUGIN_LAST_RUN_FILE.exists():
        try:
            return json.loads(PLUGIN_LAST_RUN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_last_run(data: dict) -> None:
    """Save plugin last-run timestamps to disk."""
    PLUGIN_LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLUGIN_LAST_RUN_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _is_plugin_due(config: dict, last_run_map: dict) -> bool:
    """
    Check if a plugin is due to run based on its schedule type.

    Args:
        config: Plugin PLUGIN_CONFIG dict
        last_run_map: {plugin_name: ISO_timestamp} of previous runs

    Returns:
        True if the plugin should run now
    """
    now = datetime.now()
    schedule = config["schedule"]
    name = config["name"]

    if schedule == "daily":
        # Compare HH:MM against current time (fuzzy 15-minute window)
        target_time = config.get("time", "00:00")
        target_h, target_m = map(int, target_time.split(":"))
        current_minutes = now.hour * 60 + now.minute
        target_minutes = target_h * 60 + target_m
        minutes_diff = abs(current_minutes - target_minutes)
        minutes_diff = min(minutes_diff, 1440 - minutes_diff)  # handle midnight wrap
        if minutes_diff > 15:
            return False
        # Check we haven't already run today
        last_iso = last_run_map.get(name)
        if last_iso:
            last_dt = datetime.fromisoformat(last_iso)
            if last_dt.date() == now.date():
                return False
        return True

    elif schedule == "hourly":
        # Compare MM against current minute (fuzzy 15-minute window)
        target_m = int(config.get("time", "0"))
        minutes_diff = abs(now.minute - target_m)
        minutes_diff = min(minutes_diff, 60 - minutes_diff)  # handle hour wrap
        if minutes_diff > 15:
            return False
        # Check we haven't already run this hour
        last_iso = last_run_map.get(name)
        if last_iso:
            last_dt = datetime.fromisoformat(last_iso)
            if last_dt.hour == now.hour and last_dt.date() == now.date():
                return False
        return True

    elif schedule == "interval":
        interval = config.get("interval_minutes", 60)
        last_iso = last_run_map.get(name)
        if not last_iso:
            return True  # Never run before
        last_dt = datetime.fromisoformat(last_iso)
        elapsed = (now - last_dt).total_seconds() / 60
        return elapsed >= interval

    else:
        log(f"PLUGIN: Unknown schedule type '{schedule}' for {name}")
        return False


def _next_due_str_plugin(config: dict, last_run_map: dict) -> str:
    """Calculate human-readable next due time for a plugin."""
    now = datetime.now()
    schedule = config["schedule"]
    name = config["name"]

    if schedule == "daily":
        return f"daily @ {config.get('time', '00:00')}"
    elif schedule == "hourly":
        target_m = config.get("time", "0")
        return f"hourly @ :{int(target_m):02d}"
    elif schedule == "interval":
        interval = config.get("interval_minutes", 60)
        last_iso = last_run_map.get(name)
        if last_iso:
            last_dt = datetime.fromisoformat(last_iso)
            next_dt = last_dt + timedelta(minutes=interval)
            if next_dt <= now:
                return "now"
            return next_dt.strftime("%H:%M")
        return "now"
    return "unknown"


def _next_cron_run() -> str:
    """Calculate approximate next scheduler cron run time."""
    now = datetime.now()
    if now.minute < 30:
        next_min = 30
        next_hour = now.hour
    else:
        next_min = 0
        next_hour = (now.hour + 1) % 24
    return f"{next_hour:02d}:{next_min:02d}"


def process_plugins() -> dict:
    """
    Discover and execute due plugins via wake script.

    Each plugin declares its schedule in PLUGIN_CONFIG.
    This function checks if each enabled plugin is due, then
    dispatches it by calling the wake script with the plugin's branch and prompt.

    Returns:
        Dict with keys: discovered, enabled, executed, failed, errors,
        executed_plugins (list of name->branch), skipped_plugins (list with next_due)
    """
    results = {
        "discovered": 0,
        "enabled": 0,
        "executed": 0,
        "failed": 0,
        "errors": [],
        "executed_plugins": [],
        "skipped_plugins": [],
    }

    if not PLUGINS_AVAILABLE:
        log("PLUGIN: Plugin discovery not available, skipping")
        return results

    # Discover plugins
    try:
        plugins = discover_plugins()  # type: ignore[misc]
    except Exception as e:
        log(f"PLUGIN: Discovery failed: {e}")
        results["errors"].append(f"Plugin discovery: {e}")
        return results

    results["discovered"] = len(plugins)
    log(f"PLUGIN: Discovered {len(plugins)} plugin(s)")

    # Filter enabled
    enabled = [p for p in plugins if p["config"].get("enabled", False)]
    results["enabled"] = len(enabled)

    if not enabled:
        log("PLUGIN: No enabled plugins")
        return results

    # Load last-run timestamps
    last_run_map = _load_last_run()

    # Check each plugin
    for plugin in enabled:
        config = plugin["config"]
        name = config["name"]

        if not _is_plugin_due(config, last_run_map):
            next_due = _next_due_str_plugin(config, last_run_map)
            results["skipped_plugins"].append({
                "name": name,
                "branch": config.get("branch", "?"),
                "next_due": next_due,
            })
            log(f"PLUGIN: {name} - not due, skipping")
            continue

        # Self-dispatching plugins handle their own branch targeting
        if config.get("self_dispatch") and hasattr(plugin["module"], "run"):
            log(f"PLUGIN: {name} - due, self-dispatching")
            try:
                run_result = plugin["module"].run()
                run_status = run_result.get("status", "unknown")
                if run_status in ("dispatched", "ready"):
                    target = run_result.get("branch", config.get("branch", "?"))
                    log(f"PLUGIN: {name} - self-dispatch OK -> {target}")
                    results["executed"] += 1
                    results["executed_plugins"].append({
                        "name": name,
                        "branch": target,
                    })
                    last_run_map[name] = datetime.now().isoformat()
                else:
                    error_msg = run_result.get("error", run_result.get("message", "unknown"))
                    log(f"PLUGIN: {name} - self-dispatch failed: {error_msg}")
                    results["failed"] += 1
                    results["errors"].append(f"Plugin {name} self-dispatch: {error_msg}")
            except Exception as e:
                log(f"PLUGIN: {name} - self-dispatch error: {e}")
                results["failed"] += 1
                results["errors"].append(f"Plugin {name}: {e}")
            time.sleep(1.0)
            continue

        # Check wake script availability
        if not WAKE_SCRIPT or not WAKE_SCRIPT.exists():
            log(f"PLUGIN: {name} - wake script not configured (set AIPASS_WAKE_SCRIPT)")
            results["failed"] += 1
            results["errors"].append(f"Plugin {name}: wake script not available")
            continue

        log(f"PLUGIN: {name} - due, dispatching to {config['branch']}")

        # Build wake script command
        cmd = [sys.executable, str(WAKE_SCRIPT), config["branch"]]
        if config.get("prompt"):
            cmd.append(config["prompt"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                log(f"PLUGIN: {name} - wake script dispatched OK")
                results["executed"] += 1
                results["executed_plugins"].append({
                    "name": name,
                    "branch": config.get("branch", "?"),
                })
                # Record successful run
                last_run_map[name] = datetime.now().isoformat()
            else:
                stderr_snippet = (result.stderr or "")[:200]
                log(f"PLUGIN: {name} - wake script failed (rc={result.returncode}): {stderr_snippet}")
                results["failed"] += 1
                results["errors"].append(f"Plugin {name} wake rc={result.returncode}")

        except subprocess.TimeoutExpired:
            log(f"PLUGIN: {name} - wake script timed out (30s)")
            results["failed"] += 1
            results["errors"].append(f"Plugin {name} wake timeout")
        except Exception as e:
            log(f"PLUGIN: {name} - error: {e}")
            results["failed"] += 1
            results["errors"].append(f"Plugin {name}: {e}")

        # Small delay between dispatches
        time.sleep(1.0)

    # Persist last-run timestamps
    try:
        _save_last_run(last_run_map)
    except Exception as e:
        log(f"PLUGIN: Failed to save last_run: {e}")
        results["errors"].append(f"Save last_run: {e}")

    return results

# =============================================
# ACTION REGISTRY PROCESSING (DPLAN-043)
# =============================================

def _ensure_registry() -> None:
    """Auto-migrate plugins to registry on first run if registry is empty."""
    if not ACTION_REGISTRY_AVAILABLE:
        return
    registry = load_registry()  # type: ignore[misc]
    if not registry.get("actions"):
        log("ACTION: Registry empty, auto-migrating plugins...")
        count = migrate_plugins()  # type: ignore[misc]
        log(f"ACTION: Migrated {count} plugin(s) into registry")


def _dispatch_action(action: dict) -> dict:
    """
    Dispatch a single action via wake script, self-dispatch, or email.

    For plugin-backed actions: imports the plugin module, uses self_dispatch/run()
    or dispatches via wake script.
    For schedule actions: dispatches via wake script.
    For reminder actions: sends email, then marks completed.

    Returns:
        Dict with 'status' ('ok'|'failed'|'skipped'), 'branch', and optional 'error'.
    """
    action_type = action.get("type", "schedule")
    name = action.get("name", "?")
    target = action.get("target_branch", "")

    # --- Plugin-backed actions: import plugin module for self-dispatch ---
    if action_type == "plugin" and action.get("plugin_file"):
        plugin_file = action["plugin_file"]
        try:
            module = importlib.import_module(f".plugins.{plugin_file}", package=__package__)
        except Exception as e:
            log(f"ACTION: {name} - failed to import plugin {plugin_file}: {e}")
            return {"status": "failed", "branch": target, "error": str(e)}

        # Self-dispatching plugins handle their own branch targeting
        if action.get("self_dispatch") and hasattr(module, "run"):
            log(f"ACTION: {name} - self-dispatching via plugin")
            try:
                run_result = module.run()
                run_status = run_result.get("status", "unknown")
                if run_status in ("dispatched", "ready", "skipped", "resolved", "reminded", "waiting"):
                    actual_target = run_result.get("branch", target)
                    log(f"ACTION: {name} - self-dispatch result: {run_status} -> {actual_target}")
                    return {"status": "ok", "branch": actual_target}
                else:
                    error_msg = run_result.get("error", run_result.get("message", "unknown"))
                    log(f"ACTION: {name} - self-dispatch failed: {error_msg}")
                    return {"status": "failed", "branch": target, "error": error_msg}
            except Exception as e:
                log(f"ACTION: {name} - self-dispatch error: {e}")
                return {"status": "failed", "branch": target, "error": str(e)}

        # Standard plugin: check if it has a run() that returns "ready"
        # then dispatch via wake script
        if hasattr(module, "run"):
            try:
                run_result = module.run()
                run_status = run_result.get("status", "unknown")
                if run_status not in ("ready",):
                    log(f"ACTION: {name} - plugin run() returned: {run_status}")
                    if run_status in ("resolved", "waiting"):
                        return {"status": "ok", "branch": target}
                    return {"status": "failed", "branch": target, "error": f"run() returned {run_status}"}
            except Exception as e:
                log(f"ACTION: {name} - plugin run() error: {e}")
                # Continue to wake script dispatch anyway

    # --- Reminder actions: send email ---
    if action_type == "reminder":
        if not AI_MAIL_AVAILABLE:
            log(f"ACTION: {name} - ai_mail not available for reminder")
            return {"status": "failed", "branch": target, "error": "ai_mail not available"}
        log(f"ACTION: {name} - reminder due, sending to {target}")
        try:
            email_sent = send_email_direct(
                to_branch=target,
                subject=f"[REMINDER] {name}",
                message=action.get("prompt", name),
                from_branch='@daemon',
                auto_execute=True,
                reply_to='@dev_central',
            )
            if email_sent:
                mark_reminder_completed(action["id"])  # type: ignore[misc]
                log(f"ACTION: {name} - reminder sent and completed")
                return {"status": "ok", "branch": target}
            else:
                log(f"ACTION: {name} - reminder email failed")
                return {"status": "failed", "branch": target, "error": "email send returned False"}
        except Exception as e:
            log(f"ACTION: {name} - reminder error: {e}")
            return {"status": "failed", "branch": target, "error": str(e)}

    # --- Standard dispatch via wake script ---
    if not WAKE_SCRIPT or not WAKE_SCRIPT.exists():
        log(f"ACTION: {name} - wake script not configured (set AIPASS_WAKE_SCRIPT)")
        return {"status": "failed", "branch": target, "error": "wake script not available"}

    log(f"ACTION: {name} - dispatching to {target} via wake script")

    cmd = [sys.executable, str(WAKE_SCRIPT)]
    if action.get("fresh", True):
        cmd.append("--fresh")
    cmd.append(target)
    if action.get("prompt"):
        cmd.append(action["prompt"])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log(f"ACTION: {name} - wake script dispatched OK")
            return {"status": "ok", "branch": target}
        else:
            stderr_snippet = (result.stderr or "")[:200]
            log(f"ACTION: {name} - wake script failed (rc={result.returncode}): {stderr_snippet}")
            return {"status": "failed", "branch": target, "error": f"wake rc={result.returncode}"}
    except subprocess.TimeoutExpired:
        log(f"ACTION: {name} - wake script timed out (30s)")
        return {"status": "failed", "branch": target, "error": "wake timeout"}
    except Exception as e:
        log(f"ACTION: {name} - dispatch error: {e}")
        return {"status": "failed", "branch": target, "error": str(e)}


def process_actions() -> dict:
    """
    Process all due actions from the registry.

    Reads actions_registry.json, checks each enabled action for due status,
    and dispatches via wake script, self-dispatch, or email.

    Auto-migrates plugins to registry on first run.

    Returns:
        Dict with keys: total, enabled, executed, failed, errors,
        executed_actions, skipped_actions.
    """
    results = {
        "total": 0,
        "enabled": 0,
        "executed": 0,
        "failed": 0,
        "errors": [],
        "executed_actions": [],
        "skipped_actions": [],
    }

    if not ACTION_REGISTRY_AVAILABLE:
        log("ACTION: Action registry not available, skipping")
        return results

    # Auto-migrate if registry is empty
    try:
        _ensure_registry()
    except Exception as e:
        log(f"ACTION: Migration error: {e}")
        results["errors"].append(f"Migration: {e}")

    # Load registry
    try:
        registry = load_registry()  # type: ignore[misc]
    except Exception as e:
        log(f"ACTION: Failed to load registry: {e}")
        results["errors"].append(f"Load registry: {e}")
        return results

    actions = registry.get("actions", [])
    results["total"] = len(actions)
    log(f"ACTION: Registry has {len(actions)} action(s)")

    # Filter enabled and not completed
    enabled_actions = [
        a for a in actions
        if a.get("enabled", False) and not a.get("completed")
    ]
    results["enabled"] = len(enabled_actions)

    if not enabled_actions:
        log("ACTION: No enabled actions")
        return results

    # Check each action
    for action in enabled_actions:
        action_id = action.get("id", "????")
        name = action.get("name", "?")

        if not is_action_due(action):  # type: ignore[misc]
            due_str = next_due_str(action)  # type: ignore[misc]
            results["skipped_actions"].append({
                "id": action_id,
                "name": name,
                "branch": action.get("target_branch", "?"),
                "next_due": due_str,
            })
            log(f"ACTION: {action_id} {name} - not due, next: {due_str}")
            continue

        # Dispatch the action
        dispatch_result = _dispatch_action(action)

        if dispatch_result["status"] == "ok":
            results["executed"] += 1
            results["executed_actions"].append({
                "id": action_id,
                "name": name,
                "branch": dispatch_result.get("branch", "?"),
            })
            # Update last_run in registry
            update_last_run(action_id)  # type: ignore[misc]
        else:
            results["failed"] += 1
            error_msg = dispatch_result.get("error", "unknown")
            results["errors"].append(f"Action {action_id} {name}: {error_msg}")

        # Small delay between dispatches
        time.sleep(1.0)

    return results


# =============================================
# MAIN
# =============================================

def main() -> int:
    """
    Main cron entry point.

    Returns:
        0 on success, 1 on error
    """
    args = sys.argv[1:]

    if not args:
        print_introspection()
        return 0

    if args[0] in ['--help', '-h']:
        print_help()
        sys.exit(0)

    json_handler.log_operation("cron_run")
    log("=" * 60)
    log("Scheduler cron triggered")

    # Ensure lock directory exists
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Acquire single-instance lock (non-blocking, stdlib fcntl)
    lock_fd = open(LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("Another instance already running, skipping.")
        lock_fd.close()
        return 0

    try:
        return _run_locked()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _run_locked() -> int:
    """Execute the cron job while holding the lock."""
    exit_code = 0

    # Step 1: Process due tasks
    try:
        results = process_due_tasks()
    except Exception as e:
        log(f"CRITICAL: Unhandled error in process_due_tasks: {e}")
        return 1

    # Step 2: Process actions from registry
    action_results = {
        "total": 0, "enabled": 0, "executed": 0, "failed": 0,
        "errors": [], "executed_actions": [], "skipped_actions": [],
    }
    try:
        action_results = process_actions()
    except Exception as e:
        log(f"WARNING: Unhandled error in process_actions: {e}")
        action_results["errors"].append(f"Action processing: {e}")

    # Step 3: Build summary
    lines = []

    # Tasks section
    if results["recovered"]:
        lines.append(f"Recovered {results['recovered']} stale dispatch(es)")
    if results["due"] or results["success"]:
        task_line = f"Tasks: {results['due']} due | {results['success']} sent"
        if results["failed"]:
            task_line += f" | {results['failed']} failed"
        lines.append(task_line)
    else:
        lines.append("Tasks: none due")

    # Actions section
    executed = action_results.get("executed_actions", [])
    skipped = action_results.get("skipped_actions", [])
    if executed:
        for a in executed:
            lines.append(f"  {a['id']} {a['name']} -> {a['branch']} OK")
    if skipped:
        for a in skipped:
            lines.append(f"  {a['id']} {a['name']} -> {a['branch']} (next: {a['next_due']})")
    if not executed and not skipped:
        lines.append("Actions: none enabled")
    if action_results["failed"]:
        lines.append(f"Action failures: {action_results['failed']}")

    # Next run
    lines.append(f"Next: ~{_next_cron_run()}")

    summary = "\n".join(lines)

    log(f"Results: {summary}")

    # Step 4: Determine exit code
    if results["failed"] > 0 or results["errors"] or action_results["failed"] > 0 or action_results["errors"]:
        exit_code = 1

    log("Scheduler cron finished")
    log("=" * 60)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Last-resort catch -- never crash silently
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"[{timestamp}] FATAL: Unhandled exception: {e}")
        sys.exit(1)
