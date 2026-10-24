# =================== AIPass ====================
# Name: readme_generator.py
# Description: README Section Auto-Generator
# Version: 1.1.1
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
README Section Auto-Generator
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

TREE_EXCLUDE = {
    "__pycache__",
    ".gitkeep",
    ".git",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
}

TREE_COLLAPSE = {
    "ai_mail.local",
    "logs",
    "htmlcov",
    "commands",
    "ai_mail_archive",
    "artifacts",
}

TREE_SHALLOW_PATTERN = re.compile(r".*_json$")

HIDDEN_PREFIX = "."

MARKER_PREFIX = "<!-- AUTO:"
MARKER_SUFFIX = " -->"
MARKER_CLOSE_PREFIX = "<!-- /AUTO:"

UNREADABLE_COMMENT = "(unreadable)"


def generate_tree_section(branch_path: str) -> str:
    """Generate a directory tree of the branch structure.

    Raises OSError when the tree cannot be read; generate_all_sections records it."""
    branch_dir = Path(branch_path)

    if not branch_dir.exists():
        return ""

    lines = []
    lines.append(f"{branch_dir}/")

    _build_tree(branch_dir, lines, prefix="", depth_remaining=4, is_apps_subtree=False)

    if len(lines) <= 1:
        return ""

    tree_text = "\n".join(lines)
    return f"```\n{tree_text}\n```"


def _should_skip_entry(name: str) -> bool:
    """Check if an entry should be skipped entirely from tree output."""
    if name in TREE_EXCLUDE:
        return True
    if name.startswith(HIDDEN_PREFIX) and name not in (".aipass",):
        return True
    if name.endswith(".pyc"):
        return True
    return False


def _get_dir_depth(dir_name: str, is_apps_subtree: bool) -> Optional[int]:
    """Determine how many more levels to recurse into a directory.

    None collapses the directory to its name only."""
    if dir_name in TREE_COLLAPSE:
        return None
    if TREE_SHALLOW_PATTERN.match(dir_name):
        return None

    if is_apps_subtree:
        return 4

    structural_dirs = {"apps", "docs", "tests", "tools", "templates", "standards"}
    if dir_name in structural_dirs:
        if dir_name == "apps":
            return 4  # Full depth for apps
        return 2  # Moderate depth for others

    return 1


def _build_tree(
    directory: Path, lines: List[str], prefix: str = "", depth_remaining: int = 4, is_apps_subtree: bool = False
) -> None:
    """Recursively build tree lines for a directory."""
    if depth_remaining <= 0:
        return

    try:
        entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        logger.info("Permission denied reading directory: %s", directory)
        return

    filtered = [e for e in entries if not _should_skip_entry(e.name)]

    for i, entry in enumerate(filtered):
        is_last = i == len(filtered) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "

        if entry.is_dir():
            comment = _get_dir_comment(entry)
            suffix = f"  # {comment}" if comment else ""
            lines.append(f"{prefix}{connector}{entry.name}/{suffix}")

            child_is_apps = is_apps_subtree or entry.name == "apps"
            child_depth = _get_dir_depth(entry.name, is_apps_subtree)

            if child_depth is not None:
                effective_depth = min(child_depth, depth_remaining - 1)
                if effective_depth > 0:
                    _build_tree(entry, lines, prefix + child_prefix, effective_depth, child_is_apps)
        else:
            file_comment = _get_file_comment(entry)
            if file_comment is None:
                file_comment = UNREADABLE_COMMENT
            suffix = f"  # {file_comment}" if file_comment else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")


def _read_source(file_path: Path) -> str:
    """Read one tree file's text; the seam a test replaces to make a read fail."""
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _get_file_comment(file_path: Path) -> Optional[str]:
    """Get a brief comment for a file based on its docstring or header.

    None when the file could not be read (the tree marks it unreadable)."""
    if not file_path.suffix == ".py":
        return ""
    if file_path.name == "__init__.py":
        return ""

    try:
        return _extract_description_from_content(_read_source(file_path))
    except (OSError, UnicodeDecodeError):
        logger.info("Cannot read file for comment extraction: %s", file_path)
        return None


def _get_dir_comment(dir_path: Path) -> str:
    """Get a brief comment for a directory."""
    known_dirs = {
        "modules": "Business logic orchestration",
        "handlers": "Implementation details",
        "json": "JSON handler package",
        "json_templates": "JSON templates",
        "tests": "Test suite",
        "docs": "Documentation",
        "tools": "Utilities",
        "templates": "Templates",
        "extensions": "Extensions",
        "plugins": "Plugins",
    }
    return known_dirs.get(dir_path.name, "")


