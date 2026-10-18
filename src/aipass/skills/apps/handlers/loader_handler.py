# =================== AIPass ====================
# Name: loader_handler.py
# Description: Skill loading handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Skill Loading Handler
"""

import importlib.util
import sys
from pathlib import Path

from aipass.prax import logger
from aipass.skills.apps.handlers.discovery_handler import parse_frontmatter
from aipass.skills.apps.handlers.json import json_handler


def parse_full_skill_md(skill_md_path):
    """Parse a SKILL.md file into frontmatter metadata and body text."""
    try:
        content = Path(skill_md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning(f"Failed to read SKILL.md: {skill_md_path}")
        return None, None

    lines = content.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, None

    metadata = parse_frontmatter(skill_md_path)
    if metadata is None:
        return None, None

    body_lines = lines[end_idx + 1 :]
    body = "\n".join(body_lines).strip()

    return metadata, body


def import_handler(skill_path, skill_name):
    """Dynamically import a handler.py from a skill directory.

    Returns None only when there is no handler.py; a handler that raises on import propagates."""
    handler_file = Path(skill_path) / "handler.py"
    if not handler_file.exists():
        return None

    module_name = f"skills_handler_{skill_name.replace('-', '_')}"

    spec = importlib.util.spec_from_file_location(module_name, str(handler_file))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {handler_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # A half-executed module must not stay importable under its name.
        sys.modules.pop(module_name, None)
        raise
    return module


def find_skill_in_registry(name, registry):
    """Find a skill entry in the registry by name."""
    for skill in registry:
        if skill["name"] == name:
            return skill
    return None


def load_skill(name, registry):
    """Load a skill by name from a pre-built registry."""
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

    handler = None
    if isinstance(metadata, dict) and metadata.get("has_handler", False):
        try:
            handler = import_handler(skill_path, name)
        except Exception as exc:
            logger.error(f"Failed to import handler.py for {name}: {type(exc).__name__}: {exc}")
            return {
                "success": False,
                "metadata": metadata,
                "body": body,
                "handler": None,
                "path": skill_path,
                "error": f"Failed to import handler.py for {name}: {type(exc).__name__}: {exc}",
            }

    json_handler.log_operation(
        "skill_load",
        {
            "name": name,
            "has_handler": handler is not None,
        },
    )

    return {
        "success": True,
        "metadata": metadata,
        "body": body,
        "handler": handler,
        "path": skill_path,
        "error": None,
    }
