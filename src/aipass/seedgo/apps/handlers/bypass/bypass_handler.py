# =================== AIPass ====================
# Name: bypass_handler.py
# Description: Bypass Configuration Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Bypass Configuration Handler

Handles file I/O for the .seedgo/bypass.json configuration system.
Reads registry, loads bypass rules, ensures config files exist.

Returns dicts, NEVER prints.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


# =============================================================================
# CONSTANTS
# =============================================================================

BYPASS_TEMPLATE = {
    "metadata": {"version": "1.0.0", "created": "", "description": "Standards bypass configuration for this branch"},
    "bypass": [],
    "notes": {
        "usage": "Add entries to 'bypass' list to exclude specific violations",
        "example": {
            "file": "apps/modules/logger.py",
            "standard": "cli",
            "lines": [146, 177],
            "pattern": "if __name__ == '__main__'",
            "reason": "Circular dependency - logger cannot import CLI",
        },
        "fields": {
            "file": "Relative path from branch root (required)",
            "standard": "Standard name: cli, imports, naming, etc. (required)",
            "lines": "Optional - specific line numbers to bypass",
            "pattern": "Optional - pattern to match (e.g. 'if __name__')",
            "reason": "Required - why this bypass exists",
        },
    },
}


# =============================================================================
# REGISTRY DISCOVERY
# =============================================================================


def _find_registry() -> Path:
    """Find AIPASS_REGISTRY.json by walking up from this file's location."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        candidate = parent / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
    return Path.cwd() / "AIPASS_REGISTRY.json"


REGISTRY_PATH = _find_registry()


# =============================================================================
# PUBLIC API
# =============================================================================


def get_branch_from_path(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Detect which branch a file belongs to using AIPASS_REGISTRY.

    Args:
        file_path: Absolute path to file being checked

    Returns:
        Branch dict with name, path, etc. or None if not in a branch
    """
    try:
        if not REGISTRY_PATH.exists():
            logger.warning("[bypass_handler] AIPASS_REGISTRY.json not found")
            return None

        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)

        file_path = str(Path(file_path).resolve())

        # Sort branches by path length (longest first) to match most specific
        branches = sorted(registry.get("branches", []), key=lambda b: len(b.get("path", "")), reverse=True)

        for branch in branches:
            branch_path = branch.get("path", "")
            if file_path.startswith(branch_path + "/") or file_path == branch_path:
                return branch

        return None
    except Exception as e:
        logger.error(f"[bypass_handler] Error reading AIPASS_REGISTRY: {e}")
        return None


def ensure_seedgo_config(branch_path: str) -> Path:
    """
    Ensure .seedgo/bypass.json exists for a branch, create if missing.

    Args:
        branch_path: Path to branch root

    Returns:
        Path to bypass.json file
    """
    seedgo_dir = Path(branch_path) / ".seedgo"
    bypass_file = seedgo_dir / "bypass.json"

    try:
        # Create .seedgo directory if needed
        seedgo_dir.mkdir(exist_ok=True)

        # Create bypass.json if missing
        if not bypass_file.exists():
            template = BYPASS_TEMPLATE.copy()
            template["metadata"]["created"] = datetime.now().isoformat()

            with open(bypass_file, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=2)

            logger.info(f"[bypass_handler] Created {bypass_file}")

        return bypass_file
    except Exception as e:
        logger.error(f"[bypass_handler] Error creating seedgo config: {e}")
        return bypass_file


def load_bypass_rules(branch_path: str) -> List[Dict[str, Any]]:
    """
    Load bypass rules from branch's .seedgo/bypass.json.

    Args:
        branch_path: Path to branch root

    Returns:
        List of bypass rule dicts
    """
    bypass_file = ensure_seedgo_config(branch_path)

    try:
        if bypass_file.exists():
            with open(bypass_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            rules = config.get("bypass", [])
            json_handler.log_operation("bypass_rules_loaded", {"branch": branch_path, "count": len(rules)})
            return rules
    except Exception as e:
        logger.error(f"[bypass_handler] Error loading bypass rules: {e}")

    return []


def is_bypassed(file_path: str, branch_path: str, standard: str, line: Optional[int], bypass_rules: List[Dict]) -> bool:
    """
    Check if a specific violation should be bypassed.

    Args:
        file_path: Absolute path to file
        branch_path: Path to branch root
        standard: Standard name (cli, imports, etc.)
        line: Line number of violation (optional)
        bypass_rules: List of bypass rules

    Returns:
        True if this violation should be bypassed
    """
    # Get relative path from branch root
    try:
        rel_path = str(Path(file_path).relative_to(branch_path))
    except ValueError:
        logger.info("File %s not relative to branch %s, using raw path", file_path, branch_path)
        rel_path = file_path

    for rule in bypass_rules:
        # Check if rule matches this file and standard
        rule_file = rule.get("file", "")
        rule_standard = rule.get("standard", "")

        if rule_file and rule_file != rel_path:
            continue
        if rule_standard and rule_standard != standard:
            continue

        # Check line-specific bypass
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None:
            if line in rule_lines:
                return True
        elif not rule_lines:
            # No line restriction - bypass all violations for this file/standard
            return True

    return False
