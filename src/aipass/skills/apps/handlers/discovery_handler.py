# =================== AIPass ====================
# Name: discovery_handler.py
# Description: Skill discovery handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Skill Discovery Handler

Contains the core logic for discovering skills across search paths.
Scans directories for SKILL.md files and parses YAML frontmatter.

Purpose:
    Implementation logic for skill discovery, separated from
    orchestration layer to satisfy thin-module standard.
"""

from pathlib import Path

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler

# Try yaml, fall back to simple parser
yaml = None
try:
    import yaml

    HAS_YAML = True
except ImportError:
    logger.warning("yaml package not available — using simple frontmatter parser")
    HAS_YAML = False


def get_search_paths():
    """Return the ordered list of skill search paths.

    Search order (first match wins for same name):
        1. Current project: .aipass/skills/
        2. Global user: ~/.aipass/skills/
        3. Built-in: src/aipass/skills/lib/

    Returns:
        list[tuple[Path, str]]: List of (path, source_label) tuples.
    """
    paths = []

    # 1. Current project
    project_path = Path.cwd() / ".aipass" / "skills"
    paths.append((project_path, "project"))

    # 2. Global user
    global_path = Path.home() / ".aipass" / "skills"
    paths.append((global_path, "global"))

    # 3. Built-in lib
    builtin_path = Path(__file__).resolve().parent.parent.parent / "lib"
    paths.append((builtin_path, "builtin"))

    return paths


def discover_skills_in_path(search_path, source_label):
    """Scan a directory for skill directories containing SKILL.md.

    Args:
        search_path: Path to scan for skill directories.
        source_label: Label for the source (project, global, builtin).

    Returns:
        list[dict]: List of skill dicts with keys:
            name, description, path, has_handler, source, tags.
    """
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


def parse_frontmatter(skill_md_path):
    """Parse YAML frontmatter from a SKILL.md file.

    Frontmatter must be delimited by '---' lines at the top of the file.

    Args:
        skill_md_path: Path to the SKILL.md file.

    Returns:
        dict or None: Parsed frontmatter metadata, or None if invalid.
    """
    try:
        content = Path(skill_md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning(f"Failed to read frontmatter from: {skill_md_path}")
        return None

    return _extract_frontmatter(content)


def _extract_frontmatter(content):
    """Extract and parse YAML frontmatter from file content.

    Args:
        content: Full text content of a SKILL.md file.

    Returns:
        dict or None: Parsed frontmatter, or None if not found.
    """
    lines = content.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    # Find closing ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None

    frontmatter_text = "\n".join(lines[1:end_idx])

    if yaml is not None:
        try:
            return yaml.safe_load(frontmatter_text)
        except yaml.YAMLError:
            logger.warning("YAML parse failed — falling back to simple parser")
            return _simple_frontmatter_parse(frontmatter_text)
    else:
        return _simple_frontmatter_parse(frontmatter_text)


def _simple_frontmatter_parse(text):
    """Simple YAML-like frontmatter parser (no yaml dependency).

    Handles flat key: value pairs, inline lists with [] syntax, block lists
    written as "- item" lines, and nested keys one level deep (e.g.,
    requires.pip).

    Args:
        text: Raw frontmatter text (without --- delimiters).

    Returns:
        dict: Parsed key-value pairs.

    Note:
        A key with an empty value is ambiguous until the NEXT line is read: it
        opens either a block of nested keys (requires:) or a block list
        (when_to_use:). It is therefore held as `pending` and materialised by
        whichever arrives. Answering early is what broke this parser before -
        an empty value was run through _parse_simple_value, whose int() attempt
        failed through to the string "", so every block list silently read as
        "" or {} instead of its items. Silent, because a wrong shape is not an
        error until something downstream trusts it: shipped skills (screen_lock,
        github) lost their when_to_use, and the telegram skill's declared units
        read as empty on any runner without PyYAML - the CI red of 2026-08-19.
    """
    result = {}
    current_key = None
    current_list = None
    # (container, key) for a key whose value has not been decided yet.
    pending = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Block list item: "- value"
        if stripped.startswith("- "):
            if current_list is None and pending is not None:
                container, pending_key = pending
                current_list = []
                container[pending_key] = current_list
                pending = None
            if current_list is None:
                # A stray item under no key belongs to nothing.
                continue
            value = stripped[2:].strip().strip("'\"")
            if value:
                current_list.append(value)
            continue

        # Check for key: value
        if ":" in stripped:
            # A new key ends both the open list and any undecided key.
            current_list = None
            pending = None

            colon_idx = stripped.index(":")
            key = stripped[:colon_idx].strip()
            value = stripped[colon_idx + 1 :].strip()

            # Detect indentation for nested keys
            indent = len(line) - len(line.lstrip())

            if indent > 0 and current_key is not None:
                # Nested key (e.g., pip: [] under requires:)
                if not isinstance(result.get(current_key), dict):
                    result[current_key] = {}
                if not value:
                    # Undecided: a block list may follow on the next line.
                    result[current_key][key] = {}
                    pending = (result[current_key], key)
                    continue
                parsed_value = _parse_simple_value(value)
                result[current_key][key] = parsed_value
                if isinstance(parsed_value, list):
                    current_list = parsed_value
                    # Store reference so appending works
                    result[current_key][key] = current_list
            else:
                # Top-level key
                current_key = key
                if value:
                    result[key] = _parse_simple_value(value)
                else:
                    # Could be a nested block or a block list — decided by the
                    # next line, not guessed at here.
                    result[key] = {}
                    pending = (result, key)

    return result


def _parse_simple_value(value):
    """Parse a simple YAML value string.

    Args:
        value: Raw value string.

    Returns:
        Parsed value (str, bool, int, float, or list).
    """
    # Empty brackets = empty list
    if value == "[]":
        return []

    # Inline list: [item1, item2]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items = [item.strip().strip("'\"") for item in inner.split(",")]
        return [item for item in items if item]

    # Boolean
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False

    # Numeric
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        logger.debug(f"Not a numeric value, falling through to string: {value}")

    # String (strip quotes)
    return value.strip("'\"")
