# =================== AIPass ====================
# Name: readme_ops.py
# Description: README Update Operations Handler
# Version: 1.1.1
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
README Update Operations Handler
"""

import json
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.module_root import module_file


def _find_registry() -> Path:
    """Find *_REGISTRY.json — CWD-first for external project support, then __file__ fallback."""
    return registry_scan.find_registry()


GENERATOR_PATH = module_file(__file__).parent / "readme_generator.py"

SECTION_NAMES = {
    "tree": "TREE",
    "modules": "MODULES",
    "commands": "COMMANDS",
    "header": "HEADER",
    "last_updated": "LAST_UPDATED",
}


def resolve_branch(branch_arg: str) -> Optional[Dict]:
    """Resolve @branch argument to branch info from registry.

    Raises OSError/ValueError on an unreadable registry: None means an unknown branch."""
    name = branch_arg.lstrip("@").upper()

    for branch in _load_branches():
        if branch.get("name", "").upper() == name:
            return branch
        aliases = branch.get("aliases", [])
        for alias in aliases:
            if alias.lstrip("@").upper() == name:
                return branch

    return None


def get_all_branches() -> List[Dict]:
    """Get all branches from the registry.

    Raises OSError/ValueError on an unreadable registry: [] means no registry."""
    return _load_branches()


def _load_branches() -> List[Dict]:
    """Registry branches with relative paths anchored at the registry's directory, not the CWD."""
    registry_path = _find_registry()
    if not registry_path.exists():
        return []
    branches = json.loads(registry_path.read_text(encoding="utf-8")).get("branches", [])
    for branch in branches:
        if branch.get("path"):
            branch["path"] = str((registry_path.parent / branch["path"]).resolve())
    return branches


def load_generator():
    """Load readme_generator module via importlib to avoid cross-branch import issues.

    None only when the file is absent; a load failure raises so its reason reaches the user."""
    if not GENERATOR_PATH.exists():
        return None

    spec = importlib.util.spec_from_file_location("readme_generator", str(GENERATOR_PATH))
    if spec is None or spec.loader is None:
        raise ImportError(f"no loader for {GENERATOR_PATH}")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


def resolve_targets(args: List[str]) -> tuple:
    """Resolve command arguments to a list of branch targets.

    Errors are "no_args", "no_branches", "not_found:<target>" or "unreadable_registry:<reason>"."""
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
