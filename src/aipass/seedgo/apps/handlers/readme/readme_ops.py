# =================== AIPass ====================
# Name: readme_ops.py
# Description: README Update Operations Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-09-29
# =============================================

"""
README Update Operations Handler

Implementation details for the readme_update module. Handles branch resolution,
generator loading, and target resolution. Returns data structures for the
module to display.
"""

import json
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.module_root import module_file

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# CONSTANTS
# =============================================================================


def _find_registry() -> Path:
    """Find *_REGISTRY.json — CWD-first for external project support, then __file__ fallback."""
    # Delegates: the name is the contract, the private glob walk was the disease.
    # parent.glob("*_REGISTRY.json") folds case on Windows and default macOS, so
    # a flow_json plan counter could be served as the trust anchor.
    return registry_scan.find_registry()


# Generator lives in the same handlers/readme/ directory as this file
GENERATOR_PATH = module_file(__file__).parent / "readme_generator.py"

# Section display names for output
SECTION_NAMES = {
    "tree": "TREE",
    "modules": "MODULES",
    "commands": "COMMANDS",
    "header": "HEADER",
    "last_updated": "LAST_UPDATED",
}


# =============================================================================
# BRANCH RESOLUTION
# =============================================================================


def resolve_branch(branch_arg: str) -> Optional[Dict]:
    """
    Resolve @branch argument to branch info from registry.

    Args:
        branch_arg: Branch name, optionally prefixed with @

    Returns:
        Branch dict from registry, or None if not found

    Raises:
        OSError, ValueError: the registry exists and cannot be read. An
            unreadable registry answered None, the answer for an unknown
            branch (seedgo, fleet green leg 5); resolve_targets names it.
    """
    registry_path = _find_registry()
    if not registry_path.exists():
        return None

    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    # Strip @ prefix and normalize
    name = branch_arg.lstrip("@").upper()

    for branch in registry.get("branches", []):
        if branch.get("name", "").upper() == name:
            return branch
        # Also check aliases
        aliases = branch.get("aliases", [])
        for alias in aliases:
            if alias.lstrip("@").upper() == name:
                return branch

    return None


def get_all_branches() -> List[Dict]:
    """
    Get all branches from the registry.

    Returns:
        List of branch dicts, or an empty list when there is no registry

    Raises:
        OSError, ValueError: the registry exists and cannot be read. It
            answered an empty list, the answer for an empty registry (seedgo,
            fleet green leg 5); resolve_targets names it.
    """
    registry_path = _find_registry()
    if not registry_path.exists():
        return []

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return registry.get("branches", [])


# =============================================================================
# GENERATOR LOADER
# =============================================================================


def load_generator():
    """
    Load readme_generator module via importlib to avoid cross-branch import issues.

    Returns:
        The readme_generator module, or None when the file is not there

    Raises:
        Whatever loading the file raises (a SyntaxError, an ImportError, an
        OSError). It answered None with the reason at info level only, so the
        user read "Failed to load" and nothing more (seedgo, fleet green leg 5).
    """
    if not GENERATOR_PATH.exists():
        return None

    spec = importlib.util.spec_from_file_location("readme_generator", str(GENERATOR_PATH))
    if spec is None or spec.loader is None:
        raise ImportError(f"no loader for {GENERATOR_PATH}")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


# =============================================================================
# TARGET RESOLUTION
# =============================================================================


def resolve_targets(args: List[str]) -> tuple:
    """
    Resolve command arguments to a list of branch targets.

    Handles @all, @branch, and bare branch names.

    Args:
        args: List of branch arguments

    Returns:
        Tuple of (branches_list, error_message).
        On success: (list_of_dicts, None)
        On failure: ([], error_string): "no_args", "no_branches",
        "not_found:<target>", or "unreadable_registry:<reason>" when the
        registry exists and cannot be read.
    """
    if not args:
        return [], "no_args"

    target = args[0]
    json_handler.log_operation("readme_ops_executed", {"target": target})

    try:
        if target.lstrip("@").lower() == "all":
            branches = get_all_branches()
            return (branches, None) if branches else ([], "no_branches")
        branch = resolve_branch(target)
    except (OSError, ValueError) as exc:
        logger.error("Registry unreadable for readme targets: %s", exc)
        return [], f"unreadable_registry:{exc}"

    if not branch:
        return [], f"not_found:{target}"

    return [branch], None
