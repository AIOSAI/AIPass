# ===================AIPASS====================
# META DATA HEADER
# Name: loader.py - Load SKILL.md and handlers
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/apps/modules
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Module layer: orchestration (can print)
#   - Loads skill metadata, body, and optional handler module
# =============================================

"""Skill loader module.

Loads a skill by name: finds it via discovery, parses the full SKILL.md
(frontmatter + body), and imports the handler if present.
"""

import importlib.util
import sys
from pathlib import Path

from skills.apps.modules.discovery import discover_all, parse_frontmatter


def load_skill(name):
    """Load a skill by name.

    Steps:
        1. Find skill via discovery
        2. Parse full SKILL.md (frontmatter + body)
        3. If has_handler is true, import handler.py from skill directory
        4. Return loaded skill dict

    Args:
        name: The skill name to load.

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
    # Step 1: Find via discovery
    registry = discover_all()
    skill_entry = None
    for skill in registry:
        if skill["name"] == name:
            skill_entry = skill
            break

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

    # Step 2: Parse full SKILL.md
    metadata, body = _parse_full_skill_md(skill_md)
    if metadata is None:
        return {
            "success": False,
            "metadata": None,
            "body": None,
            "handler": None,
            "path": skill_path,
            "error": f"Failed to parse SKILL.md at {skill_md}",
        }

    # Step 3: Import handler if present
    handler = None
    if metadata.get("has_handler", False):
        handler = _load_handler(skill_path, name)
        if handler is None:
            print(f"  Warning: has_handler is true but handler.py not found at {skill_path}")

    return {
        "success": True,
        "metadata": metadata,
        "body": body,
        "handler": handler,
        "path": skill_path,
        "error": None,
    }


def _parse_full_skill_md(skill_md_path):
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


def _load_handler(skill_path, skill_name):
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
    except Exception as exc:
        print(f"  Warning: Failed to load handler for {skill_name}: {exc}")
        return None
