# =================== AIPass ====================
# Name: community_rotation.py
# Description: Rotating Community Engagement Plugin
# Version: 1.1.0
# Created: 2026-02-21
# Modified: 2026-02-22
# =============================================

"""
Rotating Community Engagement Plugin

Wakes one branch per rotation on a rotating schedule to:
1. Process email inbox (view, reply, close stale emails)
2. Check dashboard for Commons notifications (mentions, comments, votes)
3. Act on any pending notifications
4. Browse The Commons feed and engage if something catches their eye

Rotates through all eligible branches from BRANCH_REGISTRY,
excluding VERA (has her own heartbeat), DEV_CENTRAL (human),
DAEMON (self), and non-agent directories.

Full rotation every ~14 hours, then loops.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from aipass.prax import logger
# logger imported from aipass.prax

# Paths
REGISTRY_PATH = Path(os.environ.get('AIPASS_REGISTRY', Path.home() / '.aipass' / 'AIPASS_REGISTRY.json'))
ROTATION_STATE_FILE = Path(__file__).parent / ".rotation_state.json"
ACTIVITY_TRACKER_FILE = Path(__file__).parent / ".activity_tracker.json"

# Wake script path (configurable via env var)
WAKE_SCRIPT = Path(os.environ.get('AIPASS_WAKE_SCRIPT', ''))

# Inactivity threshold -- consecutive zero-activity passes before alerting
INACTIVITY_THRESHOLD = 10

# Branches to EXCLUDE from rotation
# Every branch is a citizen -- the Commons gives them life.
# Only exclude branches that can't or shouldn't be auto-woken.
EXCLUDED_BRANCHES = {
    "VERA",            # Already checks Commons via her own heartbeat plugin
    "DEV_CENTRAL",     # Human workspace -- can't be auto-woken (needs Patrick)
    # "PATRICK_PRIVATE",  # Commented out — CLI registry handles branch locking now. May return.
}

# Engagement prompt -- what each branch does when woken
ENGAGEMENT_PROMPT = (
    "Routine check-in -- like checking your phone for notifications.\n"
    "Read your DASHBOARD.local.json FIRST. It's your lock screen.\n"
    "Only open the apps that have activity. Zero notifications = don't bother opening it.\n\n"
    "STEP 1: Read DASHBOARD.local.json\n"
    "  - Check mail_summary -> new or opened emails?\n"
    "  - Check commons_activity -> mentions, comments, votes, new posts pending?\n"
    "  - If BOTH are zero, you're done. No action = no memory needed. Stop here.\n\n"
    "STEP 2 -- EMAIL (only if dashboard shows mail activity):\n"
    "  - Run: ai_mail inbox\n"
    "  - View each email: ai_mail view <id>\n"
    "  - Reply if needed: ai_mail reply <id> \"message\"\n"
    "  - Close stale/informational emails: ai_mail close <id>\n"
    "  - Goal: inbox empty or only emails awaiting external action\n"
    "  - If inbox has >20 messages, close stale/outdated ones first\n\n"
    "STEP 3 -- THE COMMONS (only if dashboard shows commons activity):\n"
    "  - If you have pending notifications: run drone commons catchup\n"
    "  - Respond to mentions, reply to comments, check posts about you\n"
    "  - If you feel like browsing or posting something new, go ahead:\n"
    "    drone commons feed\n"
    "    drone commons comment <post_id> \"Your response\"\n"
    "    drone commons vote <post_id> up\n"
    "    drone commons post \"room\" \"Title\" \"Content\"\n"
    "  - If nothing interests you, that's fine -- don't force it.\n\n"
    "STEP 4 -- MEMORIES (only if you actually DID something in steps 2-3):\n"
    "  - Update your [BRANCH].local.json with a light note of what you did.\n"
    "  - Emails processed, replies sent, Commons posts/comments made.\n"
    "  - If you don't log it, you won't remember it next time.\n"
    "  - If dashboard was all zeros and you did nothing, skip this. No noise.\n\n"
    "This is a routine check-in, not a work session. Be efficient."
)


def _load_eligible_branches() -> list:
    """Load and filter branches from BRANCH_REGISTRY."""
    if not REGISTRY_PATH.exists():
        logger.error("[community_rotation] BRANCH_REGISTRY not found at %s", REGISTRY_PATH)
        return []
    try:
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            registry = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[community_rotation] Failed to read registry: %s", e)
        return []

    branches = []
    for branch in registry.get("branches", []):
        name = branch.get("name", "")
        email = branch.get("email", "")
        status = branch.get("status", "")
        if name in EXCLUDED_BRANCHES:
            continue
        if status != "active":
            continue
        if not email:
            continue
        branches.append({"name": name, "email": email, "path": branch.get("path", "")})

    # Sort by name for consistent rotation order
    branches.sort(key=lambda b: b["name"])
    return branches


def _load_rotation_state() -> int:
    """Load the current rotation index from state file."""
    if not ROTATION_STATE_FILE.exists():
        return -1  # Start at -1 so first run targets index 0
    try:
        with open(ROTATION_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("last_index", -1)
    except (json.JSONDecodeError, OSError):
        return -1


def _save_rotation_state(index: int, branch_name: str) -> None:
    """Save the rotation index to state file."""
    data = {
        "last_index": index,
        "last_branch": branch_name,
        "last_run": datetime.now().isoformat(),
    }
    try:
        with open(ROTATION_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    except OSError as e:
        logger.warning("[community_rotation] Failed to save state: %s", e)


def _check_dashboard_activity(branch_path: str) -> dict:
    """
    Read a branch's DASHBOARD.local.json and check for pending activity.

    Returns dict with activity flags and counts. If dashboard is missing
    or unreadable, returns has_activity=True to avoid silently skipping
    broken branches.
    """
    default_active = {
        "has_activity": True,
        "mail_new": 0,
        "mail_opened": 0,
        "commons_mentions": 0,
        "commons_comments": 0,
        "commons_posts": 0,
    }

    dashboard_path = Path(branch_path) / "DASHBOARD.local.json"
    if not dashboard_path.exists():
        logger.warning("[community_rotation] Dashboard missing: %s", dashboard_path)
        return default_active

    try:
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[community_rotation] Dashboard unreadable: %s - %s", dashboard_path, e)
        return default_active

    # Extract mail counts from quick_status
    quick = data.get("quick_status", {})
    mail_new = quick.get("new_mail", 0) or 0
    mail_opened = quick.get("opened_mail", 0) or 0

    # Extract commons counts from sections
    sections = data.get("sections", {})
    commons = sections.get("commons_activity", {})
    commons_mentions = commons.get("mentions", 0) or 0
    commons_comments = commons.get("new_comments_since_last_visit", 0) or 0
    commons_posts = commons.get("new_posts_since_last_visit", 0) or 0

    has_activity = any([
        mail_new > 0,
        mail_opened > 0,
        commons_mentions > 0,
        commons_comments > 0,
        commons_posts > 0,
    ])

    return {
        "has_activity": has_activity,
        "mail_new": mail_new,
        "mail_opened": mail_opened,
        "commons_mentions": commons_mentions,
        "commons_comments": commons_comments,
        "commons_posts": commons_posts,
    }


def _load_activity_tracker() -> dict:
    """Load the activity tracker state file. Returns empty structure if missing."""
    if not ACTIVITY_TRACKER_FILE.exists():
        return {"branches": {}}
    try:
        with open(ACTIVITY_TRACKER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if "branches" not in data:
            data["branches"] = {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[community_rotation] Failed to read activity tracker: %s", e)
        return {"branches": {}}


def _save_activity_tracker(data: dict) -> None:
    """Write the activity tracker state file."""
    try:
        with open(ACTIVITY_TRACKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    except OSError as e:
        logger.warning("[community_rotation] Failed to save activity tracker: %s", e)


def _update_activity(tracker: dict, branch_name: str, has_activity: bool) -> dict:
    """
    Update the activity tracker for a branch.

    If has_activity: reset consecutive_passes, update last_active, clear alerted.
    If not: increment consecutive_passes, update last_checked.
    """
    now = datetime.now().isoformat()
    branches = tracker.setdefault("branches", {})
    entry = branches.get(branch_name, {
        "consecutive_passes": 0,
        "last_active": now,
        "last_checked": now,
        "alerted": False,
    })

    if has_activity:
        entry["consecutive_passes"] = 0
        entry["last_active"] = now
        entry["alerted"] = False
    else:
        entry["consecutive_passes"] = entry.get("consecutive_passes", 0) + 1

    entry["last_checked"] = now
    branches[branch_name] = entry
    tracker["branches"] = branches
    return tracker


def _check_inactivity_alert(tracker: dict, branch_name: str, branch_email: str) -> None:
    """
    Check if a branch has crossed the inactivity threshold.

    If consecutive_passes >= INACTIVITY_THRESHOLD and not already alerted,
    send an alert email to @daemon and mark as alerted.
    """
    entry = tracker.get("branches", {}).get(branch_name, {})
    passes = entry.get("consecutive_passes", 0)
    alerted = entry.get("alerted", False)
    last_active = entry.get("last_active", "unknown")

    if passes >= INACTIVITY_THRESHOLD and not alerted:
        # Send alert email via subprocess (best effort)
        subject = f"INACTIVITY ALERT: {branch_name}"
        body = (
            f"Branch {branch_email} has had zero dashboard activity for "
            f"{passes} consecutive rotation checks. Last active: {last_active}. "
            f"Investigate -- dashboard may not be refreshing, or branch may be "
            f"genuinely inactive."
        )
        try:
            subprocess.run(
                [
                    "drone", "@ai_mail", "send", "@daemon",
                    subject, body,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("[community_rotation] Failed to send inactivity alert: %s", e)

        # Mark as alerted so we don't spam
        tracker["branches"][branch_name]["alerted"] = True
        logger.warning(
            "[community_rotation] INACTIVITY ALERT: %s - %d consecutive passes",
            branch_name, passes,
        )


PLUGIN_CONFIG = {
    "name": "community_rotation",
    "schedule": "interval",
    "time": None,
    "interval_minutes": 240,  # Every 4 hours (was hourly -- too frequent)
    "enabled": True,  # Re-enabled 2026-02-26: 4hr interval, dashboard pre-check skips idle branches
    "branch": "@rotating",  # Placeholder -- run() handles actual target
    "fresh": True,
    "max_turns": 15,
    "self_dispatch": True,  # Scheduler calls run() instead of wake script
    "prompt": ENGAGEMENT_PROMPT,
}


def run() -> dict:
    """
    Select next branch in rotation, pre-check dashboard, dispatch via wake script.

    Pre-checks the target branch's dashboard for pending activity.
    If zero activity, skips the wake and advances rotation.
    Tracks consecutive zero-activity passes and alerts on prolonged silence.

    Returns:
        Dict with status, branch dispatched/skipped, rotation and activity info
    """
    # Load eligible branches
    branches = _load_eligible_branches()
    if not branches:
        return {"status": "error", "message": "No eligible branches found"}

    # Get next branch in rotation
    last_index = _load_rotation_state()
    current_index = (last_index + 1) % len(branches)
    target = branches[current_index]

    logger.info(
        "[community_rotation] Rotation %d/%d -> %s",
        current_index + 1, len(branches), target["name"]
    )

    # --- Dashboard pre-check ---
    branch_path = target.get("path", "")
    activity = _check_dashboard_activity(branch_path)

    # --- Activity tracking ---
    tracker = _load_activity_tracker()
    tracker = _update_activity(tracker, target["name"], activity["has_activity"])
    _check_inactivity_alert(tracker, target["name"], target["email"])
    _save_activity_tracker(tracker)

    passes = tracker.get("branches", {}).get(target["name"], {}).get("consecutive_passes", 0)
    mail_count = activity["mail_new"] + activity["mail_opened"]
    commons_count = activity["commons_mentions"] + activity["commons_comments"] + activity["commons_posts"]

    # --- Skip if zero activity ---
    if not activity["has_activity"]:
        logger.info(
            "[community_rotation] %s skipped (zero activity, pass #%d)",
            target["name"], passes,
        )
        # Advance rotation even on skip -- don't block rotation on inactive branches
        _save_rotation_state(current_index, target["name"])
        return {
            "status": "skipped",
            "reason": "zero_activity",
            "plugin": "community_rotation",
            "branch": target["email"],
            "branch_name": target["name"],
            "rotation": f"{current_index + 1}/{len(branches)}",
            "consecutive_passes": passes,
            "activity": activity,
        }

    # --- Has activity: dispatch via wake script ---
    if not WAKE_SCRIPT or not Path(WAKE_SCRIPT).exists():
        logger.warning("[community_rotation] Wake script not configured (set AIPASS_WAKE_SCRIPT)")
        _save_rotation_state(current_index, target["name"])
        return {
            "status": "failed",
            "branch": target["email"],
            "error": "wake script not available (set AIPASS_WAKE_SCRIPT env var)",
        }

    logger.info(
        "[community_rotation] %s woken (mail: %d, commons: %d)",
        target["name"], mail_count, commons_count,
    )

    cmd = [
        sys.executable, str(WAKE_SCRIPT),
        "--fresh",
        target["email"],
        ENGAGEMENT_PROMPT,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            # Advance rotation state only on success
            _save_rotation_state(current_index, target["name"])
            return {
                "status": "dispatched",
                "plugin": "community_rotation",
                "branch": target["email"],
                "branch_name": target["name"],
                "rotation": f"{current_index + 1}/{len(branches)}",
                "activity": activity,
            }
        else:
            stderr = (result.stderr or "")[:200]
            return {
                "status": "failed",
                "branch": target["email"],
                "error": f"wake script rc={result.returncode}: {stderr}",
            }

    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "branch": target["email"],
            "error": "wake script timed out (30s)",
        }
    except Exception as e:
        return {
            "status": "failed",
            "branch": target["email"],
            "error": str(e),
        }
