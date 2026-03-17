# =================== AIPass ====================
# Name: trade_ops.py
# Description: Trading & Ephemeral Item Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Trading & Ephemeral Item Operations Handler

Implementation logic for artifact trading, gifting, ephemeral item drops,
item finding, expired item sweeping, and event artifact minting.
Returns dicts for module display layer.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler

# Constants
BRANCH_REGISTRY_PATH = os.path.join(os.path.expanduser("~"), "BRANCH_REGISTRY.json")

RARITY_COLORS = {
    "common": "white",
    "uncommon": "green",
    "rare": "blue",
    "legendary": "yellow",
    "unique": "magenta",
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _resolve_branch_name(mention: str) -> Optional[str]:
    """Resolve a @mention to a branch name."""
    name = mention.lstrip("@").upper()

    if not os.path.exists(BRANCH_REGISTRY_PATH):
        return None

    try:
        with open(BRANCH_REGISTRY_PATH, encoding="utf-8") as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            if branch.get("name") == name:
                return name
        return None
    except Exception:
        return None


def _now_utc() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# SWEEP EXPIRED ITEMS
# =============================================================================

def sweep_expired() -> int:
    """
    Sweep-on-access: delete artifacts where expires_at < now.

    Returns:
        Number of artifacts swept
    """
    try:
        conn = get_db()
        now = _now_utc()

        expired = conn.execute(
            "SELECT id, name, owner FROM artifacts WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        ).fetchall()

        if not expired:
            close_db(conn)
            return 0

        count = 0
        for row in expired:
            conn.execute(
                "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
                "VALUES (?, 'expired', ?, NULL, ?)",
                (row["id"], row["owner"], f"Ephemeral item '{row['name']}' expired"),
            )
            conn.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
            count += 1

        conn.commit()
        close_db(conn)
        return count

    except Exception as e:
        logger.error(f"Sweep expired failed: {e}")
        return 0


# =============================================================================
# GIFT ARTIFACT
# =============================================================================

def gift_artifact(args: List[str]) -> dict:
    """
    Gift an artifact to another branch.

    Usage: commons gift <artifact_id> @branch

    Returns:
        Dict with success, artifact info, sender, recipient
    """
    if len(args) < 2:
        return {"success": False, "error": "Usage: commons gift <artifact_id> @branch"}

    try:
        artifact_id = int(args[0])
    except ValueError:
        return {"success": False, "error": "Artifact ID must be a number"}

    recipient = _resolve_branch_name(args[1])
    if not recipient:
        return {"success": False, "error": f"Branch '{args[1]}' not found in BRANCH_REGISTRY"}

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch."}

    sender = caller["name"]

    if sender == recipient:
        return {"success": False, "error": "You cannot gift an artifact to yourself"}

    try:
        conn = get_db()

        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Artifact {artifact_id} not found"}

        artifact = dict(row)

        if artifact["owner"] != sender:
            close_db(conn)
            return {"success": False, "error": f"You don't own artifact {artifact_id}. Only the owner can gift it."}

        conn.execute("UPDATE artifacts SET owner = ? WHERE id = ?", (recipient, artifact_id))
        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'gifted', ?, ?, ?)",
            (artifact_id, sender, recipient, f"Gifted '{artifact['name']}' from {sender} to {recipient}"),
        )
        conn.commit()
        close_db(conn)

        json_handler.log_operation("gift_artifact", {"artifact_id": artifact_id, "sender": sender, "recipient": recipient})
        return {
            "success": True,
            "artifact_id": artifact_id,
            "name": artifact["name"],
            "rarity": artifact["rarity"],
            "type": artifact["type"],
            "sender": sender,
            "recipient": recipient,
        }

    except Exception as e:
        logger.error(f"Gift artifact failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# TRADE ARTIFACTS
# =============================================================================

def trade_artifact(args: List[str]) -> dict:
    """
    Trade artifacts between two branches (mutual exchange).

    Usage: commons trade <your_artifact_id> <their_artifact_id> @branch

    Returns:
        Dict with success, both artifact details, sender, partner
    """
    if len(args) < 3:
        return {"success": False, "error": "Usage: commons trade <your_artifact_id> <their_artifact_id> @branch"}

    try:
        your_id = int(args[0])
        their_id = int(args[1])
    except ValueError:
        return {"success": False, "error": "Artifact IDs must be numbers"}

    partner = _resolve_branch_name(args[2])
    if not partner:
        return {"success": False, "error": f"Branch '{args[2]}' not found in BRANCH_REGISTRY"}

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch."}

    sender = caller["name"]

    if sender == partner:
        return {"success": False, "error": "You cannot trade with yourself"}

    try:
        conn = get_db()

        your_row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (your_id,)).fetchone()
        their_row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (their_id,)).fetchone()

        if not your_row:
            close_db(conn)
            return {"success": False, "error": f"Artifact {your_id} not found"}
        if not their_row:
            close_db(conn)
            return {"success": False, "error": f"Artifact {their_id} not found"}

        your_artifact = dict(your_row)
        their_artifact = dict(their_row)

        if your_artifact["owner"] != sender:
            close_db(conn)
            return {"success": False, "error": f"You don't own artifact {your_id}"}
        if their_artifact["owner"] != partner:
            close_db(conn)
            return {"success": False, "error": f"{partner} doesn't own artifact {their_id}"}

        conn.execute("UPDATE artifacts SET owner = ? WHERE id = ?", (partner, your_id))
        conn.execute("UPDATE artifacts SET owner = ? WHERE id = ?", (sender, their_id))

        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'traded', ?, ?, ?)",
            (your_id, sender, partner, f"Traded '{your_artifact['name']}' to {partner} for '{their_artifact['name']}'"),
        )
        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'traded', ?, ?, ?)",
            (their_id, partner, sender, f"Traded '{their_artifact['name']}' to {sender} for '{your_artifact['name']}'"),
        )

        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "sender": sender,
            "partner": partner,
            "your_artifact": {
                "id": your_id,
                "name": your_artifact["name"],
                "rarity": your_artifact["rarity"],
            },
            "their_artifact": {
                "id": their_id,
                "name": their_artifact["name"],
                "rarity": their_artifact["rarity"],
            },
        }

    except Exception as e:
        logger.error(f"Trade artifact failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# DROP EPHEMERAL ITEM
# =============================================================================

def drop_item(args: List[str]) -> dict:
    """
    Drop an ephemeral item in a room for anyone to find.

    Usage: commons drop "name" "description" <room> [--expires 5]

    Returns:
        Dict with success, artifact_id, name, room, expires info
    """
    if len(args) < 3:
        return {"success": False, "error": 'Usage: commons drop "name" "description" <room> [--expires 5]'}

    name = args[0]
    description = args[1]
    room = args[2]

    expires_minutes = 5
    remaining = args[3:]
    i = 0
    while i < len(remaining):
        if remaining[i] == "--expires" and i + 1 < len(remaining):
            try:
                expires_minutes = int(remaining[i + 1])
                expires_minutes = max(1, min(1440, expires_minutes))
            except ValueError:
                return {"success": False, "error": "--expires must be a number (minutes)"}
            i += 2
        else:
            i += 1

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch."}

    creator = caller["name"]

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=expires_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn = get_db()

        room_row = conn.execute("SELECT name FROM rooms WHERE name = ?", (room,)).fetchone()
        if not room_row:
            close_db(conn)
            return {"success": False, "error": f"Room '{room}' does not exist"}

        cursor = conn.execute(
            "INSERT INTO artifacts (name, type, creator, owner, rarity, description, room_found, expires_at) "
            "VALUES (?, 'found', ?, ?, 'common', ?, ?, ?)",
            (name, creator, creator, description, room, expires_at),
        )
        artifact_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'created', ?, NULL, ?)",
            (artifact_id, creator, f"Dropped ephemeral item '{name}' in r/{room} (expires in {expires_minutes}m)"),
        )

        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "artifact_id": artifact_id,
            "name": name,
            "description": description,
            "room": room,
            "creator": creator,
            "expires_minutes": expires_minutes,
            "expires_at": expires_at,
        }

    except Exception as e:
        logger.error(f"Drop item failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# FIND (PICK UP) EPHEMERAL ITEM
# =============================================================================

def find_item(args: List[str]) -> dict:
    """
    Pick up an ephemeral item before it expires.

    Usage: commons find <artifact_id>

    Returns:
        Dict with success, artifact details, finder
    """
    if not args:
        return {"success": False, "error": "Usage: commons find <artifact_id>"}

    try:
        artifact_id = int(args[0])
    except ValueError:
        return {"success": False, "error": "Artifact ID must be a number"}

    sweep_expired()

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch."}

    finder = caller["name"]

    try:
        conn = get_db()

        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Artifact {artifact_id} not found (it may have expired)"}

        artifact = dict(row)

        if artifact["type"] != "found":
            close_db(conn)
            return {"success": False, "error": f"Artifact {artifact_id} is not an ephemeral item (type: {artifact['type']})"}

        if artifact["expires_at"]:
            now = datetime.now(timezone.utc)
            expires_dt = datetime.strptime(artifact["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if now > expires_dt:
                conn.execute(
                    "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
                    "VALUES (?, 'expired', ?, NULL, ?)",
                    (artifact_id, artifact["owner"], f"Ephemeral item '{artifact['name']}' expired"),
                )
                conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
                conn.commit()
                close_db(conn)
                return {"success": False, "error": f"Artifact {artifact_id} has expired and is no longer available"}

        old_owner = artifact["owner"]

        conn.execute(
            "UPDATE artifacts SET owner = ?, expires_at = NULL WHERE id = ?",
            (finder, artifact_id),
        )
        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'found', ?, ?, ?)",
            (artifact_id, old_owner, finder, f"Found by {finder} in r/{artifact['room_found'] or 'unknown'}"),
        )

        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "artifact_id": artifact_id,
            "name": artifact["name"],
            "description": artifact["description"],
            "rarity": artifact["rarity"],
            "room_found": artifact["room_found"] or "unknown",
            "creator": artifact["creator"],
            "finder": finder,
        }

    except Exception as e:
        logger.error(f"Find item failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# MINT EVENT ARTIFACT
# =============================================================================

def mint_event_artifact(args: List[str]) -> dict:
    """
    Mint proof-of-attendance artifacts for an event.

    Usage: commons mint "Event Name" @branch1 @branch2 @branch3

    Returns:
        Dict with success, event_name, minted list of (branch, artifact_id)
    """
    if len(args) < 2:
        return {"success": False, "error": 'Usage: commons mint "Event Name" @branch1 @branch2 ...'}

    event_name = args[0]
    mentions = args[1:]

    branches = []
    warnings = []
    for mention in mentions:
        branch = _resolve_branch_name(mention)
        if branch:
            branches.append(branch)
        else:
            warnings.append(f"Branch '{mention}' not found, skipping")

    if not branches:
        return {"success": False, "error": "No valid branches found. Provide at least one @branch."}

    branches = list(dict.fromkeys(branches))

    try:
        conn = get_db()

        conn.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
            "VALUES (?, ?, ?)",
            ("THE_COMMONS", "The Commons", "The Commons event host"),
        )

        minted = []

        for branch in branches:
            description = f"Proof of attendance: {event_name}"

            cursor = conn.execute(
                "INSERT INTO artifacts (name, type, creator, owner, rarity, description, metadata) "
                "VALUES (?, 'event', 'THE_COMMONS', ?, 'rare', ?, ?)",
                (f"{event_name} - Attendee Badge", branch, description,
                 json.dumps({"event": event_name, "attendee": branch})),
            )
            artifact_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
                "VALUES (?, 'created', 'THE_COMMONS', ?, ?)",
                (artifact_id, branch, f"Event badge minted for '{event_name}'"),
            )

            minted.append({"branch": branch, "artifact_id": artifact_id})

        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "event_name": event_name,
            "minted": minted,
            "warnings": warnings,
        }

    except Exception as e:
        logger.error(f"Mint event artifact failed: {e}")
        return {"success": False, "error": str(e)}
