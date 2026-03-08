# ===================AIPASS====================
# META DATA HEADER
# Name: discovery.py - Find skills across search paths
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/apps/modules
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Module layer: orchestration (can print)
#   - Discovers skills by scanning for SKILL.md files
#   - Falls back to simple frontmatter parser if yaml unavailable
# =============================================

"""Skill discovery module.

Scans search paths for directories containing SKILL.md files and
extracts metadata from YAML frontmatter.
"""

from pathlib import Path

# Try yaml, fall back to simple parser
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def get_search_paths():
    """Return the ordered list of skill search paths.

    Search order (first match wins for same name):
        1. Current project: .aipass/skills/
        2. Global user: ~/.aipass/skills/
        3. Built-in: src/skills/catalog/

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

    # 3. Built-in catalog
    builtin_path = Path(__file__).resolve().parent.parent.parent / "catalog"
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

        skills.append({
            "name": metadata.get("name", item.name),
            "description": metadata.get("description", "No description"),
            "path": item,
            "has_handler": metadata.get("has_handler", False),
            "source": source_label,
            "tags": metadata.get("tags", []),
        })

    return skills


def discover_all():
    """Discover all skills across all search paths.

    Returns:
        list[dict]: All discovered skills, deduplicated by name
            (first match wins).
    """
    from skills.apps.handlers.registry import build_registry

    search_paths = get_search_paths()
    return build_registry(search_paths, discover_skills_in_path)


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

    if HAS_YAML:
        try:
            return yaml.safe_load(frontmatter_text)
        except yaml.YAMLError:
            return _simple_frontmatter_parse(frontmatter_text)
    else:
        return _simple_frontmatter_parse(frontmatter_text)


def _simple_frontmatter_parse(text):
    """Simple YAML-like frontmatter parser (no yaml dependency).

    Handles flat key: value pairs, simple lists with [] syntax,
    and nested keys one level deep (e.g., requires.pip).

    Args:
        text: Raw frontmatter text (without --- delimiters).

    Returns:
        dict: Parsed key-value pairs.
    """
    result = {}
    current_key = None
    current_list = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for list item under a nested key
        if stripped.startswith("- ") and current_list is not None:
            value = stripped[2:].strip().strip("'\"")
            if value:
                current_list.append(value)
            continue

        # Check for key: value
        if ":" in stripped:
            # Reset list tracking
            current_list = None

            colon_idx = stripped.index(":")
            key = stripped[:colon_idx].strip()
            value = stripped[colon_idx + 1:].strip()

            # Detect indentation for nested keys
            indent = len(line) - len(line.lstrip())

            if indent > 0 and current_key is not None:
                # Nested key (e.g., pip: [] under requires:)
                if not isinstance(result.get(current_key), dict):
                    result[current_key] = {}
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
                    # Could be a nested block or empty value
                    result[key] = {}

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
        pass

    # String (strip quotes)
    return value.strip("'\"")
