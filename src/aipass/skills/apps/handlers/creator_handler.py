# =================== AIPass ====================
# Name: creator_handler.py
# Description: Skill creation handler
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Skill Creation Handler
"""

from pathlib import Path

from aipass.skills.apps.handlers.json import json_handler
from aipass.skills.apps.handlers.template import copy_template, get_template


def is_valid_name(name):
    """Check if a skill name is valid."""
    if not name or not name[0].isalpha():
        return False
    return all(c.isalnum() or c in "-_" for c in name) and name == name.lower()


def create_skill(name, template_type="markdown_only", target_dir=None):
    """Create a new skill from a template."""
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

    template_result = get_template(template_type)
    if not template_result["success"]:
        return {
            "success": False,
            "path": None,
            "files": [],
            "error": template_result["error"],
        }

    if target_dir is None:
        # Unlike discovery, this WRITES: a default that cannot be computed refuses, never falls back.
        try:
            target_dir = Path.cwd() / ".aipass" / "skills"
        except OSError as exc:
            return {
                "success": False,
                "path": None,
                "files": [],
                "error": (
                    f"No readable working directory ({exc}); cannot place a skill "
                    f"in the current project. Pass an explicit target directory."
                ),
            }

    target_path = Path(target_dir) / name

    target_path.parent.mkdir(parents=True, exist_ok=True)

    result = copy_template(template_result["path"], target_path, name)

    json_handler.log_operation(
        "skill_scaffold",
        {
            "name": name,
            "template_type": template_type,
            "success": result["success"],
        },
    )

    return {
        "success": result["success"],
        "path": str(target_path) if result["success"] else None,
        "files": result["created_files"],
        "error": result["error"],
    }
