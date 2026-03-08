"""
README Section Auto-Generator

Generates auto-populatable README sections for any AIPass branch.
Designed to work with the branch template placeholders and the
readme_check.py validator (Phase 1).

Sections generated:
- Directory tree (apps/ structure)
- Modules list (with docstring descriptions)
- Commands (from --help output)
- Header (from .trinity/passport.json)
- Last Updated timestamp
"""

# =================== AIPass ====================
# Name: readme_generator.py
# Description: README Section Auto-Generator
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

TREE_EXCLUDE = {
    '__pycache__', '.gitkeep', '.git', 'node_modules',
    '.pytest_cache', '.mypy_cache',
}

# Directories to show as name-only (no children) - data/log dirs
TREE_COLLAPSE = {
    'ai_mail.local', 'logs', 'htmlcov', 'commands',
    'ai_mail_archive', 'artifacts',
}

# Directories whose children are files only (no recursion into subdirs)
# e.g., *_json dirs with config/data/log triplets
TREE_SHALLOW_PATTERN = re.compile(r'.*_json$')

# Hidden directory prefixes to skip
HIDDEN_PREFIX = '.'

# Auto-section markers for README updates
MARKER_PREFIX = "<!-- AUTO:"
MARKER_SUFFIX = " -->"
MARKER_CLOSE_PREFIX = "<!-- /AUTO:"


# =============================================================================
# SECTION GENERATORS
# =============================================================================

def generate_tree_section(branch_path: str) -> str:
    """
    Generate a directory tree of the branch structure.

    Uses tree-drawing characters. Shows full detail for apps/ directory
    (the code structure), but collapses data directories (logs, json,
    ai_mail, etc.) to keep output readable.

    Filters out __pycache__, .gitkeep, hidden dirs.
    Returns the tree as a fenced markdown code block.

    Args:
        branch_path: Absolute path to the branch root directory

    Returns:
        Fenced code block string with directory tree, or empty string on failure
    """
    branch_dir = Path(branch_path)

    if not branch_dir.exists():
        return ""

    try:
        lines = []
        # Start with the branch root
        lines.append(f"{branch_dir}/")

        # Build tree with smart depth control:
        # - apps/ gets full depth (4 levels)
        # - docs/, tests/, tools/, templates/ get 2 levels
        # - Data dirs (logs, *_json, ai_mail.local) get collapsed
        _build_tree(branch_dir, lines, prefix="", depth_remaining=4, is_apps_subtree=False)

        if len(lines) <= 1:
            return ""

        tree_text = '\n'.join(lines)
        return f"```\n{tree_text}\n```"

    except Exception:
        return ""


def _should_skip_entry(name: str) -> bool:
    """
    Check if an entry should be skipped entirely from tree output.

    Args:
        name: File or directory name

    Returns:
        True if entry should be excluded
    """
    if name in TREE_EXCLUDE:
        return True
    if name.startswith(HIDDEN_PREFIX) and name not in ('.aipass',):
        return True
    if name.endswith('.pyc'):
        return True
    return False


def _get_dir_depth(dir_name: str, is_apps_subtree: bool) -> Optional[int]:
    """
    Determine how many more levels to recurse into a directory.

    Returns None to collapse (show dir name only, no children).
    Returns an int for the remaining depth to allow.

    Args:
        dir_name: Name of the directory
        is_apps_subtree: Whether we're inside the apps/ directory tree

    Returns:
        Remaining depth (int) or None to collapse
    """
    # Always collapse data/log directories
    if dir_name in TREE_COLLAPSE:
        return None
    if TREE_SHALLOW_PATTERN.match(dir_name):
        return None

    # Inside apps/, allow deep recursion
    if is_apps_subtree:
        return 4

    # Top-level structural directories get moderate depth
    structural_dirs = {'apps', 'docs', 'tests', 'tools', 'templates', 'standards'}
    if dir_name in structural_dirs:
        if dir_name == 'apps':
            return 4  # Full depth for apps
        return 2  # Moderate depth for others

    # Other top-level dirs: show 1 level only
    return 1


