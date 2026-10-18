# =================== AIPass ====================
# Name: identity_ops.py
# Description: Identity operations handler
# Version: 1.6.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Identity Operations Handler
"""

import os
import re
import json
from pathlib import Path
from typing import Callable, Dict, Any, Iterator, Optional, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.handlers.module_root import module_file


def _find_branch_registry_path() -> Path:
    """Locate AIPASS_REGISTRY.json by searching standard paths (the result may not exist)."""
    aipass_root = os.environ.get("AIPASS_ROOT", "")
    if aipass_root:
        candidate = Path(aipass_root) / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate

    # module_file(), not a bare .resolve(): this runs at module scope, and on
    # Windows a bare resolve would read cwd at import time.
    current = module_file(__file__).parent
    for _ in range(10):
        candidate = current / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    for candidate_path in [
        Path.home() / ".aipass" / "AIPASS_REGISTRY.json",
        Path.home() / "AIPASS_REGISTRY.json",
    ]:
        if candidate_path.exists():
            return candidate_path

    return Path.home() / "AIPASS_REGISTRY.json"


BRANCH_REGISTRY_PATH = _find_branch_registry_path()


class CallerLookupFailed(RuntimeError):
    """The caller lookup broke; never returned as None, which means "no branch detected"."""


def find_branch_root(start_path: Path) -> Optional[Path]:
    """Walk up from start_path to the nearest directory holding .trinity/passport.json, or None."""
    current = start_path.resolve()

    for _ in range(10):
        if (current / ".trinity" / "passport.json").exists():
            return current

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def list_registry_candidates(directory: Path) -> Iterator[Path]:
    """
    List the *_REGISTRY.json candidates in one directory (single level).

    A test seam: test_identity replaces it to emulate a case-insensitive filesystem;
    patching Path.glob instead would widen every glob in the pytest process.
    """
    return directory.glob("*_REGISTRY.json")


def _find_caller_registries() -> List[Path]:
    """
    Find the registries belonging to the caller's own project.

    Sorted so a directory holding several registries always resolves the same way.
    Raises OSError when AIPASS_CALLER_CWD will not resolve: [] would let the lookup
    fall through by name and serve an AIPass namesake's identity.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return []

    try:
        caller_path = Path(caller_cwd).resolve()
    except OSError as exc:
        logger.warning(f"[commons.identity] Unusable AIPASS_CALLER_CWD '{caller_cwd}': {exc}")
        raise

    primary = BRANCH_REGISTRY_PATH.resolve() if BRANCH_REGISTRY_PATH.exists() else None

    for directory in [caller_path] + list(caller_path.parents):
        matches = sorted(
            path
            for path in list_registry_candidates(directory)
            # Case-insensitive filesystems also glob *_registry.json (plan counters,
            # dotfiles): re-check the SUFFIX only; vera_studio_REGISTRY.json is real.
            if path.name.endswith("_REGISTRY.json")
            and path.name != "AIPASS_REGISTRY.json"
            and path.resolve() != primary
        )
        if matches:
            return matches

    return []


def _branches_from_registry(registry_path: Path) -> List[Dict[str, Any]]:
    """
    Read the branches list out of a registry file ([] only when the file is missing).

    Unreadable or malformed registries raise: [] reads as "no match" and would
    serve the AIPass namesake by name.
    """
    if not registry_path.exists():
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[commons.identity] Unreadable registry {registry_path.name}: {exc}")
        raise

    raw_branches = registry.get("branches", [])
    if isinstance(raw_branches, dict):
        raw_branches = list(raw_branches.values())
    if not isinstance(raw_branches, list):
        malformed = f"Registry {registry_path.name} has a malformed branches field"
        logger.warning(f"[commons.identity] {malformed}")
        raise ValueError(malformed)

    for index, branch in enumerate(raw_branches):
        if not isinstance(branch, dict):
            malformed = f"Registry {registry_path.name} has a malformed branch entry at index {index}"
            logger.warning(f"[commons.identity] {malformed}")
            raise ValueError(malformed)

    return raw_branches


def _match_by_path(registry_path: Path, branch_path: Path) -> Optional[Dict[str, Any]]:
    """Find the branch in this registry whose path is branch_path."""
    target = str(branch_path.resolve())
    registry_root = registry_path.parent

    for branch in _branches_from_registry(registry_path):
        raw_path = branch.get("path", "")
        if not raw_path:
            continue
        # Registry paths are relative to the registry file's own directory.
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
    """Run a matcher against the AIPass registry, then the caller's own project registries."""
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
    """Look up branch information by path, AIPass registry first."""
    return _search_registries(lambda registry_path: _match_by_path(registry_path, branch_path))


def get_branch_info_by_name(branch_name: str) -> Optional[Dict[str, Any]]:
    """Look up branch information by name (case-insensitive), AIPass registry first."""
    return _search_registries(lambda registry_path: _match_by_name(registry_path, branch_name))


def get_caller_branch() -> Optional[Dict[str, Any]]:
    """Detect and auto-register the calling branch; CallerLookupFailed when the lookup breaks."""
    try:
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
        raise CallerLookupFailed(f"Caller lookup failed: {e}") from e


def _normalize_branch_name(branch_info: Dict[str, Any]) -> None:
    """
    Lowercase the branch name so Commons identity is case-canonical.

    The registry mixes casings; every caller identity flows through get_caller_branch,
    so normalizing here keeps one branch = one identity (no DEVPULSE/devpulse split).
    """
    name = branch_info.get("name")
    if isinstance(name, str) and name:
        branch_info["name"] = name.lower()


def _ensure_agent_registered(branch_info: Dict[str, Any]) -> None:
    """Ensure the branch is registered as an agent in The Commons database."""
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
    """Resolve a branch name to "Alias (SYSTEM)", the bare alias when compact, else branch_name."""
    cache = _load_alias_cache()
    alias = cache.get(branch_name, "")
    if not alias:
        return branch_name
    if compact:
        return alias
    return f"{alias} ({branch_name})"


def extract_mentions(content: str) -> Optional[List[str]]:
    """Extract registered @mention names, lowercased; None (not []) when the agents lookup broke."""
    if not content:
        return []

    pattern = r"@(\w+)"
    matches = re.findall(pattern, content)

    if not matches:
        return []

    mentioned = [m.lower() for m in matches]

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
        return None
