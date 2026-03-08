# ===================AIPASS====================
# META DATA HEADER
# Name: creator.py - Scaffold new skills from templates
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/apps/modules
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Module layer: orchestration (can print)
#   - Creates new skills from template directories
# =============================================

"""Skill creator module.

Scaffolds new skills from templates into a target location.
Supports three tiers: markdown_only, with_handler, full.
"""

from pathlib import Path

from skills.apps.handlers.template import copy_template, get_template


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

    if not _is_valid_name(name):
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

    if result["success"]:
        print(f"  Created skill '{name}' at {target_path}")
        print(f"  Template: {template_type}")
        print(f"  Files: {len(result['created_files'])}")
        for f in result["created_files"]:
            print(f"    - {f}")

    return {
        "success": result["success"],
        "path": str(target_path) if result["success"] else None,
        "files": result["created_files"],
        "error": result["error"],
    }


def _is_valid_name(name):
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
    return all(c.isalnum() or c == "-" for c in name) and name == name.lower()