def _build_tree(directory: Path, lines: List[str], prefix: str = "",
                depth_remaining: int = 4, is_apps_subtree: bool = False) -> None:
    """
    Recursively build tree lines for a directory.

    Uses smart depth control: apps/ gets full depth, data directories
    get collapsed, structural directories get moderate depth.

    Args:
        directory: Directory to scan
        lines: List to append lines to
        prefix: Current prefix for tree drawing characters
        depth_remaining: How many more levels to recurse
        is_apps_subtree: Whether we are inside the apps/ directory
    """
    if depth_remaining <= 0:
        return

    try:
        entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return

    # Filter entries
    filtered = [e for e in entries if not _should_skip_entry(e.name)]

    for i, entry in enumerate(filtered):
        is_last = (i == len(filtered) - 1)
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "

        if entry.is_dir():
            comment = _get_dir_comment(entry)
            suffix = f"  # {comment}" if comment else ""
            lines.append(f"{prefix}{connector}{entry.name}/{suffix}")

            # Determine child depth
            child_is_apps = is_apps_subtree or entry.name == 'apps'
            child_depth = _get_dir_depth(entry.name, is_apps_subtree)

            if child_depth is not None:
                effective_depth = min(child_depth, depth_remaining - 1)
                if effective_depth > 0:
                    _build_tree(entry, lines, prefix + child_prefix,
                                effective_depth, child_is_apps)
        else:
            comment = _get_file_comment(entry)
            suffix = f"  # {comment}" if comment else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")


def _get_file_comment(file_path: Path) -> str:
    """
    Get a brief comment for a file based on its docstring or header.

    Args:
        file_path: Path to the file

    Returns:
        Short description string, or empty string
    """
    if not file_path.suffix == '.py':
        return ""
    if file_path.name == '__init__.py':
        return ""

    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        # Try to extract from META header Name line
        name_match = re.search(r'^# Name:\s*\S+\s*-\s*(.+)$', content, re.MULTILINE)
        if name_match:
            return name_match.group(1).strip()

        # Fallback: first line of module docstring
        doc_match = re.search(r'^"""(.+?)"""', content, re.DOTALL)
        if doc_match:
            first_line = doc_match.group(1).strip().split('\n')[0].strip()
            if first_line:
                return first_line
    except (OSError, UnicodeDecodeError):
        return ""

    return ""


def _get_dir_comment(dir_path: Path) -> str:
    """
    Get a brief comment for a directory.

    Args:
        dir_path: Path to the directory

    Returns:
        Short description string, or empty string
    """
    # Known directory purposes
    known_dirs = {
        'modules': 'Business logic orchestration',
        'handlers': 'Implementation details',
        'json': 'JSON handler package',
        'json_templates': 'JSON templates',
        'tests': 'Test suite',
        'docs': 'Documentation',
        'tools': 'Utilities',
        'templates': 'Templates',
        'extensions': 'Extensions',
        'plugins': 'Plugins',
    }
    return known_dirs.get(dir_path.name, "")


def generate_modules_section(branch_path: str) -> str:
    """
    Generate a modules list from apps/modules/*.py.

    For each module, extracts the first line of the module docstring
    as a description. Returns a markdown list.

    Args:
        branch_path: Absolute path to the branch root directory

    Returns:
        Markdown formatted module list, or empty string if no modules
    """
    modules_dir = Path(branch_path) / 'apps' / 'modules'

    if not modules_dir.exists():
        return ""

    module_files = sorted(
        f for f in modules_dir.glob('*.py')
        if f.name != '__init__.py'
    )

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

    return '\n'.join(lines)


def _extract_module_description(module_path: Path) -> str:
    """
    Extract description from a Python module file.

    Tries (in order):
    1. META header Name line (after the dash)
    2. First line of module docstring
    3. Empty string

    Args:
        module_path: Path to the .py file

    Returns:
        Description string, or empty string
    """
    try:
        content = module_path.read_text(encoding='utf-8', errors='ignore')

        # Try META header Name line
        name_match = re.search(r'^# Name:\s*\S+\s*-\s*(.+)$', content, re.MULTILINE)
        if name_match:
            return name_match.group(1).strip()

        # Try module docstring first line
        # Match triple-quoted docstring at module level
        doc_match = re.search(r'^"""(.*?)"""', content, re.DOTALL | re.MULTILINE)
        if doc_match:
            docstring = doc_match.group(1).strip()
            if docstring:
                first_line = docstring.split('\n')[0].strip()
                if first_line:
                    return first_line

    except (OSError, UnicodeDecodeError):
        return ""

    return ""


