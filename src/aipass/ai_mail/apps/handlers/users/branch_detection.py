# =================== AIPass ====================
# Name: branch_detection.py
# Description: Branch Auto-Detection Handler
# Version: 1.0.0
# Created: 2025-11-18
# Modified: 2025-11-18
# =============================================

"""
Branch Auto-Detection Handler

Detects which branch is calling AI_MAIL based on PWD/CWD.
Walks up directory tree to find branch root (has .trinity/passport.json).
"""

# =============================================
# IMPORTS
# =============================================
import os
import json
from pathlib import Path
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

# =============================================
# CONSTANTS
# =============================================
BRANCH_REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"


def _get_contact_info(branch_name: str) -> Optional[Dict]:
    """Look up branch info from the contacts address book.

    Fastest path for sender detection — works for external projects that
    have previously registered via contacts, bypassing registry/CWD walk.

    Args:
        branch_name: Branch name or email (e.g., 'devpulse' or '@devpulse').

    Returns:
        Synthetic branch info dict compatible with registry format, or None.
    """
    try:
        from aipass.ai_mail.apps.handlers.email.contacts import get_contact

        contact = get_contact(branch_name)
        if not contact:
            return None
        inbox_path = Path(contact["inbox"])
        branch_path = inbox_path.parent.parent  # .ai_mail.local -> branch root
        name_key = branch_name.lstrip("@").lower()
        return {
            "name": name_key.upper(),
            "email": "@" + name_key,
            "path": str(branch_path),
            "project": contact.get("project", ""),
        }
    except Exception as e:
        logger.warning("[identity] _get_contact_info(%s) failed: %s", branch_name, e)
        return None


