# =================== AIPass ====================
# Name: loader_handler.py
# Description: Skill loading handler
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""
Skill Loading Handler
"""

import importlib.util
import sys
from pathlib import Path

from aipass.prax import logger
from aipass.skills.apps.handlers.discovery_handler import read_skill_md
from aipass.skills.apps.handlers.json import json_handler
from aipass.skills.apps.handlers.registry import get_skill


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


def load_skill(name, registry):
    """Load a skill by name from a pre-built registry."""
    skill_entry = get_skill(name, registry)

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

    metadata, body = read_skill_md(skill_md)
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
