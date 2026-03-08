
# ===================AIPASS====================
# META DATA HEADER
# Name: actions_registry.py - Numbered Action Registry
# Date: 2026-03-02
# Version: 1.0.0
# Category: daemon/handlers/actions
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-02): Initial creation - DPLAN-043
#     * Sequential 4-digit IDs (0001-9999)
#     * JSON storage with CRUD operations
#     * Plugin auto-migration from PLUGIN_CONFIG
#     * Due-checking logic for all schedule types
#     * Supports: plugin, schedule, reminder action types
#
# CODE STANDARDS:
#   - Handler independence: pure business logic
#   - No Rich console (headless compatible)
# =============================================

"""
Numbered Action Registry — DPLAN-043

Central registry for all scheduled actions. Each action gets a sequential
numeric ID (0001, 0002, ...) and can be individually toggled on/off.

Replaces the old all-or-nothing daemon + kill switch model with granular
per-action control.

Action types:
  - plugin: Backed by a plugin file in apps/plugins/ (migrated from existing system)
  - schedule: Custom recurring action (dispatches via wake.py)
  - reminder: One-shot action that auto-completes after firing
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Paths
_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
REGISTRY_FILE = _DAEMON_ROOT / "daemon_json" / "actions_registry.json"
PLUGINS_DIR = _DAEMON_ROOT / "apps" / "plugins"

def _empty_registry() -> dict:
    """Return a fresh empty registry structure (avoids shared mutable state)."""
    return {"version": 1, "next_id": 1, "actions": []}

# =============================================
# STORAGE
# =============================================

def load_registry() -> dict:
    """Load the actions registry from disk. Returns empty registry if missing."""
    if not REGISTRY_FILE.exists():
        return _empty_registry().copy()
    try:
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if "actions" not in data:
            data["actions"] = []
        if "next_id" not in data:
            data["next_id"] = 1
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[actions_registry] Failed to load: %s", e)
        return _empty_registry().copy()


def save_registry(data: dict) -> bool:
    """Save the actions registry to disk. Returns True on success."""
    try:
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        logger.error("[actions_registry] Failed to save: %s", e)
        return False


# =============================================
# ID GENERATION
# =============================================

def _get_next_id(registry: dict) -> str:
    """Get next sequential ID as 4-digit string. Advances next_id."""
    next_num = registry.get("next_id", 1)
    action_id = f"{next_num:04d}"
    registry["next_id"] = next_num + 1
    return action_id


# =============================================
# CRUD OPERATIONS
# =============================================

def create_action(
    name: str,
    action_type: str,
    schedule_type: str,
    target_branch: str = "",
    prompt: str = "",
    time: Optional[str] = None,
    interval_minutes: Optional[int] = None,
    due_date: Optional[str] = None,
    fresh: bool = True,
    max_turns: int = 50,
    enabled: bool = True,
    self_dispatch: bool = False,
    plugin_file: Optional[str] = None,
) -> dict:
    """
    Create a new action and save to registry.

    Args:
        name: Human-readable action name (e.g., "daily_audit")
        action_type: "plugin" | "schedule" | "reminder"
        schedule_type: "daily" | "hourly" | "interval" | "once"
        target_branch: Target branch email (e.g., "@seed")
        prompt: What the dispatched agent should do
        time: For daily: "HH:MM", for hourly: "MM"
        interval_minutes: For interval schedule type
        due_date: For reminder (once) type, ISO date string
        fresh: Start fresh session (True) or resume (False)
        max_turns: Max agent turns
        enabled: Active by default
        self_dispatch: Plugin handles its own dispatch
        plugin_file: Plugin filename (without .py) for plugin-backed actions

    Returns:
        The created action dict
    """
    registry = load_registry()
    action_id = _get_next_id(registry)

    action = {
        "id": action_id,
        "name": name,
        "type": action_type,
        "schedule_type": schedule_type,
        "time": time,
        "interval_minutes": interval_minutes,
        "due_date": due_date,
        "target_branch": target_branch,
        "prompt": prompt,
        "fresh": fresh,
        "max_turns": max_turns,
        "enabled": enabled,
        "self_dispatch": self_dispatch,
        "plugin_file": plugin_file,
        "last_run": None,
        "next_run": None,
        "created": datetime.now().isoformat(),
        "completed": None,
    }

    registry["actions"].append(action)
    save_registry(registry)

    logger.info("[actions_registry] Created action %s: %s (%s)", action_id, name, action_type)
    return action


def get_action(action_id: str) -> Optional[dict]:
    """Get a single action by ID. Returns None if not found."""
    registry = load_registry()
    for action in registry["actions"]:
        if action["id"] == action_id:
            return action
    return None


def list_actions(include_completed: bool = False) -> list:
    """
    List all actions.

    Args:
        include_completed: If True, include completed reminders.

    Returns:
        List of action dicts.
    """
    registry = load_registry()
    actions = registry["actions"]
    if not include_completed:
        actions = [a for a in actions if a.get("completed") is None]
    return actions


def toggle_action(action_id: str, enabled: bool) -> bool:
    """Toggle an action on or off. Returns True if found and updated."""
    registry = load_registry()
    for action in registry["actions"]:
        if action["id"] == action_id:
            action["enabled"] = enabled
            save_registry(registry)
            state = "enabled" if enabled else "disabled"
            logger.info("[actions_registry] Action %s %s: %s", action_id, state, action["name"])
            return True
    return False


def delete_action(action_id: str) -> bool:
    """Delete an action by ID. Returns True if found and removed."""
    registry = load_registry()
    original_len = len(registry["actions"])
    registry["actions"] = [a for a in registry["actions"] if a["id"] != action_id]
    if len(registry["actions"]) < original_len:
        save_registry(registry)
        logger.info("[actions_registry] Deleted action %s", action_id)
        return True
    return False


def update_last_run(action_id: str, timestamp: Optional[str] = None) -> bool:
    """Update last_run timestamp for an action. Returns True if found."""
    if timestamp is None:
        timestamp = datetime.now().isoformat()
    registry = load_registry()
    for action in registry["actions"]:
        if action["id"] == action_id:
            action["last_run"] = timestamp
            action["next_run"] = calc_next_run(action)
            save_registry(registry)
            return True
    return False


def mark_reminder_completed(action_id: str) -> bool:
    """Mark a reminder as completed (one-shot). Returns True if found."""
    registry = load_registry()
    for action in registry["actions"]:
        if action["id"] == action_id:
            action["completed"] = datetime.now().isoformat()
            action["enabled"] = False
            save_registry(registry)
            logger.info("[actions_registry] Reminder %s completed: %s", action_id, action["name"])
            return True
    return False


# =============================================
# DUE CHECKING
# =============================================

def is_action_due(action: dict) -> bool:
    """
    Check if an action should run now.

    For daily: matches current hour:minute, hasn't run today
    For hourly: matches current minute, hasn't run this hour
    For interval: enough time has elapsed since last run
    For once (reminder): due_date <= today, not completed
    """
    if not action.get("enabled", False):
        return False

    if action.get("completed"):
        return False

    now = datetime.now()
    schedule_type = action.get("schedule_type", "")

    if schedule_type == "daily":
        target_time = action.get("time", "00:00")
        try:
            target_h, target_m = map(int, target_time.split(":"))
        except (ValueError, AttributeError):
            return False
        if now.hour != target_h or now.minute != target_m:
            return False
        last_run = action.get("last_run")
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                if last_dt.date() == now.date():
                    return False
            except (ValueError, TypeError):
                pass
        return True

    elif schedule_type == "hourly":
        target_m_str = action.get("time", "0")
        try:
            target_m = int(target_m_str)
        except (ValueError, TypeError):
            return False
        if now.minute != target_m:
            return False
        last_run = action.get("last_run")
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                if last_dt.hour == now.hour and last_dt.date() == now.date():
                    return False
            except (ValueError, TypeError):
                pass
        return True

    elif schedule_type == "interval":
        interval = action.get("interval_minutes", 60)
        last_run = action.get("last_run")
        if not last_run:
            return True
        try:
            last_dt = datetime.fromisoformat(last_run)
            elapsed = (now - last_dt).total_seconds() / 60
            return elapsed >= interval
        except (ValueError, TypeError):
            return True

    elif schedule_type == "once":
        due_date = action.get("due_date")
        if not due_date:
            return False
        try:
            due_dt = datetime.fromisoformat(due_date).date() if "T" in due_date else datetime.strptime(due_date, "%Y-%m-%d").date()
            return now.date() >= due_dt
        except (ValueError, TypeError):
            return False

    return False


def calc_next_run(action: dict) -> Optional[str]:
    """Calculate the next run time for an action. Returns ISO string or None."""
    now = datetime.now()
    schedule_type = action.get("schedule_type", "")

    if schedule_type == "daily":
        target_time = action.get("time", "00:00")
        try:
            target_h, target_m = map(int, target_time.split(":"))
        except (ValueError, AttributeError):
            return None
        next_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(days=1)
        return next_dt.isoformat()

    elif schedule_type == "hourly":
        target_m_str = action.get("time", "0")
        try:
            target_m = int(target_m_str)
        except (ValueError, TypeError):
            return None
        next_dt = now.replace(minute=target_m, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(hours=1)
        return next_dt.isoformat()

    elif schedule_type == "interval":
        interval = action.get("interval_minutes", 60)
        last_run = action.get("last_run")
        if not last_run:
            return now.isoformat()
        try:
            last_dt = datetime.fromisoformat(last_run)
            return (last_dt + timedelta(minutes=interval)).isoformat()
        except (ValueError, TypeError):
            return now.isoformat()

    elif schedule_type == "once":
        due_date = action.get("due_date")
        if due_date and not action.get("completed"):
            return due_date
        return None

    return None


def next_due_str(action: dict) -> str:
    """Human-readable next due string for display."""
    schedule_type = action.get("schedule_type", "")

    if schedule_type == "daily":
        return f"daily @ {action.get('time', '00:00')}"
    elif schedule_type == "hourly":
        m = action.get("time", "0")
        return f"hourly @ :{int(m):02d}"
    elif schedule_type == "interval":
        interval = action.get("interval_minutes", 60)
        last_run = action.get("last_run")
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                next_dt = last_dt + timedelta(minutes=interval)
                if next_dt <= datetime.now():
                    return "now"
                return next_dt.strftime("%H:%M")
            except (ValueError, TypeError):
                return "now"
        return "now"
    elif schedule_type == "once":
        return action.get("due_date", "unknown")

    return "unknown"


# =============================================
# PLUGIN MIGRATION
# =============================================

def migrate_plugins() -> int:
    """
    Scan plugins/ directory and auto-register any plugins not yet in the registry.

    Maps PLUGIN_CONFIG fields to action fields. Preserves last_run timestamps
    from .last_run.json.

    Returns:
        Number of newly migrated plugins.
    """
    registry = load_registry()
    existing_plugins = {
        a["plugin_file"]
        for a in registry["actions"]
        if a.get("plugin_file")
    }

    # Load last_run data for timestamp preservation
    last_run_file = PLUGINS_DIR / ".last_run.json"
    last_run_map = {}
    if last_run_file.exists():
        try:
            last_run_map = json.loads(last_run_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Discover plugins
    migrated = 0
    for plugin_path in sorted(PLUGINS_DIR.glob("*.py")):
        if plugin_path.name.startswith("_"):
            continue

        plugin_name = plugin_path.stem
        if plugin_name in existing_plugins:
            continue

        # Import plugin to read PLUGIN_CONFIG
        try:
            import importlib
            # Use absolute package path for plugin import
            spec_name = f"aipass.daemon.apps.plugins.{plugin_name}"
            module = importlib.import_module(spec_name)

            if not hasattr(module, 'PLUGIN_CONFIG'):
                continue

            config = module.PLUGIN_CONFIG
        except Exception as e:
            logger.warning("[actions_registry] Failed to import plugin %s: %s", plugin_name, e)
            continue

        # Map PLUGIN_CONFIG to action fields
        action_id = _get_next_id(registry)
        action = {
            "id": action_id,
            "name": config.get("name", plugin_name),
            "type": "plugin",
            "schedule_type": config.get("schedule", "interval"),
            "time": config.get("time"),
            "interval_minutes": config.get("interval_minutes"),
            "due_date": None,
            "target_branch": config.get("branch", ""),
            "prompt": config.get("prompt", ""),
            "fresh": config.get("fresh", True),
            "max_turns": config.get("max_turns", 50),
            "enabled": config.get("enabled", False),
            "self_dispatch": config.get("self_dispatch", False),
            "plugin_file": plugin_name,
            "last_run": last_run_map.get(config.get("name", plugin_name)),
            "next_run": None,
            "created": datetime.now().isoformat(),
            "completed": None,
        }

        # Calculate next_run from last_run
        action["next_run"] = calc_next_run(action)

        registry["actions"].append(action)
        migrated += 1
        logger.info("[actions_registry] Migrated plugin: %s -> action %s", plugin_name, action_id)

    if migrated > 0:
        save_registry(registry)
        logger.info("[actions_registry] Migration complete: %d plugin(s) migrated", migrated)

    return migrated