def generate_commands_section(branch_path: str) -> str:
    """
    Generate a commands section from the branch entry point's --help output.

    Finds the branch entry point (apps/*.py matching directory name),
    runs --help, and parses the Commands: line.

    Args:
        branch_path: Absolute path to the branch root directory

    Returns:
        Markdown formatted commands section, or empty string on failure
    """
    branch_dir = Path(branch_path)
    branch_name = branch_dir.name

    # Find entry point: apps/<branch_name>.py
    entry_point = branch_dir / 'apps' / f'{branch_name}.py'
    if not entry_point.exists():
        # Try lowercase
        entry_point = branch_dir / 'apps' / f'{branch_name.lower()}.py'
    if not entry_point.exists():
        return ""

    try:
        env = os.environ.copy()
        env['COLUMNS'] = '500'

        result = subprocess.run(
            [sys.executable, str(entry_point), '--help'],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
            cwd=str(branch_dir)
        )

        output = result.stdout or ""
        if not output:
            output = result.stderr or ""

        if not output.strip():
            return ""

        return _parse_help_output(output)

    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


def _parse_help_output(help_text: str) -> str:
    """
    Parse help output to extract commands information.

    Tries multiple strategies:
    1. A 'Commands:' line (comma-separated list) - drone-compliant format
    2. An 'AVAILABLE COMMANDS:' section with indented lines
    3. Indented 'command   description' pairs throughout the output

    Args:
        help_text: Raw help output text

    Returns:
        Markdown formatted commands section
    """
    lines = []

    # Strategy 1: "Commands:" line (drone-compliant format, usually at end)
    commands_line_match = re.search(r'^Commands:\s*(.+)$', help_text, re.MULTILINE)
    if commands_line_match:
        commands_str = commands_line_match.group(1).strip()
        commands = [cmd.strip() for cmd in commands_str.split(',') if cmd.strip()]
        if commands:
            for cmd in commands:
                if cmd.startswith('--'):
                    lines.append(f"- `{cmd}` - Flag")
                else:
                    lines.append(f"- `{cmd}`")

    # Strategy 2: "AVAILABLE COMMANDS:" section with indented entries
    if not lines:
        available_match = re.search(
            r'AVAILABLE COMMANDS:\s*\n((?:\s+\S.*\n)*)',
            help_text,
            re.MULTILINE
        )
        if available_match:
            cmd_block = available_match.group(1)
            for line in cmd_block.strip().split('\n'):
                stripped = line.strip()
                if stripped:
                    parts = re.split(r'\s{2,}', stripped, maxsplit=1)
                    if len(parts) == 2:
                        lines.append(f"- `{parts[0]}` - {parts[1]}")
                    else:
                        lines.append(f"- `{stripped}`")

    # Strategy 3: Extract indented "command  description" pairs
    # Matches lines like "  drone systems     List all registered branches"
    # or "  command-name    Description text"
    if not lines:
        seen_commands = set()
        # Match: leading whitespace, command words, large gap, description
        cmd_pattern = re.compile(
            r'^\s{2,}([\w@-]+(?:\s[\w@<>-]+)*)\s{2,}([A-Z].*?)$',
            re.MULTILINE
        )
        for match in cmd_pattern.finditer(help_text):
            cmd_part = match.group(1).strip()
            description = match.group(2).strip()
            # Skip lines that look like examples (contain ->, quotes, paths)
            if '->' in description or '"' in cmd_part:
                continue
            # Skip numbered list items like "1. drone systems"
            if re.match(r'^\d+\.', cmd_part):
                continue
            if cmd_part in seen_commands:
                continue
            seen_commands.add(cmd_part)
            lines.append(f"- `{cmd_part}` - {description}")

    if not lines:
        return ""

    return '\n'.join(lines)


