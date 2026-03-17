# =================== AIPass ====================
# Name: loader_handler.py
# Description: Skill loading handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Skill Loading Handler

Contains the core logic for loading skills: parsing full SKILL.md files
(frontmatter + body) and dynamically importing handler.py modules.

Purpose:
    Implementation logic for skill loading, separated from
    orchestration layer to satisfy thin-module standard.
"""

import importlib.util
import sys
from pathlib import Path

from aipass.prax import logger
from skills.apps.handlers.discovery_handler import parse_frontmatter
from skills.apps.handlers.json import json_handler


def parse_full_skill_md(skill_md_path):
    """Parse a SKILL.md file into frontmatter metadata and body text.

    Args:
        skill_md_path: Path to the SKILL.md file.

    Returns:
        tuple: (metadata_dict, body_string) or (None, None) on failure.
    """
    try:
        content = Path(skill_md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None

    lines = content.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None

    # Find closing ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, None

    # Parse frontmatter
    metadata = parse_frontmatter(skill_md_path)
    if metadata is None:
        return None, None

    # Body is everything after the closing ---
    body_lines = lines[end_idx + 1:]
    body = "\n".join(body_lines).strip()

    return metadata, body


def import_handler(skill_path, skill_name):
    """Dynamically import a handler.py from a skill directory.

    Args:
        skill_path: Path to the skill directory.
        skill_name: Name of the skill (used for module naming).

    Returns:
        module or None: The imported handler module, or None on failure.
    """
    handler_file = Path(skill_path) / "handler.py"
    if not handler_file.exists():
        return None

    module_name = f"skills_handler_{skill_name.replace('-', '_')}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, str(handler_file))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        logger.warning(f"Failed to load handler for {skill_name}")
        return None


def find_skill_in_registry(name, registry):
    """Find a skill entry in the registry by name.

    Args:
        name: Skill name to find.
        registry: List of skill dicts.

    Returns:
        dict or None: The matching skill dict, or None if not found.
    """
    for skill in registry:
        if skill["name"] == name:
            return skill
    return None


def load_skill(name, registry):
    """Load a skill by name from a pre-built registry.

    Steps:
        1. Find skill in registry
        2. Parse full SKILL.md (frontmatter + body)
        3. If has_handler is true, import handler.py from skill directory
        4. Return loaded skill dict

    Args:
        name: The skill name to load.
        registry: List of skill dicts from discovery.

    Returns:
        dict: {
            "success": bool,
            "metadata": dict or None,
            "body": str or None,
            "handler": module or None,
            "path": Path or None,
            "error": str or None
        }
    """
    skill_entry = find_skill_in_registry(name, registry)

    if skill_entry is None:
        return {
            "success": False,
            "metadata": None,
            "body": None,
            "handler": None,
            "path": None,
            "error": f"Skill not found: {name}",
        }

    skill_path = Path(skill_entry["path"])
    skill_md = skill_path / "SKILL.md"

    # Parse full SKILL.md
    metadata, body = parse_full_skill_md(skill_md)
    if metadata is None:
        return {
            "success": False,
            "metadata": None,
            "body": None,
            "handler": None,
            "path": skill_path,
            "error": f"Failed to parse SKILL.md at {skill_md}",
        }

    # Import handler if present
    handler = None
    if isinstance(metadata, dict) and metadata.get("has_handler", False):
        handler = import_handler(skill_path, name)

    json_handler.log_operation("skill_load", {
        "name": name,
        "has_handler": handler is not None,
    })

    return {
        "success": True,
        "metadata": metadata,
        "body": body,
        "handler": handler,
        "path": skill_path,
        "error": None,
    }