def generate_modules_section(branch_path: str) -> str:
    """Generate a modules list from apps/modules/*.py."""
    modules_dir = Path(branch_path) / "apps" / "modules"

    if not modules_dir.exists():
        return ""

    module_files = sorted(f for f in modules_dir.glob("*.py") if f.name != "__init__.py")

    if not module_files:
        return ""

    lines = []
    for module_file in module_files:
        name = module_file.stem
        description = _extract_module_description(module_file)

        if description:
            lines.append(f"- **{name}** - {description}")
        else:
            lines.append(f"- **{name}**")

    return "\n".join(lines)


def _extract_description_from_content(content: str) -> str:
    name_match = re.search(r"^# Name:\s*\S+\s*-\s*(.+)$", content, re.MULTILINE)
    if name_match:
        return name_match.group(1).strip()

    desc_match = re.search(r"^# Description:\s*(.+)$", content, re.MULTILINE)
    if desc_match:
        return desc_match.group(1).strip()

    doc_match = re.search(r'^"""(.*?)"""', content, re.DOTALL | re.MULTILINE)
    if doc_match:
        docstring = doc_match.group(1).strip()
        if docstring:
            first_line = docstring.split("\n")[0].strip()
            if first_line:
                return first_line

    return ""


def _extract_module_description(module_path: Path) -> str:
    """Extract description from a Python module file."""
    try:
        content = module_path.read_text(encoding="utf-8", errors="ignore")
        return _extract_description_from_content(content)
    except (OSError, UnicodeDecodeError):
        logger.info("Cannot read module for description extraction: %s", module_path)
        return ""


