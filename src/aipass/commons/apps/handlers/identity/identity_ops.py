# =================== AIPass ====================
# Name: identity_ops.py
# Description: Identity operations handler
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-08-31
# =============================================

"""
Identity Operations Handler

Implementation logic for branch identity detection, registry lookup,
caller detection, and mention extraction.

Detects which branch is calling The Commons based on CWD by walking
up the directory tree to find a .trinity/passport.json branch root, then
cross-referencing with AIPASS_REGISTRY.json. When the AIPass registry does
not know the caller, the caller's own project registry (*_REGISTRY.json,
found by walking up from AIPASS_CALLER_CWD) is consulted — external
citizens are citizens too, and the social space has to be able to name them.
"""

import os
import re
import json
from pathlib import Path
from typing import Callable, Dict, Any, Optional, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.handlers.module_root import module_file


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

    # Walk up from this package to find project root. module_file() rather
    # than a bare .resolve(): BRANCH_REGISTRY_PATH calls this at module scope,
    # so on Windows a bare resolve would read cwd at import time.
    current = module_file(__file__).parent
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


def _find_caller_registries() -> List[Path]:
    """
    Find the registries belonging to the caller's own project.

    Walks up from AIPASS_CALLER_CWD (set by drone) looking for
    *_REGISTRY.json — external projects name theirs after themselves
    (VERA-STUDIO_REGISTRY.json). The AIPass registry is skipped: it is
    already consulted first, and re-reading it here would double the work
    for every miss. Results are sorted so a directory holding more than
    one registry always resolves the same way.

    The suffix is re-checked case-sensitively after the glob: on Windows
    and default macOS the pattern also matches *_registry.json, and a
    lowercase counter would otherwise answer an identity lookup.

    Returns:
        List of registry paths from the nearest matching directory, or [].
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return []

    try:
        caller_path = Path(caller_cwd).resolve()
    except OSError as exc:
        logger.warning(f"[commons.identity] Unusable AIPASS_CALLER_CWD '{caller_cwd}': {exc}")
        return []

    primary = BRANCH_REGISTRY_PATH.resolve() if BRANCH_REGISTRY_PATH.exists() else None

    for directory in [caller_path] + list(caller_path.parents):
        matches = sorted(
            path
            for path in directory.glob("*_REGISTRY.json")
            # Windows and default macOS are case-insensitive, so this glob also
            # returns *_registry.json — plan counters and .template_registry.json
            # (pathlib's * matches dotfiles). Re-check the SUFFIX case-sensitively;
            # never the stem, because external projects name registries after
            # themselves and vera_studio_REGISTRY.json is a real citizen.
            if path.name.endswith("_REGISTRY.json")
            and path.name != "AIPASS_REGISTRY.json"
            and path.resolve() != primary
        )
        if matches:
            return matches

    return []


def _branches_from_registry(registry_path: Path) -> List[Dict[str, Any]]:
    """
    Read the branches list out of a registry file.

    Args:
        registry_path: Path to a *_REGISTRY.json file.

    Returns:
        List of branch dicts (dict-shaped registries are flattened to
        their values), or [] if the file is missing or unreadable.
    """
    if not registry_path.exists():
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[commons.identity] Unreadable registry {registry_path.name}: {exc}")
        return []

    raw_branches = registry.get("branches", [])
    if isinstance(raw_branches, dict):
        raw_branches = list(raw_branches.values())
    if not isinstance(raw_branches, list):
        logger.warning(f"[commons.identity] Registry {registry_path.name} has a malformed branches field")
        return []

    return [branch for branch in raw_branches if isinstance(branch, dict)]


def _match_by_path(registry_path: Path, branch_path: Path) -> Optional[Dict[str, Any]]:
    """Find the branch in this registry whose path is branch_path."""
    target = str(branch_path.resolve())
    registry_root = registry_path.parent

    for branch in _branches_from_registry(registry_path):
        raw_path = branch.get("path", "")
        if not raw_path:
            continue
        # Registry paths are relative to the registry file's own directory
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = registry_root / candidate
        if str(candidate.resolve()) == target:
            return branch

    return None


def _match_by_name(registry_path: Path, branch_name: str) -> Optional[Dict[str, Any]]:
    """Find the branch in this registry named branch_name (case-insensitive)."""
    name_upper = branch_name.upper()

    for branch in _branches_from_registry(registry_path):
        if branch.get("name", "").upper() == name_upper:
            return branch

    return None


def _search_registries(matcher: Callable[[Path], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """
    Run a matcher against the AIPass registry, then the caller's own.

    AIPass citizens resolve on the first lookup and never pay for the
    walk-up. External citizens — a whole project's worth of branches with
    passports and mailboxes that the AIPass registry has never heard of —
    resolve on the fallback instead of falling through to None.

    Args:
        matcher: Callable taking a registry path, returning a branch dict.

    Returns:
        The first branch dict any registry matched, or None.
    """
    found = matcher(BRANCH_REGISTRY_PATH)
    if found:
        return found

    for registry_path in _find_caller_registries():
        found = matcher(registry_path)
        if found:
            logger.info(
                f"[commons.identity] Resolved external citizen "
                f"'{found.get('name', 'unknown')}' via {registry_path.name}"
            )
            return found

    return None


def get_branch_info_from_registry(branch_path: Path) -> Optional[Dict[str, Any]]:
    """
    Look up branch information by path, AIPass registry first.

    Falls back to the caller's project registry so external citizens are
    identifiable in The Commons.

    Args:
        branch_path: Path to branch directory.

    Returns:
        Dict with branch info from registry, or None if not found.
    """
    return _search_registries(lambda registry_path: _match_by_path(registry_path, branch_path))


def get_branch_info_by_name(branch_name: str) -> Optional[Dict[str, Any]]:
    """
    Look up branch information by name, AIPass registry first.

    Falls back to the caller's project registry so external citizens are
    identifiable in The Commons.

    Args:
        branch_name: Branch name to look up (case-insensitive).

    Returns:
        Dict with branch info from registry, or None if not found.
    """
    return _search_registries(lambda registry_path: _match_by_name(registry_path, branch_name))


def get_caller_branch() -> Optional[Dict[str, Any]]:
    """
    Detect which branch is calling The Commons.

    Detection order:
    1. AIPASS_CALLER_CWD env var (set by drone) — walk up to find .trinity/
    2. Current working directory — walk up to find .trinity/
    3. AIPASS_CALLER_BRANCH env var (set by drone) — direct name lookup

    Auto-registers the branch as a Commons agent if not already present.

    Returns:
        Dict with branch info {"name": "SEED", "path": "...", "email": "@seed", ...}
        or None if no branch detected.
    """
    try:
        # Strategy 1 & 2: Walk up from CWD to find branch root
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
        cwd = Path(caller_cwd) if caller_cwd else Path.cwd()
        branch_root = find_branch_root(cwd)

        if branch_root:
            branch_info = get_branch_info_from_registry(branch_root)
            if branch_info:
                _normalize_branch_name(branch_info)
                _ensure_agent_registered(branch_info)
                json_handler.log_operation("caller_detected", {"branch": branch_info.get("name", "unknown")})
                return branch_info

        # Strategy 3: Use AIPASS_CALLER_BRANCH env var (drone sets this)
        caller_branch_name = os.environ.get("AIPASS_CALLER_BRANCH", "")
        if caller_branch_name:
            branch_info = get_branch_info_by_name(caller_branch_name)
            if branch_info:
                _normalize_branch_name(branch_info)
                _ensure_agent_registered(branch_info)
                json_handler.log_operation(
                    "caller_detected", {"branch": branch_info.get("name", "unknown"), "via": "AIPASS_CALLER_BRANCH"}
                )
                return branch_info

        logger.warning(
            "[commons.identity] Could not detect calling branch — run from a branch directory or use drone routing"
        )
        return None

    except Exception as e:
        logger.error(f"[commons.identity] Branch detection failed: {e}")
        return None


def _normalize_branch_name(branch_info: Dict[str, Any]) -> None:
    """
    Lowercase the branch name so Commons identity is case-canonical.

    The AIPASS registry has historically used mixed casing for branch names
    (e.g. BACKUP vs devpulse), and both the agents roster and post authorship
    mirror whatever casing the registry supplies. get_caller_branch() is the
    single choke point every caller identity flows through (post/comment author
    writes, agent registration), so normalizing here keeps one branch = one
    identity regardless of registry casing — no DEVPULSE/devpulse splits.

    Args:
        branch_info: Branch dict from the registry (mutated in place).
    """
    name = branch_info.get("name")
    if isinstance(name, str) and name:
        branch_info["name"] = name.lower()


def _ensure_agent_registered(branch_info: Dict[str, Any]) -> None:
    """
    Ensure the branch is registered as an agent in The Commons database.

    Args:
        branch_info: Branch dict from BRANCH_REGISTRY.
    """
    try:
        from aipass.commons.apps.handlers.database.db import get_db, close_db

        name = branch_info.get("name", "")
        if not name:
            return

        conn = get_db()

        existing = conn.execute("SELECT branch_name FROM agents WHERE branch_name = ?", (name,)).fetchone()

        if not existing:
            display_name = name.replace("_", " ").title()
            description = branch_info.get("description", "")
            conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name, description) VALUES (?, ?, ?)",
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
        from aipass.commons.apps.handlers.database.db import get_db, close_db

        conn = get_db()
        placeholders = ",".join("?" * len(mentioned))
        query = f"SELECT DISTINCT LOWER(branch_name) FROM agents WHERE LOWER(branch_name) IN ({placeholders})"
        rows = conn.execute(query, mentioned).fetchall()
        close_db(conn)

        valid_mentions = [row[0] for row in rows]
        return valid_mentions

    except Exception as e:
        logger.warning(f"[commons.identity] Mention extraction failed: {e}")
        return []