def generate_header_section(branch_path: str) -> str:
    """
    Generate the README header block from the branch's passport.

    Reads .trinity/passport.json and extracts: branch_name, path, profile,
    created, email.

    Args:
        branch_path: Absolute path to the branch root directory

    Returns:
        Formatted header markdown, or empty string on failure
    """
    branch_dir = Path(branch_path)
    branch_name = branch_dir.name.upper().replace('-', '_')

    # Find passport.json
    id_file = branch_dir / '.trinity' / 'passport.json'
    if not id_file.exists():
        return ""

    try:
        data = json.loads(id_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return ""

    branch_info = data.get('branch_info', {})

    name = branch_info.get('branch_name', branch_name)
    path = branch_info.get('path', str(branch_dir))
    profile = branch_info.get('profile', 'Unknown')
    created = branch_info.get('created', 'Unknown')
    role = branch_info.get('role', '')

    lines = [
        f"# {name}",
        "",
    ]

    if role:
        lines.append(f"**Purpose:** {role}")
    lines.append(f"**Location:** `{path}`")
    lines.append(f"**Profile:** {profile}")
    lines.append(f"**Created:** {created}")

    return '\n'.join(lines)


def generate_last_updated() -> str:
    """
    Generate the Last Updated timestamp line.

    Returns:
        Formatted timestamp string: *Last Updated: YYYY-MM-DD*
    """
    today = datetime.now().strftime('%Y-%m-%d')
    return f"*Last Updated: {today}*"


# =============================================================================
# AGGREGATE GENERATORS
# =============================================================================

def generate_all_sections(branch_path: str) -> dict:
    """
    Generate all auto-populatable README sections for a branch.

    Calls each generator and returns results as a dict.
    Errors in one section don't affect others.

    Args:
        branch_path: Absolute path to the branch root directory

    Returns:
        Dict with section names as keys, generated content as values.
        Failed sections have empty string values.
    """
    sections = {}

    generators = {
        'header': lambda: generate_header_section(branch_path),
        'tree': lambda: generate_tree_section(branch_path),
        'modules': lambda: generate_modules_section(branch_path),
        'commands': lambda: generate_commands_section(branch_path),
        'last_updated': lambda: generate_last_updated(),
    }

    for name, generator in generators.items():
        try:
            sections[name] = generator()
        except Exception as e:
            sections[name] = ""

    return sections


# =============================================================================
# README UPDATER
# =============================================================================

def update_readme_auto_sections(branch_path: str, dry_run: bool = False) -> dict:
    """
    Update auto-generated sections in an existing README.md.

    Finds sections delimited by HTML comment markers:
        <!-- AUTO:TREE -->...<!-- /AUTO:TREE -->
        <!-- AUTO:MODULES -->...<!-- /AUTO:MODULES -->
        <!-- AUTO:COMMANDS -->...<!-- /AUTO:COMMANDS -->
        <!-- AUTO:HEADER -->...<!-- /AUTO:HEADER -->
        <!-- AUTO:LAST_UPDATED -->...<!-- /AUTO:LAST_UPDATED -->

    If markers don't exist, reports what would be updated without modifying.

    Args:
        branch_path: Absolute path to the branch root directory
        dry_run: If True, print what would change but don't write

    Returns:
        Dict with:
            'updated': list of section names that were updated
            'missing_markers': list of section names without markers
            'errors': list of error messages
            'dry_run': whether this was a dry run
    """
    result = {
        'updated': [],
        'missing_markers': [],
        'errors': [],
        'dry_run': dry_run,
    }

    readme_path = Path(branch_path) / 'README.md'
    if not readme_path.exists():
        result['errors'].append('README.md not found')
        return result

    try:
        content = readme_path.read_text(encoding='utf-8')
    except OSError as e:
        result['errors'].append(f'Failed to read README.md: {e}')
        return result

    # Generate all sections
    sections = generate_all_sections(branch_path)

    # Map section names to marker names
    marker_map = {
        'tree': 'TREE',
        'modules': 'MODULES',
        'commands': 'COMMANDS',
        'header': 'HEADER',
        'last_updated': 'LAST_UPDATED',
    }

    updated_content = content

    for section_name, marker_name in marker_map.items():
        section_content = sections.get(section_name, "")
        if not section_content:
            continue

        open_marker = f"{MARKER_PREFIX}{marker_name}{MARKER_SUFFIX}"
        close_marker = f"{MARKER_CLOSE_PREFIX}{marker_name}{MARKER_SUFFIX}"

        if open_marker in updated_content and close_marker in updated_content:
            # Replace content between markers
            pattern = re.compile(
                re.escape(open_marker) + r'.*?' + re.escape(close_marker),
                re.DOTALL
            )
            replacement = f"{open_marker}\n{section_content}\n{close_marker}"
            updated_content = pattern.sub(replacement, updated_content)
            result['updated'].append(section_name)
        else:
            result['missing_markers'].append(section_name)

    # Write if not dry run and something changed
    if not dry_run and result['updated'] and updated_content != content:
        try:
            readme_path.write_text(updated_content, encoding='utf-8')
        except OSError as e:
            result['errors'].append(f'Failed to write README.md: {e}')

    return result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(Path.cwd())
    print(f"Generating README sections for: {target}\n{'='*70}")
    sections = generate_all_sections(target)
    for name, content in sections.items():
        print(f"\n{'='*70}\nSECTION: {name}\n{'='*70}")
        print(content if content else "(empty - no content generated)")
    # Test updater in dry_run mode
    print(f"\n{'='*70}\nUPDATE DRY RUN\n{'='*70}")
    update_result = update_readme_auto_sections(target, dry_run=True)
    print(f"Would update: {update_result['updated']}")
    print(f"Missing markers: {update_result['missing_markers']}")
    print(f"Errors: {update_result['errors']}")
