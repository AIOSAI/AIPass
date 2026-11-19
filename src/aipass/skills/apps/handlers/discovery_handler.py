# =================== AIPass ====================
# Name: discovery_handler.py
# Description: Skill discovery handler
# Version: 1.1.2
# Created: 2026-03-08
# Modified: 2026-11-17
# =============================================

"""
Skill Discovery Handler
"""

from pathlib import Path

import yaml

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler


def get_search_paths():
    """Return the ordered list of skill search paths.

    Priority order, first match wins: project, global, built-in."""
    paths = []

    # Host processes (relay, cron lanes, hooks) can hold a dead cwd: skip the project path,
    # never guess it, so global and builtin skills still resolve.
    try:
        project_path = Path.cwd() / ".aipass" / "skills"
    except OSError as exc:
        logger.warning("No readable working directory (%s) - skipping the project search path", exc)
    else:
        paths.append((project_path, "project"))

    global_path = Path.home() / ".aipass" / "skills"
    paths.append((global_path, "global"))

    builtin_path = Path(__file__).resolve().parent.parent.parent / "lib"
    paths.append((builtin_path, "builtin"))

    return paths


def discover_skills_in_path(search_path, source_label):
    """Scan a directory for skill directories containing SKILL.md."""
    path = Path(search_path)
    if not path.exists() or not path.is_dir():
        return []

    skills = []
    for item in sorted(path.iterdir()):
        if not item.is_dir():
            continue
        skill_md = item / "SKILL.md"
        if not skill_md.exists():
            continue

        metadata = parse_frontmatter(skill_md)
        if metadata is None:
            continue
        if not isinstance(metadata, dict):
            continue

        skill_entry = {
            "name": metadata.get("name", item.name),
            "description": metadata.get("description", "No description"),
            "path": item,
            "has_handler": metadata.get("has_handler", False),
            "source": source_label,
            "tags": metadata.get("tags", []),
        }
        when_to_use = metadata.get("when_to_use")
        if when_to_use:
            skill_entry["when_to_use"] = when_to_use
        skills.append(skill_entry)

    json_handler.log_operation(
        "discovery_scan",
        {
            "path": str(path),
            "source": source_label,
            "found": len(skills),
        },
    )
    return skills


def read_skill_md(skill_md_path):
    """Read a SKILL.md once: (frontmatter metadata, body), or (None, None) without a --- block; unreadable or malformed raises ValueError."""
    try:
        content = Path(skill_md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"Unreadable SKILL.md at {skill_md_path}: {type(exc).__name__}") from exc

    lines = content.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    end_idx = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end_idx is None:
        return None, None

    frontmatter_text = "\n".join(lines[1:end_idx])
    try:
        metadata = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML frontmatter in {skill_md_path}: {exc}") from exc
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"Frontmatter in {skill_md_path} is a {type(metadata).__name__}, not a mapping")
    return metadata, "\n".join(lines[end_idx + 1 :]).strip()


def parse_frontmatter(skill_md_path):
    """Parse YAML frontmatter from a SKILL.md file."""
    return read_skill_md(skill_md_path)[0]
