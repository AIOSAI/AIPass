# =================== AIPass ====================
# Name: trade_ops.py
# Description: Trading & Ephemeral Item Operations Handler
# Version: 1.1.1
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""
Trading & Ephemeral Item Operations Handler
"""

import json
from datetime import datetime, timezone, timedelta
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.commons.apps.handlers.database.db import get_db, close_db
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.handlers.identity.identity_ops import resolve_registered_name


def _now_utc() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sweep_expired() -> int:
    """Sweep-on-access: delete artifacts where expires_at < now.

    Returns the count swept, or -1 on failure (never readable as "nothing expired")."""
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
                "DELETE FROM artifact_history WHERE artifact_id = ?",
                (row["id"],),
            )
            conn.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
            logger.info(f"[trade_ops] Swept expired item '{row['name']}' (id={row['id']}, owner={row['owner']})")
            count += 1

        conn.commit()
        close_db(conn)
        return count

    except Exception as e:
        logger.error(f"Sweep expired failed: {e}")
        return -1


def gift_artifact(args: List[str]) -> dict:
    """Gift an artifact to another branch."""
    if len(args) < 2:
        return {"success": False, "error": "Usage: commons gift <artifact_id> @branch"}

    try:
        artifact_id = int(args[0])
    except ValueError:
        logger.warning("[trade_ops] Non-numeric artifact ID provided for gift")
        return {"success": False, "error": "Artifact ID must be a number"}

    try:
        recipient = resolve_registered_name(args[1])
    except Exception as exc:
        logger.warning(f"[trade_ops] gift stopped: branch registry unreadable: {exc}")
        return {"success": False, "error": f"Branch registry unreadable: {exc}"}
    if not recipient:
        return {"success": False, "error": f"Branch '{args[1]}' not found in BRANCH_REGISTRY"}

    from aipass.commons.apps.handlers.identity.identity_ops import CallerLookupFailed, get_caller_branch

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
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

        # Owner in the WHERE: a concurrent gift or trade of the same artifact moves 0 rows here.
        moved = conn.execute(
            "UPDATE artifacts SET owner = ? WHERE id = ? AND owner = ?", (recipient, artifact_id, sender)
        ).rowcount
        if not moved:
            conn.rollback()
            close_db(conn)
            return {"success": False, "error": f"Artifact {artifact_id} changed owner while gifting; nothing moved"}
        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'gifted', ?, ?, ?)",
            (artifact_id, sender, recipient, f"Gifted '{artifact['name']}' from {sender} to {recipient}"),
        )
        conn.commit()
        close_db(conn)

        json_handler.log_operation(
            "gift_artifact", {"artifact_id": artifact_id, "sender": sender, "recipient": recipient}
        )
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


def trade_artifact(args: List[str]) -> dict:
    """Trade artifacts between two branches (mutual exchange)."""
    if len(args) < 3:
        return {"success": False, "error": "Usage: commons trade <your_artifact_id> <their_artifact_id> @branch"}

    try:
        your_id = int(args[0])
        their_id = int(args[1])
    except ValueError:
        logger.warning("[trade_ops] Non-numeric artifact IDs provided for trade")
        return {"success": False, "error": "Artifact IDs must be numbers"}

    try:
        partner = resolve_registered_name(args[2])
    except Exception as exc:
        logger.warning(f"[trade_ops] trade stopped: branch registry unreadable: {exc}")
        return {"success": False, "error": f"Branch registry unreadable: {exc}"}
    if not partner:
        return {"success": False, "error": f"Branch '{args[2]}' not found in BRANCH_REGISTRY"}

    from aipass.commons.apps.handlers.identity.identity_ops import CallerLookupFailed, get_caller_branch

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
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

        # Owners in the WHERE: if either side changed hands meanwhile, the whole trade rolls back.
        moved = conn.execute(
            "UPDATE artifacts SET owner = ? WHERE id = ? AND owner = ?", (partner, your_id, sender)
        ).rowcount
        moved += conn.execute(
            "UPDATE artifacts SET owner = ? WHERE id = ? AND owner = ?", (sender, their_id, partner)
        ).rowcount
        if moved != 2:
            conn.rollback()
            close_db(conn)
            return {"success": False, "error": "An artifact changed owner while trading; nothing moved"}

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


def drop_item(args: List[str]) -> dict:
    """Drop an ephemeral item in a room for anyone to find."""
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
                logger.warning("[trade_ops] Non-numeric --expires value provided for drop")
                return {"success": False, "error": "--expires must be a number (minutes)"}
            i += 2
        else:
            i += 1

    from aipass.commons.apps.handlers.identity.identity_ops import CallerLookupFailed, get_caller_branch

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
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


def find_item(args: List[str]) -> dict:
    """Pick up an ephemeral item before it expires.

    A failed sweep does not stop the find (it checks expires_at itself); success carries sweep_failed."""
    if not args:
        return {"success": False, "error": "Usage: commons find <artifact_id>"}

    try:
        artifact_id = int(args[0])
    except ValueError:
        logger.warning("[trade_ops] Non-numeric artifact ID provided for find")
        return {"success": False, "error": "Artifact ID must be a number"}

    sweep_failed = sweep_expired() == -1

    from aipass.commons.apps.handlers.identity.identity_ops import CallerLookupFailed, get_caller_branch

    try:
        caller = get_caller_branch()
    except CallerLookupFailed as exc:
        return {"success": False, "error": str(exc)}
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
            return {
                "success": False,
                "error": f"Artifact {artifact_id} is not an ephemeral item (type: {artifact['type']})",
            }

        if artifact["expires_at"]:
            now = datetime.now(timezone.utc)
            expires_dt = datetime.strptime(artifact["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if now > expires_dt:
                # Left for sweep_expired, which removes the history rows first as the foreign key requires.
                close_db(conn)
                return {"success": False, "error": f"Artifact {artifact_id} has expired and is no longer available"}

        old_owner = artifact["owner"]

        # Old owner in the WHERE: of two finders at once, only the first moves the row.
        moved = conn.execute(
            "UPDATE artifacts SET owner = ?, expires_at = NULL WHERE id = ? AND owner = ? AND expires_at IS NOT NULL",
            (finder, artifact_id, old_owner),
        ).rowcount
        if not moved:
            conn.rollback()
            close_db(conn)
            return {"success": False, "error": f"Artifact {artifact_id} was already found"}
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
            "sweep_failed": sweep_failed,
        }

    except Exception as e:
        logger.error(f"Find item failed: {e}")
        return {"success": False, "error": str(e)}


def mint_event_artifact(args: List[str]) -> dict:
    """Mint proof-of-attendance artifacts for an event."""
    if len(args) < 2:
        return {"success": False, "error": 'Usage: commons mint "Event Name" @branch1 @branch2 ...'}

    event_name = args[0]
    mentions = args[1:]

    branches = []
    warnings = []
    for mention in mentions:
        try:
            branch = resolve_registered_name(mention)
        except Exception as exc:
            logger.warning(f"[trade_ops] mint stopped: branch registry unreadable: {exc}")
            return {"success": False, "error": f"Branch registry unreadable: {exc}"}
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
            "INSERT OR IGNORE INTO agents (branch_name, display_name, description) VALUES (?, ?, ?)",
            ("THE_COMMONS", "The Commons", "The Commons event host"),
        )

        minted = []

        for branch in branches:
            description = f"Proof of attendance: {event_name}"

            cursor = conn.execute(
                "INSERT INTO artifacts (name, type, creator, owner, rarity, description, metadata) "
                "VALUES (?, 'event', 'THE_COMMONS', ?, 'rare', ?, ?)",
                (
                    f"{event_name} - Attendee Badge",
                    branch,
                    description,
                    json.dumps({"event": event_name, "attendee": branch}),
                ),
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
