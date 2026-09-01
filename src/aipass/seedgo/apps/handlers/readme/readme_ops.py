# =================== AIPass ====================
# Name: readme_ops.py
# Description: README Update Operations Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
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
    """
    registry_path = _find_registry()
    if not registry_path.exists():
        return None

    try:
        content = registry_path.read_text(encoding="utf-8")
        registry = json.loads(content)
    except (json.JSONDecodeError, OSError):
        logger.info("Cannot read registry for branch resolution: %s", registry_path)
        return None

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
        List of branch dicts, or empty list on failure
    """
    registry_path = _find_registry()
    if not registry_path.exists():
        return []

    try:
        content = registry_path.read_text(encoding="utf-8")
        registry = json.loads(content)
        return registry.get("branches", [])
    except (json.JSONDecodeError, OSError):
        logger.info("Cannot read registry for branch listing: %s", registry_path)
        return []


# =============================================================================
# GENERATOR LOADER
# =============================================================================


def load_generator():
    """
    Load readme_generator module via importlib to avoid cross-branch import issues.

    Returns:
        The readme_generator module, or None on failure
    """
    if not GENERATOR_PATH.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location("readme_generator", str(GENERATOR_PATH))
        if spec is None or spec.loader is None:
            return None
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        return generator
    except Exception:
        logger.info("Failed to load readme generator module")
        return None


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
        On failure: ([], error_string)
    """
    if not args:
        return [], "no_args"

    target = args[0]
    json_handler.log_operation("readme_ops_executed", {"target": target})

    # Handle @all
    if target.lstrip("@").lower() == "all":
        branches = get_all_branches()
        if not branches:
            return [], "no_branches"
        return branches, None

    # Handle specific branch
    branch = resolve_branch(target)
    if not branch:
        return [], f"not_found:{target}"

    return [branch], None
