# =================== AIPass ====================
# Name: placeholders.py
# Description: Placeholder replacement engine
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-13
# =============================================

"""Placeholder replacement engine for agent templates."""

import json
import re
from datetime import datetime
from pathlib import Path

from aipass.spawn.apps.handlers.registry import find_registry


def replace_placeholders(content, replacements):
    """Replace {{PLACEHOLDER}} patterns in content string."""
    for placeholder, value in replacements.items():
        content = content.replace("{{" + placeholder + "}}", str(value))
    return content


def build_replacements_dict(target_dir, branch_name, **overrides):
    """
    Build the full placeholder -> value mapping.

    Args:
        target_dir: Path to target directory
        branch_name: Raw folder name
        **overrides: Optional overrides for ROLE, TRAITS, PURPOSE_BRIEF, PROFILE,
                     CITIZEN_NUMBER, MODULE, etc.

    Returns:
        Dict mapping placeholder names to replacement values
    """
    upper = branch_name.upper().replace("-", "_")
    lower = branch_name.lower().replace("-", "_")
    now = datetime.now()

    # Read registry ID — never crash spawn if registry is missing
    registry_id = ""
    try:
        registry_path = find_registry()
        if registry_path.exists():
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            registry_id = data.get("metadata", {}).get("id", "")
    except Exception:
        registry_id = ""

    replacements = {
        "BRANCHNAME": upper,
        "branchname": lower,
        "BRANCH": lower,
        "CWD": str(target_dir),
        "DATE": now.strftime("%Y-%m-%d"),
        "MODULE": lower,
        "EMAIL": f"@{lower}",
        "PROFILE": overrides.get("profile", "AIPass Workshop"),
        "ROLE": overrides.get("role", ""),
        "TRAITS": overrides.get("traits", ""),
        "PURPOSE_BRIEF": overrides.get("purpose", "New agent - purpose TBD"),
        "CITIZEN_NUMBER": str(overrides.get("citizen_number", 0)),
        "REGISTRY_ID": registry_id,
        "KEY_CAPABILITIES": "",
        "DEPENDS_ON": "",
        "PROVIDES_TO": "",
    }

    return replacements


def validate_no_placeholders(target_dir):
    """
    Scan all text files in target_dir for unreplaced {{X}} patterns.

    Returns:
        List of (file_path, list_of_placeholders) tuples. Empty if clean.
    """
    pattern = re.compile(r"\{\{([^}]+)\}\}")
    issues = []

    for file_path in Path(target_dir).rglob("*"):
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue

        found = pattern.findall(content)
        if found:
            issues.append((str(file_path), list(set(found))))

    return issues
