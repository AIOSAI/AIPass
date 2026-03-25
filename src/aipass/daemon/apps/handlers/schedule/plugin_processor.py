# =================== AIPass ====================
# Name: plugin_processor.py
# Description: Plugin scheduling and dispatch processor
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Plugin scheduling and dispatch processor.

Extracted from scheduler_cron.py to separate plugin processing concerns
from the main cron orchestration logic. Handles plugin discovery,
schedule evaluation, and dispatch via wake script or self-dispatch.
"""

# =============================================
# IMPORTS
# =============================================

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.daemon.apps.handlers.json import json_handler

# =============================================
# OPTIONAL IMPORTS
# =============================================

try:
    from aipass.daemon.apps.plugins import discover_plugins
    PLUGINS_AVAILABLE = True
except ImportError as e:
    logger.info(f"Optional dependency not available: discover_plugins ({e})")
    PLUGINS_AVAILABLE = False
    discover_plugins = None

# =============================================
# CONSTANTS
# =============================================

WAKE_SCRIPT = Path(os.environ.get('AIPASS_WAKE_SCRIPT', ''))

_APPS_DIR = Path(__file__).resolve().parents[2]  # apps/handlers/schedule -> apps/
PLUGIN_LAST_RUN_FILE = _APPS_DIR / "plugins" / ".last_run.json"

# =============================================
# LAST-RUN PERSISTENCE
# =============================================


def _load_last_run() -> dict:
    """Load plugin last-run timestamps from disk."""
    if PLUGIN_LAST_RUN_FILE.exists():
        try:
            return json.loads(PLUGIN_LAST_RUN_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load plugin last-run file, using empty defaults: {e}")
            return {}
    return {}


def _save_last_run(data: dict) -> None:
    """Save plugin last-run timestamps to disk."""
    PLUGIN_LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLUGIN_LAST_RUN_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding='utf-8')


# =============================================
# SCHEDULE EVALUATION
# =============================================


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
        logger.info(f"PLUGIN: Unknown schedule type '{schedule}' for {name}")
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


# =============================================
# PLUGIN PROCESSING
# =============================================


def process_plugins(log_fn: Callable[[str], None] | None = None) -> Dict[str, Any]:
    """
    Discover and execute due plugins via wake script.

    Each plugin declares its schedule in PLUGIN_CONFIG.
    This function checks if each enabled plugin is due, then
    dispatches it by calling the wake script with the plugin's branch and prompt.

    Args:
        log_fn: Optional callable for log output. Falls back to logger.info
                if not provided.

    Returns:
        Dict with keys: discovered, enabled, executed, failed, errors,
        executed_plugins (list of name->branch), skipped_plugins (list with next_due)
    """
    json_handler.log_operation("process_plugins")

    if log_fn is None:
        log_fn = logger.info

    results: Dict[str, Any] = {
        "discovered": 0,
        "enabled": 0,
        "executed": 0,
        "failed": 0,
        "errors": [],
        "executed_plugins": [],
        "skipped_plugins": [],
    }

    if not PLUGINS_AVAILABLE:
        log_fn("PLUGIN: Plugin discovery not available, skipping")
        return results

    # Discover plugins
    try:
        plugins = discover_plugins()  # type: ignore[misc]
    except Exception as e:
        logger.error(f"Plugin discovery failed: {e}")
        log_fn(f"PLUGIN: Discovery failed: {e}")
        results["errors"].append(f"Plugin discovery: {e}")
        return results

    results["discovered"] = len(plugins)
    log_fn(f"PLUGIN: Discovered {len(plugins)} plugin(s)")

    # Filter enabled
    enabled = [p for p in plugins if p["config"].get("enabled", False)]
    results["enabled"] = len(enabled)

    if not enabled:
        log_fn("PLUGIN: No enabled plugins")
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
            log_fn(f"PLUGIN: {name} - not due, skipping")
            continue

        # Self-dispatching plugins handle their own branch targeting
        if config.get("self_dispatch") and hasattr(plugin["module"], "run"):
            log_fn(f"PLUGIN: {name} - due, self-dispatching")
            try:
                run_result = plugin["module"].run()
                run_status = run_result.get("status", "unknown")
                if run_status in ("dispatched", "ready"):
                    target = run_result.get("branch", config.get("branch", "?"))
                    log_fn(f"PLUGIN: {name} - self-dispatch OK -> {target}")
                    results["executed"] += 1
                    results["executed_plugins"].append({
                        "name": name,
                        "branch": target,
                    })
                    last_run_map[name] = datetime.now().isoformat()
                else:
                    error_msg = run_result.get("error", run_result.get("message", "unknown"))
                    log_fn(f"PLUGIN: {name} - self-dispatch failed: {error_msg}")
                    results["failed"] += 1
                    results["errors"].append(f"Plugin {name} self-dispatch: {error_msg}")
            except Exception as e:
                logger.error(f"Plugin {name} self-dispatch error: {e}")
                log_fn(f"PLUGIN: {name} - self-dispatch error: {e}")
                results["failed"] += 1
                results["errors"].append(f"Plugin {name}: {e}")
            time.sleep(1.0)
            continue

        # Check wake script availability
        if not WAKE_SCRIPT or not WAKE_SCRIPT.exists():
            log_fn(f"PLUGIN: {name} - wake script not configured (set AIPASS_WAKE_SCRIPT)")
            results["failed"] += 1
            results["errors"].append(f"Plugin {name}: wake script not available")
            continue

        log_fn(f"PLUGIN: {name} - due, dispatching to {config['branch']}")

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
                log_fn(f"PLUGIN: {name} - wake script dispatched OK")
                results["executed"] += 1
                results["executed_plugins"].append({
                    "name": name,
                    "branch": config.get("branch", "?"),
                })
                # Record successful run
                last_run_map[name] = datetime.now().isoformat()
            else:
                stderr_snippet = (result.stderr or "")[:200]
                log_fn(f"PLUGIN: {name} - wake script failed (rc={result.returncode}): {stderr_snippet}")
                results["failed"] += 1
                results["errors"].append(f"Plugin {name} wake rc={result.returncode}")

        except subprocess.TimeoutExpired:
            logger.warning(f"Plugin {name} wake script timed out (30s)")
            log_fn(f"PLUGIN: {name} - wake script timed out (30s)")
            results["failed"] += 1
            results["errors"].append(f"Plugin {name} wake timeout")
        except Exception as e:
            logger.error(f"Plugin {name} error: {e}")
            log_fn(f"PLUGIN: {name} - error: {e}")
            results["failed"] += 1
            results["errors"].append(f"Plugin {name}: {e}")

        # Small delay between dispatches
        time.sleep(1.0)

    # Persist last-run timestamps
    try:
        _save_last_run(last_run_map)
    except Exception as e:
        logger.warning(f"Failed to save plugin last_run timestamps: {e}")
        log_fn(f"PLUGIN: Failed to save last_run: {e}")
        results["errors"].append(f"Save last_run: {e}")

    return results
