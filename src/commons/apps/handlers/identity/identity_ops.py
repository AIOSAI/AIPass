# =================== AIPass ====================
# Name: identity_ops.py
# Description: Identity operations handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Identity Operations Handler

Implementation logic for branch identity detection, registry lookup,
caller detection, and mention extraction.

Detects which branch is calling The Commons based on CWD by walking
up the directory tree to find a *.id.json file, then cross-referencing
with AIPASS_REGISTRY.json.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from aipass.prax.apps.modules.logger import system_logger as logger
from commons.apps.handlers.json import json_handler


# =============================================================================
# CONSTANTS
# =============================================================================

def _find_branch_registry_path() -> Path:
    """
    Locate AIPASS_REGISTRY.json by searching standard paths.

    Returns:
        Path to registry file (may not exist).
    """
    # Check AIPASS_ROOT env var
    aipass_root = os.environ.get("AIPASS_ROOT", "")
    if aipass_root:
        candidate = Path(aipass_root) / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate

    # Walk up from this package to find project root
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Standard locations
    for candidate_path in [
        Path.home() / ".aipass" / "AIPASS_REGISTRY.json",
        Path.home() / "AIPASS_REGISTRY.json",
    ]:
        if candidate_path.exists():
            return candidate_path

    # Return a default even if it doesn't exist
    return Path.home() / "AIPASS_REGISTRY.json"


BRANCH_REGISTRY_PATH = _find_branch_registry_path()


# =============================================================================
# BRANCH DETECTION
# =============================================================================

def find_branch_root(start_path: Path) -> Optional[Path]:
    """
    Walk up directory tree to find branch root.

    Branch root is a directory containing a [BRANCH_NAME].id.json file.

    Args:
        start_path: Directory to start searching from (usually PWD).

    Returns:
        Path to branch root directory, or None if not found.
    """
    current = start_path.resolve()

    for _ in range(10):
        # AIPass branches have .trinity/passport.json
        if (current / ".trinity" / "passport.json").exists():
            return current

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def get_branch_info_from_registry(branch_path: Path) -> Optional[Dict[str, Any]]:
    """
    Look up branch information in AIPASS_REGISTRY.json by path.

    Args:
        branch_path: Path to branch directory.

    Returns:
        Dict with branch info from registry, or None if not found.
    """
    if not BRANCH_REGISTRY_PATH.exists():
        return None

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)

        branch_path_str = str(branch_path.resolve())
        registry_root = BRANCH_REGISTRY_PATH.parent

        for branch in registry.get("branches", []):
            # Registry paths are relative to the registry file's parent
            candidate = (registry_root / branch["path"]).resolve()
            if str(candidate) == branch_path_str:
                return branch

        return None

    except Exception:
        return None


def get_caller_branch() -> Optional[Dict[str, Any]]:
    """
    Detect which branch is calling The Commons based on PWD.

    Walks up from CWD to find branch root, then looks up in AIPASS_REGISTRY.json.
    Auto-registers the branch as a Commons agent if not already present.

    Returns:
        Dict with branch info {"name": "SEED", "path": "...", "email": "@seed", ...}
        or None if no branch detected.
    """
    try:
        # Use caller's original CWD if routed through drone
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
        cwd = Path(caller_cwd) if caller_cwd else Path.cwd()
        branch_root = find_branch_root(cwd)

        if not branch_root:
            logger.warning("[commons.identity] Could not detect branch from PWD")
            return None

        branch_info = get_branch_info_from_registry(branch_root)
        if not branch_info:
            logger.warning(
                f"[commons.identity] Branch at {branch_root} not in BRANCH_REGISTRY"
            )
            return None

        # Auto-register as Commons agent
        _ensure_agent_registered(branch_info)

        json_handler.log_operation("caller_detected", {"branch": branch_info.get("name", "unknown")})
        return branch_info

    except Exception as e:
        logger.error(f"[commons.identity] Branch detection failed: {e}")
        return None


def _ensure_agent_registered(branch_info: Dict[str, Any]) -> None:
    """
    Ensure the branch is registered as an agent in The Commons database.

    Args:
        branch_info: Branch dict from BRANCH_REGISTRY.
    """
    try:
        from commons.apps.handlers.database.db import get_db, close_db

        name = branch_info.get("name", "")
        if not name:
            return

        conn = get_db()

        existing = conn.execute(
            "SELECT branch_name FROM agents WHERE branch_name = ?", (name,)
        ).fetchone()

        if not existing:
            display_name = name.replace("_", " ").title()
            description = branch_info.get("description", "")
            conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
                "VALUES (?, ?, ?)",
                (name, display_name, description),
            )
            conn.commit()
            logger.info(f"[commons.identity] Auto-registered agent: {name}")

        close_db(conn)

    except Exception as e:
        logger.warning(f"[commons.identity] Agent registration failed: {e}")


# =============================================================================
# DISPLAY NAME RESOLUTION
# =============================================================================

_alias_cache: Optional[Dict[str, str]] = None


def _load_alias_cache() -> Dict[str, str]:
    """Load branch alias map from AIPASS_REGISTRY.json (cached)."""
    global _alias_cache
    if _alias_cache is not None:
        return _alias_cache

    _alias_cache = {}
    if not BRANCH_REGISTRY_PATH.exists():
        return _alias_cache

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            alias = branch.get("alias", "").strip()
            if alias:
                _alias_cache[branch["name"]] = alias
    except Exception as e:
        logger.warning(f"[commons.identity] Alias cache load failed: {e}")

    return _alias_cache


def resolve_display_name(branch_name: str, compact: bool = False) -> str:
    """
    Resolve a branch name to its display name using alias from BRANCH_REGISTRY.

    Args:
        branch_name: System branch name (e.g. "TEAM_1").
        compact: If True, return alias only. If False, return "Alias (SYSTEM)".

    Returns:
        Display name string. Falls back to branch_name if no alias set.
    """
    cache = _load_alias_cache()
    alias = cache.get(branch_name, "")
    if not alias:
        return branch_name
    if compact:
        return alias
    return f"{alias} ({branch_name})"


# =============================================================================
# MENTION EXTRACTION
# =============================================================================

def extract_mentions(content: str) -> List[str]:
    """
    Extract @mention branch names from content.

    Matches patterns like @drone, @flow, @seed_cortex.
    Validates against the agents table to ensure they exist.

    Args:
        content: Text content to search for @mentions.

    Returns:
        List of valid branch names that were mentioned (lowercased).
    """
    if not content:
        return []

    # Find all @word patterns (alphanumeric + underscore)
    pattern = r"@(\w+)"
    matches = re.findall(pattern, content)

    if not matches:
        return []

    # Normalize to lowercase
    mentioned = [m.lower() for m in matches]

    # Validate against agents table
    try:
        from commons.apps.handlers.database.db import get_db, close_db

        conn = get_db()
        placeholders = ",".join("?" * len(mentioned))
        query = f"SELECT branch_name FROM agents WHERE LOWER(branch_name) IN ({placeholders})"
        rows = conn.execute(query, mentioned).fetchall()
        close_db(conn)

        valid_mentions = [row[0] for row in rows]
        return valid_mentions

    except Exception as e:
        logger.warning(f"[commons.identity] Mention extraction failed: {e}")
        return []
