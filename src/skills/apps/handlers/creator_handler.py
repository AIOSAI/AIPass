# =================== AIPass ====================
# Name: creator_handler.py
# Description: Skill creation handler
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Skill Creation Handler

Contains the core logic for creating new skills from templates.
Validates skill names, resolves templates, and orchestrates the copy.

Purpose:
    Implementation logic for skill creation, separated from CLI/display
    layer to satisfy thin-module standard.
"""

from pathlib import Path

from aipass.prax import logger
from skills.apps.handlers.json import json_handler
from skills.apps.handlers.template import copy_template, get_template

# logger imported from aipass.prax


def is_valid_name(name):
    """Check if a skill name is valid.

    Valid names contain only lowercase letters, numbers, and hyphens.
    Must start with a letter.

    Args:
        name: The skill name to validate.

    Returns:
        bool: True if valid.
    """
    if not name or not name[0].isalpha():
        return False
    return all(c.isalnum() or c in "-_" for c in name) and name == name.lower()


def create_skill(name, template_type="markdown_only", target_dir=None):
    """Create a new skill from a template.

    Args:
        name: Name for the new skill (used as directory name and placeholder).
        template_type: Template tier - "markdown_only", "with_handler", or "full".
        target_dir: Directory to create the skill in. Defaults to
                    .aipass/skills/ in the current working directory.

    Returns:
        dict: {"success": bool, "path": str|None, "files": list[str], "error": str|None}
    """
    # Validate skill name
    if not name:
        return {
            "success": False,
            "path": None,
            "files": [],
            "error": "Skill name is required.",
        }

    if not is_valid_name(name):
        return {
            "success": False,
            "path": None,
            "files": [],
            "error": f"Invalid skill name: '{name}'. Use lowercase letters, numbers, and hyphens only.",
        }

    # Resolve template
    template_result = get_template(template_type)
    if not template_result["success"]:
        return {
            "success": False,
            "path": None,
            "files": [],
            "error": template_result["error"],
        }

    # Determine target directory
    if target_dir is None:
        target_dir = Path.cwd() / ".aipass" / "skills"

    target_path = Path(target_dir) / name

    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy template
    result = copy_template(template_result["path"], target_path, name)

    json_handler.log_operation("skill_scaffold", {
        "name": name,
        "template_type": template_type,
        "success": result["success"],
    })

    return {
        "success": result["success"],
        "path": str(target_path) if result["success"] else None,
        "files": result["created_files"],
        "error": result["error"],
    }
