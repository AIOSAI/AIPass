# =================== AIPass ====================
# Name: registry.py
# Description: Skill registry management
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Skill registry: one deduplicated catalogue built from the search paths."""

from pathlib import Path

from aipass.skills.apps.handlers.json import json_handler


def build_registry(search_paths, discover_fn):
    """Discover and cache all skills from search paths."""
    registry = []
    seen_names = set()

    for search_path, source_label in search_paths:
        path = Path(search_path)
        if not path.exists():
            continue

        skills = discover_fn(path, source_label)
        for skill in skills:
            # Paths come in priority order: first name wins, so a project skill shadows a built-in.
            if skill["name"] not in seen_names:
                seen_names.add(skill["name"])
                registry.append(skill)

    json_handler.log_operation(
        "registry_built",
        {
            "paths_scanned": len(search_paths),
            "skills_found": len(registry),
        },
    )

    return registry


def get_skill(name, registry):
    """Look up a skill by name in the registry."""
    for skill in registry:
        if skill["name"] == name:
            return skill
    return None