def generate_commands_section(branch_path: str) -> str:
    """Generate a commands section from the branch entry point's --help output.

    Raises TimeoutExpired or OSError; generate_all_sections records both."""
    branch_dir = Path(branch_path)
    branch_name = branch_dir.name

    entry_point = branch_dir / "apps" / f"{branch_name}.py"
    if not entry_point.exists():
        entry_point = branch_dir / "apps" / f"{branch_name.lower()}.py"
    if not entry_point.exists():
        return ""

    env = os.environ.copy()
    env["COLUMNS"] = "500"

    result = subprocess.run(
        [sys.executable, str(entry_point), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
        cwd=str(branch_dir),
    )

    output = result.stdout or ""
    if not output:
        output = result.stderr or ""

    if not output.strip():
        return ""

    return _parse_help_output(output)


def _parse_commands_line(help_text: str) -> List[str]:
    commands_line_match = re.search(r"^Commands:\s*(.+)$", help_text, re.MULTILINE)
    if not commands_line_match:
        return []
    commands_str = commands_line_match.group(1).strip()
    commands = [cmd.strip() for cmd in commands_str.split(",") if cmd.strip()]
    lines = []
    for cmd in commands:
        if cmd.startswith("--"):
            lines.append(f"- `{cmd}` - Flag")
        else:
            lines.append(f"- `{cmd}`")
    return lines


def _parse_commands_section(help_text: str) -> List[str]:
    available_match = re.search(r"AVAILABLE COMMANDS:\s*\n((?:\s+\S.*\n)*)", help_text, re.MULTILINE)
    if not available_match:
        return []
    lines = []
    cmd_block = available_match.group(1)
    for line in cmd_block.strip().split("\n"):
        stripped = line.strip()
        if stripped:
            parts = re.split(r"\s{2,}", stripped, maxsplit=1)
            if len(parts) == 2:
                lines.append(f"- `{parts[0]}` - {parts[1]}")
            else:
                lines.append(f"- `{stripped}`")
    return lines


def _parse_command_pairs(help_text: str) -> List[str]:
    lines = []
    seen_commands = set()
    cmd_pattern = re.compile(r"^\s{2,}([\w@-]+(?:\s[\w@<>-]+)*)\s{2,}([A-Z].*?)$", re.MULTILINE)
    for match in cmd_pattern.finditer(help_text):
        cmd_part = match.group(1).strip()
        description = match.group(2).strip()
        if "->" in description or '"' in cmd_part:
            continue
        if re.match(r"^\d+\.", cmd_part):
            continue
        if cmd_part in seen_commands:
            continue
        seen_commands.add(cmd_part)
        lines.append(f"- `{cmd_part}` - {description}")
    return lines


def _parse_help_output(help_text: str) -> str:
    """Parse help output to extract commands information."""
    lines = _parse_commands_line(help_text)

    if not lines:
        lines = _parse_commands_section(help_text)

    if not lines:
        lines = _parse_command_pairs(help_text)

    if not lines:
        return ""

    return "\n".join(lines)


def generate_header_section(branch_path: str) -> str:
    """Generate the README header block from the branch's passport.

    Raises JSONDecodeError or OSError on an unreadable passport; generate_all_sections records it."""
    branch_dir = Path(branch_path)
    branch_name = branch_dir.name.upper().replace("-", "_")

    id_file = branch_dir / ".trinity" / "passport.json"
    if not id_file.exists():
        return ""

    data = json.loads(id_file.read_text(encoding="utf-8"))

    branch_info = data.get("branch_info", {})

    name = branch_info.get("branch_name", branch_name)
    path = branch_info.get("path", str(branch_dir))
    profile = branch_info.get("profile", "Unknown")
    created = branch_info.get("created", "Unknown")
    role = branch_info.get("role", "")

    lines = [
        f"# {name}",
        "",
    ]

    if role:
        lines.append(f"**Purpose:** {role}")
    lines.append(f"**Location:** `{path}`")
    lines.append(f"**Profile:** {profile}")
    lines.append(f"**Created:** {created}")

    return "\n".join(lines)


def generate_last_updated() -> str:
    """Generate the Last Updated timestamp line."""
    today = datetime.now().strftime("%Y-%m-%d")
    return f"*Last Updated: {today}*"


def generate_all_sections(branch_path: str, errors: Optional[List[str]] = None) -> dict:
    """Generate all auto-populatable README sections for a branch.

    A failed section is "" and named in ``errors``; the others still run."""
    sections = {}

    generators = {
        "header": lambda: generate_header_section(branch_path),
        "tree": lambda: generate_tree_section(branch_path),
        "modules": lambda: generate_modules_section(branch_path),
        "commands": lambda: generate_commands_section(branch_path),
        "last_updated": lambda: generate_last_updated(),
    }

    for name, generator in generators.items():
        try:
            sections[name] = generator()
        except Exception as exc:
            logger.info("Section generator %s failed for %s: %s", name, branch_path, exc)
            sections[name] = ""
            if errors is not None:
                errors.append(f"{name} section failed: {exc}")

    json_handler.log_operation("readme_generated", {"branch": branch_path, "sections": list(sections.keys())})
    return sections


def update_readme_auto_sections(branch_path: str, dry_run: bool = False) -> dict:
    """Update auto-generated sections in an existing README.md.

    Rewrites only between ``<!-- AUTO:NAME -->`` and ``<!-- /AUTO:NAME -->`` markers."""
    result = {
        "updated": [],
        "missing_markers": [],
        "errors": [],
        "dry_run": dry_run,
    }

    readme_path = Path(branch_path) / "README.md"
    if not readme_path.exists():
        result["errors"].append("README.md not found")
        return result

    try:
        content = readme_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.info("Cannot read README at %s: %s", readme_path, e)
        result["errors"].append(f"Failed to read README.md: {e}")
        return result

    sections = generate_all_sections(branch_path, result["errors"])

    marker_map = {
        "tree": "TREE",
        "modules": "MODULES",
        "commands": "COMMANDS",
        "header": "HEADER",
        "last_updated": "LAST_UPDATED",
    }

    updated_content = content

    for section_name, marker_name in marker_map.items():
        section_content = sections.get(section_name, "")
        if not section_content:
            continue

        open_marker = f"{MARKER_PREFIX}{marker_name}{MARKER_SUFFIX}"
        close_marker = f"{MARKER_CLOSE_PREFIX}{marker_name}{MARKER_SUFFIX}"

        if open_marker in updated_content and close_marker in updated_content:
            pattern = re.compile(re.escape(open_marker) + r".*?" + re.escape(close_marker), re.DOTALL)
            replacement = f"{open_marker}\n{section_content}\n{close_marker}"
            # A callable hands the text over verbatim: as a template string, a Windows
            # path's "C:\Users" reads as the escape \U and raises re.error.
            new_content = pattern.sub(lambda _match: replacement, updated_content)
            if new_content != updated_content:
                result["updated"].append(section_name)
            updated_content = new_content
        else:
            result["missing_markers"].append(section_name)

    if not dry_run and result["updated"] and updated_content != content:
        try:
            readme_path.write_text(updated_content, encoding="utf-8")
        except OSError as e:
            logger.info("Cannot write README at %s: %s", readme_path, e)
            result["errors"].append(f"Failed to write README.md: {e}")
            result["updated"] = []

    return result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    from rich.console import Console as _Console

    _cli = _Console()
    target = sys.argv[1] if len(sys.argv) > 1 else str(Path.cwd())
    _cli.print(f"Generating README sections for: {target}\n{'=' * 70}")
    sections = generate_all_sections(target)
    for name, content in sections.items():
        _cli.print(f"\n{'=' * 70}\nSECTION: {name}\n{'=' * 70}")
        _cli.print(content if content else "(empty - no content generated)")
    _cli.print(f"\n{'=' * 70}\nUPDATE DRY RUN\n{'=' * 70}")
    update_result = update_readme_auto_sections(target, dry_run=True)
    _cli.print(f"Would update: {update_result['updated']}")
    _cli.print(f"Missing markers: {update_result['missing_markers']}")
    _cli.print(f"Errors: {update_result['errors']}")
