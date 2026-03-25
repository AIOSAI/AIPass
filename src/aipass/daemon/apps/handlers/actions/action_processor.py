# =================== AIPass ====================
# Name: action_processor.py
# Description: Action registry scheduling and dispatch processor
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Action registry scheduling and dispatch processor.

Extracted from scheduler_cron.py to decouple action processing from the
main scheduler loop. All three public functions accept injectable log_fn
and send_email_fn callables so the module can be driven from any caller
without hard-wiring daemon-specific helpers.
"""

import sys
import time
import importlib
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import os

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.daemon.apps.handlers.json import json_handler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WAKE_SCRIPT = Path(os.environ.get('AIPASS_WAKE_SCRIPT', ''))

AI_MAIL_AVAILABLE = True

# ---------------------------------------------------------------------------
# Optional scheduler_ops imports (action registry helpers)
# ---------------------------------------------------------------------------

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
except ImportError as e:
    logger.info(f"Optional dependency not available: scheduler_ops action registry ({e})")
    ACTION_REGISTRY_AVAILABLE = False
    load_registry = None
    is_action_due = None
    update_last_run = None
    mark_reminder_completed = None
    migrate_plugins = None
    next_due_str = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(msg: str, log_fn: Callable | None = None) -> None:
    """Route a message through the caller-supplied log function or logger.info."""
    if log_fn is not None:
        log_fn(msg)
    else:
        logger.info(msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _ensure_registry(log_fn: Callable | None = None) -> None:
    """Auto-migrate plugins to registry on first run if registry is empty."""
    if not ACTION_REGISTRY_AVAILABLE:
        return
    assert load_registry is not None
    assert migrate_plugins is not None
    registry = load_registry()
    if not registry.get("actions"):
        _log("ACTION: Registry empty, auto-migrating plugins...", log_fn)
        count = migrate_plugins()
        _log(f"ACTION: Migrated {count} plugin(s) into registry", log_fn)


def _dispatch_action(
    action: dict,
    log_fn: Callable | None = None,
    send_email_fn: Callable | None = None,
) -> dict:
    """
    Dispatch a single action based on its type (plugin / reminder / schedule).

    Returns a dict with at least ``{"status": "ok"|"failed", "branch": ...}``.
    """
    action_type = action.get("type", "schedule")
    name = action.get("name", "?")
    target = action.get("target_branch", "")

    # ---- plugin actions ----
    if action_type == "plugin" and action.get("plugin_file"):
        plugin_file = action["plugin_file"]
        try:
            module = importlib.import_module(f"aipass.daemon.apps.plugins.{plugin_file}")
        except Exception as e:
            logger.error(f"Action {name} failed to import plugin {plugin_file}: {e}")
            _log(f"ACTION: {name} - failed to import plugin {plugin_file}: {e}", log_fn)
            return {"status": "failed", "branch": target, "error": str(e)}

        # Self-dispatching plugins
        if action.get("self_dispatch") and hasattr(module, "run"):
            _log(f"ACTION: {name} - self-dispatching via plugin", log_fn)
            try:
                run_result = module.run()
                run_status = run_result.get("status", "unknown")
                if run_status in (
                    "dispatched", "ready", "skipped",
                    "resolved", "reminded", "waiting",
                ):
                    actual_target = run_result.get("branch", target)
                    _log(
                        f"ACTION: {name} - self-dispatch result: {run_status} -> {actual_target}",
                        log_fn,
                    )
                    return {"status": "ok", "branch": actual_target}
                else:
                    error_msg = run_result.get("error", run_result.get("message", "unknown"))
                    _log(f"ACTION: {name} - self-dispatch failed: {error_msg}", log_fn)
                    return {"status": "failed", "branch": target, "error": error_msg}
            except Exception as e:
                logger.error(f"Action {name} self-dispatch error: {e}")
                _log(f"ACTION: {name} - self-dispatch error: {e}", log_fn)
                return {"status": "failed", "branch": target, "error": str(e)}

        # Normal plugin run()
        if hasattr(module, "run"):
            try:
                run_result = module.run()
                run_status = run_result.get("status", "unknown")
                if run_status not in ("ready",):
                    _log(f"ACTION: {name} - plugin run() returned: {run_status}", log_fn)
                    if run_status in ("resolved", "waiting"):
                        return {"status": "ok", "branch": target}
                    return {
                        "status": "failed",
                        "branch": target,
                        "error": f"run() returned {run_status}",
                    }
            except Exception as e:
                logger.warning(f"Action {name} plugin run() error: {e}")
                _log(f"ACTION: {name} - plugin run() error: {e}", log_fn)

    # ---- reminder actions ----
    if action_type == "reminder":
        if not AI_MAIL_AVAILABLE:
            _log(f"ACTION: {name} - ai_mail not available for reminder", log_fn)
            return {"status": "failed", "branch": target, "error": "ai_mail not available"}

        if send_email_fn is None:
            _log(f"ACTION: {name} - email not configured for reminder", log_fn)
            return {"status": "failed", "branch": target, "error": "email not configured"}

        _log(f"ACTION: {name} - reminder due, sending to {target}", log_fn)
        try:
            email_sent = send_email_fn(
                to_branch=target,
                subject=f"[REMINDER] {name}",
                message=action.get("prompt", name),
                from_branch='@daemon',
                auto_execute=True,
                reply_to='@dev_central',
            )
            if email_sent:
                assert mark_reminder_completed is not None
                mark_reminder_completed(action["id"])
                _log(f"ACTION: {name} - reminder sent and completed", log_fn)
                return {"status": "ok", "branch": target}
            else:
                _log(f"ACTION: {name} - reminder email failed", log_fn)
                return {
                    "status": "failed",
                    "branch": target,
                    "error": "email send returned False",
                }
        except Exception as e:
            logger.error(f"Action {name} reminder error: {e}")
            _log(f"ACTION: {name} - reminder error: {e}", log_fn)
            return {"status": "failed", "branch": target, "error": str(e)}

    # ---- schedule (wake-script) actions ----
    if not WAKE_SCRIPT or not WAKE_SCRIPT.exists():
        _log(
            f"ACTION: {name} - wake script not configured (set AIPASS_WAKE_SCRIPT)",
            log_fn,
        )
        return {"status": "failed", "branch": target, "error": "wake script not available"}

    _log(f"ACTION: {name} - dispatching to {target} via wake script", log_fn)

    cmd = [sys.executable, str(WAKE_SCRIPT)]
    if action.get("fresh", True):
        cmd.append("--fresh")
    cmd.append(target)
    if action.get("prompt"):
        cmd.append(action["prompt"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            _log(f"ACTION: {name} - wake script dispatched OK", log_fn)
            return {"status": "ok", "branch": target}
        else:
            stderr_snippet = (result.stderr or "")[:200]
            _log(
                f"ACTION: {name} - wake script failed (rc={result.returncode}): {stderr_snippet}",
                log_fn,
            )
            return {
                "status": "failed",
                "branch": target,
                "error": f"wake rc={result.returncode}",
            }
    except subprocess.TimeoutExpired:
        logger.warning(f"Action {name} wake script timed out (30s)")
        _log(f"ACTION: {name} - wake script timed out (30s)", log_fn)
        return {"status": "failed", "branch": target, "error": "wake timeout"}
    except Exception as e:
        logger.error(f"Action {name} dispatch error: {e}")
        _log(f"ACTION: {name} - dispatch error: {e}", log_fn)
        return {"status": "failed", "branch": target, "error": str(e)}


def process_actions(
    log_fn: Callable | None = None,
    send_email_fn: Callable | None = None,
) -> Dict[str, Any]:
    """
    Walk the action registry, dispatch every enabled-and-due action.

    Returns a summary dict with counts, errors, and per-action details.
    """
    results: Dict[str, Any] = {
        "total": 0,
        "enabled": 0,
        "executed": 0,
        "failed": 0,
        "errors": [],
        "executed_actions": [],
        "skipped_actions": [],
    }

    json_handler.log_operation("process_actions")

    if not ACTION_REGISTRY_AVAILABLE:
        _log("ACTION: Action registry not available, skipping", log_fn)
        return results

    assert load_registry is not None
    assert is_action_due is not None
    assert next_due_str is not None
    assert update_last_run is not None

    # --- ensure registry is populated ---
    try:
        _ensure_registry(log_fn)
    except Exception as e:
        logger.warning(f"Action registry migration error: {e}")
        _log(f"ACTION: Migration error: {e}", log_fn)
        results["errors"].append(f"Migration: {e}")

    # --- load registry ---
    try:
        registry = load_registry()
    except Exception as e:
        logger.error(f"Failed to load action registry: {e}")
        _log(f"ACTION: Failed to load registry: {e}", log_fn)
        results["errors"].append(f"Load registry: {e}")
        return results

    actions = registry.get("actions", [])
    results["total"] = len(actions)
    _log(f"ACTION: Registry has {len(actions)} action(s)", log_fn)

    enabled_actions = [
        a for a in actions
        if a.get("enabled", False) and not a.get("completed")
    ]
    results["enabled"] = len(enabled_actions)

    if not enabled_actions:
        _log("ACTION: No enabled actions", log_fn)
        return results

    # --- dispatch loop ---
    for action in enabled_actions:
        action_id = action.get("id", "????")
        name = action.get("name", "?")

        if not is_action_due(action):
            due_str = next_due_str(action)
            results["skipped_actions"].append({
                "id": action_id,
                "name": name,
                "branch": action.get("target_branch", "?"),
                "next_due": due_str,
            })
            _log(f"ACTION: {action_id} {name} - not due, next: {due_str}", log_fn)
            continue

        dispatch_result = _dispatch_action(action, log_fn, send_email_fn)

        if dispatch_result["status"] == "ok":
            results["executed"] += 1
            results["executed_actions"].append({
                "id": action_id,
                "name": name,
                "branch": dispatch_result.get("branch", "?"),
            })
            update_last_run(action_id)
        else:
            results["failed"] += 1
            error_msg = dispatch_result.get("error", "unknown")
            results["errors"].append(f"Action {action_id} {name}: {error_msg}")

        time.sleep(1.0)

    return results
