# =================== AIPass ====================
# Name: template.py
# Description: Skill template management
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""Skill scaffolding templates: resolve a tier, copy it, fill placeholders."""

import shutil
from pathlib import Path

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler
from aipass.skills.apps.handlers.module_paths import module_file


TEMPLATES_DIR = module_file(__file__).parent.parent.parent / "templates"

VALID_TYPES = ("markdown_only", "with_handler", "full")


def get_template(template_type):
    """Get the path to a template directory."""
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


def _replace_placeholder_in_file(file_path, skill_name):
    """Replace {{SKILL_NAME}} placeholder in a single file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        if "{{SKILL_NAME}}" in content:
            content = content.replace("{{SKILL_NAME}}", skill_name)
            file_path.write_text(content, encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning(f"Skipping binary file during template copy: {file_path}")


def copy_template(template_path, target_path, skill_name):
    """Copy a template directory to a target location, replacing placeholders."""
    target = Path(target_path)

    if target.exists():
        return {
            "success": False,
            "created_files": [],
            "error": f"Target directory already exists: {target}",
        }

    try:
        shutil.copytree(str(template_path), str(target), ignore=shutil.ignore_patterns("__pycache__"))

        # Posix-spelled and sorted so every host answers the same list: str() spells apps\handlers on Windows.
        created_files = []
        for file_path in target.rglob("*"):
            if not file_path.is_file():
                continue
            created_files.append(file_path.relative_to(target).as_posix())
            _replace_placeholder_in_file(file_path, skill_name)

        json_handler.log_operation(
            "template_copied",
            {
                "template": str(template_path.name),
                "target": str(target),
                "files_count": len(created_files),
            },
        )

        return {
            "success": True,
            "created_files": sorted(created_files),
            "error": None,
        }

    except Exception as e:
        logger.error(f"Template copy failed: {e}")
        if target.exists():
            shutil.rmtree(str(target))
        return {
            "success": False,
            "created_files": [],
            "error": f"Failed to create skill: {e}",
        }
