# =================== AIPass ====================
# Name: template.py
# Description: Skill template management
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

import shutil
from pathlib import Path

from skills.apps.handlers.json import json_handler


# Template directory lives at src/skills/templates/
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

VALID_TYPES = ("markdown_only", "with_handler", "full")


def get_template(template_type):
    """Get the path to a template directory.

    Args:
        template_type: One of "markdown_only", "with_handler", "full".

    Returns:
        dict: {"success": bool, "path": Path|None, "error": str|None}
    """
    if template_type not in VALID_TYPES:
        return {
            "success": False,
            "path": None,
            "error": f"Unknown template type: {template_type}. Valid types: {', '.join(VALID_TYPES)}",
        }

    template_path = TEMPLATES_DIR / template_type
    if not template_path.exists():
        return {
            "success": False,
            "path": None,
            "error": f"Template directory not found: {template_path}",
        }

    return {"success": True, "path": template_path, "error": None}


def copy_template(template_path, target_path, skill_name):
    """Copy a template directory to a target location, replacing placeholders.

    Args:
        template_path: Path to the source template directory.
        target_path: Path to the destination directory for the new skill.
        skill_name: Name to replace {{SKILL_NAME}} with in all files.

    Returns:
        dict: {"success": bool, "created_files": list[str], "error": str|None}
    """
    target = Path(target_path)

    if target.exists():
        return {
            "success": False,
            "created_files": [],
            "error": f"Target directory already exists: {target}",
        }

    try:
        # Copy the entire template tree
        shutil.copytree(str(template_path), str(target))

        # Replace placeholders in all files
        created_files = []
        for file_path in target.rglob("*"):
            if file_path.is_file():
                created_files.append(str(file_path.relative_to(target)))
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if "{{SKILL_NAME}}" in content:
                        content = content.replace("{{SKILL_NAME}}", skill_name)
                        file_path.write_text(content, encoding="utf-8")
                except UnicodeDecodeError:
                    # Skip binary files
                    pass

        json_handler.log_operation("template_copied", {
            "template": str(template_path.name),
            "target": str(target),
            "files_count": len(created_files),
        })

        return {
            "success": True,
            "created_files": sorted(created_files),
            "error": None,
        }

    except Exception as e:
        # Clean up on failure
        if target.exists():
            shutil.rmtree(str(target))
        return {
            "success": False,
            "created_files": [],
            "error": f"Failed to create skill: {e}",
        }