def _find_caller_registry() -> Optional[Path]:
    """Find the caller's AIPASS_REGISTRY.json by walking up from AIPASS_CALLER_CWD.

    Used to resolve external project branches that aren't in the AIPass registry.
    Skips the AIPass registry itself to avoid redundant double-lookup.

    Returns:
        Path to the caller's registry file, or None if not found or same as main registry.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return None
    candidate = Path(caller_cwd)
    aipass_registry = BRANCH_REGISTRY_PATH.resolve()
    for path in [candidate] + list(candidate.parents)[:10]:
        registry = path / "AIPASS_REGISTRY.json"
        if registry.exists():
            try:
                if registry.resolve() != aipass_registry:
                    return registry
            except Exception as e:
                logger.warning("[identity] _find_caller_registry() resolve failed for %s: %s", registry, e)
    return None


def _get_branches_list(registry: dict) -> list:
    """Normalize branches from registry to a list of dicts.

    Handles both formats:
    - List: [{"name": "DEVPULSE", ...}, ...]
    - Dict: {"devpulse": {"name": "devpulse", ...}, ...}
    """
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        return list(branches.values())
    return branches


# =============================================
# BRANCH DETECTION FUNCTIONS
# =============================================


def detect_branch_from_pwd() -> Optional[Dict]:
    """
    Detect which branch is calling based on current working directory.

    Walks up directory tree from PWD to find branch root (directory with .trinity/passport.json).
    Then looks up branch info in AIPASS_REGISTRY.json.

    Returns:
        Dict with branch info if detected:
        {
            "name": "SEEDGO",
            "path": "src/aipass/seedgo",
            "email": "@seedgo",
            "display_name": "Seedgo (Standards Branch)",
            ...
        }
        None if no branch detected
    """
    json_handler.log_operation("detect_branch_from_pwd", {"cwd": str(Path.cwd())})

    try:
        # Primary: use explicit branch name passed by drone (works in Docker + local)
        caller_branch = os.environ.get("AIPASS_CALLER_BRANCH")
        if caller_branch:
            # Try contacts first (fastest, works for external projects)
            contact = _get_contact_info(caller_branch)
            if contact:
                return contact
            # Fall back to registry lookup
            branch_info = _lookup_branch_by_name(caller_branch)
            if branch_info:
                return branch_info
            # Last resort: synthesize from env vars (external project, first contact)
            caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
            if caller_cwd:
                cwd_path = Path(caller_cwd)
                name_key = caller_branch.lstrip("@").lower()
                mailbox = cwd_path / ".ai_mail.local"
                if not mailbox.exists():
                    # Walk up to find project-level mailbox
                    for parent in [cwd_path] + list(cwd_path.parents):
                        candidate = parent / ".ai_mail.local"
                        if candidate.exists():
                            mailbox = candidate
                            break
                return {
                    "name": name_key,
                    "path": str(cwd_path),
                    "email": f"@{name_key}",
                    "status": "active",
                    "type": "external",
                }

        # Fallback: use caller's CWD for path-based detection (local only)
        caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
        cwd = Path(caller_cwd) if caller_cwd else Path.cwd()

        # Find branch root
        branch_root = find_branch_root(cwd)
        if not branch_root:
            return None

        # Get branch info from registry
        branch_info = get_branch_info_from_registry(branch_root)
        if not branch_info:
            return None

        return branch_info

    except Exception as e:
        logger.warning("[identity] detect_branch_from_pwd() failed: %s", e)
        return None


def _lookup_branch_by_name(branch_name: str) -> Optional[Dict]:
    """
    Look up branch in the registry by name (case-insensitive).

    Handles both registry formats:
    - List format: {"branches": [{"name": "DEVPULSE", ...}, ...]}
    - Dict format: {"branches": {"devpulse": {"name": "devpulse", ...}, ...}}

    Args:
        branch_name: Branch name (e.g., "DEVPULSE", "devpulse")

    Returns:
        Dict with branch info from registry, or None if not found
    """
    name_lower = branch_name.lower()

    if BRANCH_REGISTRY_PATH.exists():
        try:
            with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for branch in _get_branches_list(registry):
                if branch.get("name", "").lower() == name_lower:
                    return branch
        except Exception as e:
            logger.warning("[identity] _lookup_branch_by_name(%s) failed: %s", branch_name, e)

    # Fallback: caller's registry (external project branches not in AIPass registry)
    caller_registry = _find_caller_registry()
    if caller_registry:
        try:
            with open(caller_registry, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for branch in _get_branches_list(registry):
                if branch.get("name", "").lower() == name_lower:
                    return branch
        except Exception as e:
            logger.warning(
                "[identity] _lookup_branch_by_name(%s) caller registry %s failed: %s", branch_name, caller_registry, e
            )

    return None


def find_branch_root(start_path: Path) -> Optional[Path]:
    """
    Walk up directory tree to find branch root.

    Branch root = directory containing .trinity/passport.json.
    Example: src/aipass/seedgo/ contains .trinity/passport.json

    Args:
        start_path: Directory to start searching from (usually PWD)

    Returns:
        Path to branch root directory, or None if not found
    """
    current = start_path.resolve()

    # Walk up directory tree (max 10 levels to prevent infinite loop)
    for _ in range(10):
        # Check for .trinity/passport.json (AIPass identity pattern)
        if (current / ".trinity" / "passport.json").exists():
            return current

        # Move up one level
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    return None


def get_branch_info_from_registry(branch_path: Path) -> Optional[Dict]:
    """
    Look up branch information in AIPASS_REGISTRY.json by path.

    Args:
        branch_path: Path to branch directory

    Returns:
        Dict with branch info from registry, or None if not found
    """
    branch_path_resolved = branch_path.resolve()

    if BRANCH_REGISTRY_PATH.exists():
        try:
            with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
                registry = json.load(f)
            registry_dir = BRANCH_REGISTRY_PATH.parent
            for branch in _get_branches_list(registry):
                reg_path = Path(branch["path"])
                if not reg_path.is_absolute():
                    reg_path = (registry_dir / reg_path).resolve()
                else:
                    reg_path = reg_path.resolve()
                if reg_path == branch_path_resolved:
                    return branch
        except Exception as e:
            logger.warning("[identity] get_branch_info_from_registry(%s) failed: %s", branch_path, e)

    # Fallback: caller's registry (external project branches not in AIPass registry)
    caller_registry = _find_caller_registry()
    if caller_registry:
        try:
            with open(caller_registry, "r", encoding="utf-8") as f:
                registry = json.load(f)
            registry_dir = caller_registry.parent
            for branch in _get_branches_list(registry):
                reg_path = Path(branch["path"])
                if not reg_path.is_absolute():
                    reg_path = (registry_dir / reg_path).resolve()
                else:
                    reg_path = reg_path.resolve()
                if reg_path == branch_path_resolved:
                    return branch
        except Exception as e:
            logger.warning("[identity] get_branch_info_from_registry(%s) caller registry failed: %s", branch_path, e)

    return None


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("BRANCH AUTO-DETECTION HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Detects which branch is calling AI_MAIL based on PWD/CWD")
    console.print("  Walks up directory tree to find branch root")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - detect_branch_from_pwd() -> Optional[Dict]")
    console.print("  - find_branch_root(start_path) -> Optional[Path]")
    console.print("  - get_branch_info_from_registry(branch_path) -> Optional[Dict]")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  ✓ Independent - no module dependencies")
    console.print("  ✓ Can import Prax (service provider)")
    console.print("  ✓ Pure business logic")
    console.print("  ✗ CANNOT import parent modules")
    console.print()
    console.print("DETECTION FLOW:")
    console.print("  1. Get current working directory (PWD)")
    console.print("  2. Walk up tree to find .trinity/passport.json")
    console.print("  3. Look up branch path in AIPASS_REGISTRY.json")
    console.print("  4. Return branch info (name, email, path, etc.)")
    console.print()
    console.print("=" * 70 + "\n")
