# =================== AIPass ====================
# Name: artifact_ops.py
# Description: Artifact Operations Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Artifact Operations Handler

Implementation logic for artifact workflows: craft, list, inspect,
birth certificates, and joint artifact collaboration.
Returns dicts for module display layer.
"""

import json
import os
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from aipass.prax.apps.modules.logger import system_logger as logger

from commons.apps.handlers.database.db import get_db, close_db
from commons.apps.handlers.json import json_handler

# Constants
BRANCH_REGISTRY_PATH = os.path.join(os.path.expanduser("~"), "BRANCH_REGISTRY.json")

VALID_RARITIES = ("common", "uncommon", "rare", "legendary", "unique")
VALID_TYPES = ("crafted", "found", "birth_certificate", "event", "seasonal", "joint", "system")

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

def _validate_metadata(metadata_str: str) -> Optional[dict]:
    """Validate JSON metadata string. Must be shallow (one level deep max)."""
    try:
        data = json.loads(metadata_str)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    for value in data.values():
        if isinstance(value, (dict, list)):
            return None

    return data


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


# =============================================================================
# ARTIFACT OPERATIONS
# =============================================================================

def craft_artifact(args: List[str]) -> dict:
    """
    Create a new artifact.

    Usage: commons craft "name" "description" [--type crafted] [--rarity common] [--metadata '{}']

    Returns:
        Dict with success, artifact_id, name, type, rarity, creator, description
    """
    if not args or len(args) < 2:
        return {
            "success": False,
            "error": 'Usage: commons craft "name" "description" [--type TYPE] [--rarity RARITY]',
        }

    name = args[0]
    description = args[1]

    artifact_type = "crafted"
    rarity = "common"
    metadata_str = "{}"
    remaining = args[2:]

    i = 0
    while i < len(remaining):
        if remaining[i] == "--type" and i + 1 < len(remaining):
            artifact_type = remaining[i + 1]
            i += 2
        elif remaining[i] == "--rarity" and i + 1 < len(remaining):
            rarity = remaining[i + 1]
            i += 2
        elif remaining[i] == "--metadata" and i + 1 < len(remaining):
            metadata_str = remaining[i + 1]
            i += 2
        else:
            i += 1

    if artifact_type not in VALID_TYPES:
        return {"success": False, "error": f"Invalid type '{artifact_type}'. Must be one of: {', '.join(VALID_TYPES)}"}

    if rarity not in VALID_RARITIES:
        return {"success": False, "error": f"Invalid rarity '{rarity}'. Must be one of: {', '.join(VALID_RARITIES)}"}

    metadata = _validate_metadata(metadata_str)
    if metadata is None:
        return {"success": False, "error": "Invalid metadata: must be valid shallow JSON (no nested objects/arrays)"}

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    creator = caller["name"]

    try:
        conn = get_db()

        cursor = conn.execute(
            "INSERT INTO artifacts (name, type, creator, owner, rarity, description, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, artifact_type, creator, creator, rarity, description, json.dumps(metadata)),
        )
        artifact_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
            "VALUES (?, 'created', ?, ?, ?)",
            (artifact_id, creator, creator, f"Crafted '{name}' ({rarity} {artifact_type})"),
        )

        conn.commit()
        close_db(conn)
        json_handler.log_operation("craft_artifact", {"artifact_id": artifact_id, "name": name, "rarity": rarity, "creator": creator})

        return {
            "success": True,
            "artifact_id": artifact_id,
            "name": name,
            "type": artifact_type,
            "rarity": rarity,
            "creator": creator,
            "description": description,
        }

    except Exception as e:
        logger.error(f"Artifact creation failed: {e}")
        return {"success": False, "error": str(e)}


def list_artifacts(args: List[str]) -> dict:
    """
    List artifacts. Default: show only YOUR artifacts.

    Usage: commons artifacts [--all] [--type TYPE] [--rarity RARITY]

    Returns:
        Dict with success, artifacts list, scope label, show_all flag
    """
    show_all = "--all" in args
    filter_type = None
    filter_rarity = None

    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            filter_type = args[i + 1]
            i += 2
        elif args[i] == "--rarity" and i + 1 < len(args):
            filter_rarity = args[i + 1]
            i += 2
        else:
            i += 1

    owner_filter = None
    if not show_all:
        from commons.apps.modules.commons_identity import get_caller_branch
        caller = get_caller_branch()
        if not caller:
            return {"success": False, "error": "Could not detect calling branch. Use --all to see all artifacts."}
        owner_filter = caller["name"]

    try:
        conn = get_db()

        query = "SELECT id, name, type, creator, owner, rarity, description, created_at FROM artifacts WHERE 1=1"
        params: list = []

        if owner_filter:
            query += " AND owner = ?"
            params.append(owner_filter)
        if filter_type:
            query += " AND type = ?"
            params.append(filter_type)
        if filter_rarity:
            query += " AND rarity = ?"
            params.append(filter_rarity)

        query += " ORDER BY created_at DESC"

        rows = conn.execute(query, params).fetchall()
        close_db(conn)

    except Exception as e:
        logger.error(f"Artifact listing failed: {e}")
        return {"success": False, "error": str(e)}

    artifacts = [dict(r) for r in rows]
    scope_label = "All Artifacts" if show_all else f"Artifacts owned by {owner_filter}"

    return {
        "success": True,
        "artifacts": artifacts,
        "scope_label": scope_label,
        "show_all": show_all,
        "owner_filter": owner_filter,
    }


def inspect_artifact(args: List[str]) -> dict:
    """
    Show full artifact details including provenance chain.

    Usage: commons inspect <id> [--full]

    Returns:
        Dict with success, artifact, history, show_full
    """
    if not args:
        return {"success": False, "error": "Usage: commons inspect <artifact_id> [--full]"}

    show_full = "--full" in args
    filtered_args = [a for a in args if a != "--full"]

    if not filtered_args:
        return {"success": False, "error": "Usage: commons inspect <artifact_id> [--full]"}

    try:
        artifact_id = int(filtered_args[0])
    except ValueError:
        return {"success": False, "error": "Artifact ID must be a number"}

    try:
        conn = get_db()

        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Artifact {artifact_id} not found"}

        artifact = dict(row)

        history_rows = conn.execute(
            "SELECT * FROM artifact_history WHERE artifact_id = ? ORDER BY created_at ASC",
            (artifact_id,),
        ).fetchall()
        history = [dict(r) for r in history_rows]

        close_db(conn)

    except Exception as e:
        logger.error(f"Artifact inspect failed: {e}")
        return {"success": False, "error": str(e)}

    # Parse metadata
    try:
        metadata = json.loads(artifact["metadata"]) if artifact["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    artifact["_parsed_metadata"] = metadata

    return {
        "success": True,
        "artifact": artifact,
        "history": history,
        "show_full": show_full,
    }


def collab_artifact(args: List[str]) -> dict:
    """
    Initiate a joint artifact that requires multiple signers.

    Usage: commons collab "artifact_name" "description" @signer1 @signer2 [--rarity rare]

    Returns:
        Dict with success, pending_id, name, rarity, initiator, signers, expires_at
    """
    if len(args) < 3:
        return {"success": False, "error": 'Usage: commons collab "name" "description" @signer1 @signer2 [--rarity rare]'}

    artifact_name = args[0]
    description = args[1]

    rarity = "rare"
    signers = []
    remaining = args[2:]
    warnings = []
    i = 0
    while i < len(remaining):
        if remaining[i] == "--rarity" and i + 1 < len(remaining):
            rarity = remaining[i + 1]
            i += 2
        elif remaining[i].startswith("@"):
            resolved = _resolve_branch_name(remaining[i])
            if resolved:
                signers.append(resolved)
            else:
                warnings.append(f"Branch '{remaining[i]}' not found, skipping")
            i += 1
        else:
            i += 1

    if not signers:
        return {"success": False, "error": "At least one @signer is required"}

    if rarity not in VALID_RARITIES:
        return {"success": False, "error": f"Invalid rarity '{rarity}'. Must be one of: {', '.join(VALID_RARITIES)}"}

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    initiator = caller["name"]
    signers = list(dict.fromkeys(s for s in signers if s != initiator))
    if not signers:
        return {"success": False, "error": "You need at least one other signer (not yourself)"}

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn = get_db()

        cursor = conn.execute(
            "INSERT INTO joint_pending (artifact_name, description, rarity, initiator, "
            "required_signers, current_signers, expires_at) VALUES (?, ?, ?, ?, ?, '[]', ?)",
            (artifact_name, description, rarity, initiator, json.dumps(signers), expires_at),
        )
        pending_id = cursor.lastrowid
        conn.commit()
        close_db(conn)

        return {
            "success": True,
            "pending_id": pending_id,
            "name": artifact_name,
            "rarity": rarity,
            "initiator": initiator,
            "signers": signers,
            "expires_at": expires_at,
            "warnings": warnings,
        }

    except Exception as e:
        logger.error(f"Collab artifact failed: {e}")
        return {"success": False, "error": str(e)}


def sign_artifact(args: List[str]) -> dict:
    """
    Sign a pending joint artifact.

    Usage: commons sign <pending_id>

    Returns:
        Dict with success, completed (bool), and relevant details
    """
    if not args:
        return {"success": False, "error": "Usage: commons sign <pending_id>"}

    try:
        pending_id = int(args[0])
    except ValueError:
        return {"success": False, "error": "Pending ID must be a number"}

    from commons.apps.modules.commons_identity import get_caller_branch
    caller = get_caller_branch()
    if not caller:
        return {"success": False, "error": "Could not detect calling branch. Run from a branch directory."}

    signer = caller["name"]

    try:
        conn = get_db()

        row = conn.execute("SELECT * FROM joint_pending WHERE id = ?", (pending_id,)).fetchone()
        if not row:
            close_db(conn)
            return {"success": False, "error": f"Pending joint artifact {pending_id} not found"}

        pending = dict(row)

        now = datetime.now(timezone.utc)
        expires_dt = datetime.strptime(pending["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now > expires_dt:
            conn.execute("DELETE FROM joint_pending WHERE id = ?", (pending_id,))
            conn.commit()
            close_db(conn)
            return {"success": False, "error": f"Joint artifact {pending_id} has expired"}

        required_signers = json.loads(pending["required_signers"])
        current_signers = json.loads(pending["current_signers"])

        if signer not in required_signers:
            close_db(conn)
            return {"success": False, "error": f"You are not a required signer. Required: {', '.join(required_signers)}"}

        if signer in current_signers:
            close_db(conn)
            return {"success": False, "error": "You have already signed this artifact"}

        current_signers.append(signer)
        conn.execute(
            "UPDATE joint_pending SET current_signers = ? WHERE id = ?",
            (json.dumps(current_signers), pending_id),
        )

        if set(required_signers).issubset(set(current_signers)):
            all_participants = [pending["initiator"]] + current_signers
            metadata = json.dumps({"signers": all_participants, "joint": True})

            cursor = conn.execute(
                "INSERT INTO artifacts (name, type, creator, owner, rarity, description, metadata) "
                "VALUES (?, 'joint', ?, ?, ?, ?, ?)",
                (pending["artifact_name"], pending["initiator"], pending["initiator"],
                 pending["rarity"], pending["description"], metadata),
            )
            artifact_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO artifact_history (artifact_id, action, from_agent, to_agent, details) "
                "VALUES (?, 'created', ?, ?, ?)",
                (artifact_id, pending["initiator"], pending["initiator"],
                 f"Joint artifact created by {', '.join(all_participants)}"),
            )

            conn.execute("DELETE FROM joint_pending WHERE id = ?", (pending_id,))
            conn.commit()
            close_db(conn)

            return {
                "success": True,
                "completed": True,
                "artifact_id": artifact_id,
                "name": pending["artifact_name"],
                "rarity": pending["rarity"],
                "participants": all_participants,
                "owner": pending["initiator"],
            }
        else:
            conn.commit()
            close_db(conn)

            remaining_signers = [s for s in required_signers if s not in current_signers]
            return {
                "success": True,
                "completed": False,
                "pending_id": pending_id,
                "signer": signer,
                "signed": current_signers,
                "remaining": remaining_signers,
            }

    except Exception as e:
        logger.error(f"Sign artifact failed: {e}")
        return {"success": False, "error": str(e)}
