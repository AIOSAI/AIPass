# =================== AIPass ====================
# Name: discovery_handler.py
# Description: Skill discovery handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""
Skill Discovery Handler
"""

from pathlib import Path

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler
from aipass.skills.apps.handlers.module_paths import module_file

yaml = None
try:
    import yaml

    HAS_YAML = True
except ImportError:
    logger.warning("yaml package not available — using simple frontmatter parser")
    HAS_YAML = False


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

    builtin_path = module_file(__file__).parent.parent.parent / "lib"
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
    """Read a SKILL.md once: (frontmatter metadata, body), or (None, None) without a readable --- block."""
    try:
        content = Path(skill_md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning(f"Failed to read SKILL.md: {skill_md_path}")
        return None, None

    lines = content.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    end_idx = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end_idx is None:
        return None, None

    return _parse_frontmatter_text("\n".join(lines[1:end_idx])), "\n".join(lines[end_idx + 1 :]).strip()


def parse_frontmatter(skill_md_path):
    """Parse YAML frontmatter from a SKILL.md file."""
    return read_skill_md(skill_md_path)[0]


def _parse_frontmatter_text(frontmatter_text):
    """Parse the text between the --- fences: PyYAML when present, else the simple parser."""
    if yaml is not None:
        try:
            return yaml.safe_load(frontmatter_text)
        except yaml.YAMLError:
            logger.warning("YAML parse failed — falling back to simple parser")
    return _simple_frontmatter_parse(frontmatter_text)


def _simple_frontmatter_parse(text):
    """Simple YAML-like frontmatter parser (no yaml dependency).

    An empty-valued key stays `pending` until the next line shows a nested block or a block list;
    deciding early reads every block list as "" or {} (the switch's units vanish without PyYAML)."""
    result = {}
    current_key = None
    current_list = None
    pending = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if current_list is None and pending is not None:
                container, pending_key = pending
                current_list = []
                container[pending_key] = current_list
                pending = None
            if current_list is None:
                continue
            value = stripped[2:].strip().strip("'\"")
            if value:
                current_list.append(value)
            continue

        if ":" in stripped:
            current_list = None
            pending = None

            colon_idx = stripped.index(":")
            key = stripped[:colon_idx].strip()
            value = stripped[colon_idx + 1 :].strip()

            indent = len(line) - len(line.lstrip())

            if indent > 0 and current_key is not None:
                if not isinstance(result.get(current_key), dict):
                    result[current_key] = {}
                if not value:
                    result[current_key][key] = {}
                    pending = (result[current_key], key)
                    continue
                parsed_value = _parse_simple_value(value)
                result[current_key][key] = parsed_value
                if isinstance(parsed_value, list):
                    current_list = parsed_value
                    result[current_key][key] = current_list
            else:
                current_key = key
                if value:
                    result[key] = _parse_simple_value(value)
                else:
                    result[key] = {}
                    pending = (result, key)

    return result


def _parse_simple_value(value):
    """Parse a simple YAML value string."""
    if value == "[]":
        return []

    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items = [item.strip().strip("'\"") for item in inner.split(",")]
        return [item for item in items if item]

    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        logger.debug(f"Not a numeric value, falling through to string: {value}")

    return value.strip("'\"")
