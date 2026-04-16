# =================== AIPass ====================
# Name: readme_check.py
# Description: README Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
README Standards Checker Handler

Validates README.md completeness and freshness for AIPass branches.

Checks:
1. README exists at branch root
2. Required sections present (Architecture, Commands, Integration Points)
3. Last Updated freshness (within 7 days of newest code change)
4. Directory tree accuracy (mentioned directories exist on disk)
5. Module list completeness (all modules in apps/modules/ mentioned)
6. Command list presence (commands/usage section is not empty)
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: entry points only (apps/{name}.py)
AUDIT_SCOPE = "entry_point"


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed"""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if branch README follows standards

    Args:
        module_path: Path to branch entry point (e.g., src/aipass/seedgo/apps/branch.py)
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': str
        }
    """
    checks = []

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "readme", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "README",
        }

    # Derive branch root: module_path is apps/[branch].py, go up 2 levels
    entry_path = Path(module_path)
    branch_root = entry_path.parent.parent

    # Check 1: README exists
    readme_path = branch_root / "README.md"
    readme_exists_check = check_readme_exists(readme_path)
    checks.append(readme_exists_check)

    # If README doesn't exist, all other checks fail
    if not readme_exists_check["passed"]:
        for name in [
            "Required sections",
            "Last Updated freshness",
            "Directory tree accuracy",
            "Module list completeness",
            "Command list presence",
        ]:
            checks.append({"name": name, "passed": False, "message": "Cannot check - README.md missing"})

        passed_checks = sum(1 for c in checks if c["passed"])
        total_checks = len(checks)
        score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

        return {"passed": score >= 75, "checks": checks, "score": score, "standard": "README"}

    # Read README content
    try:
        content = readme_path.read_text(encoding="utf-8")
        lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read README at %s: %s", readme_path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading README: {e}"}],
            "score": 0,
            "standard": "README",
        }

    # Check 2: Required sections present
    sections_check = check_required_sections(lines, module_path, bypass_rules)
    checks.append(sections_check)

    # Check 3: Last Updated freshness
    freshness_check = check_last_updated_freshness(lines, branch_root, module_path, bypass_rules)
    checks.append(freshness_check)

    # Check 4: Directory tree accuracy
    tree_check = check_directory_tree(lines, branch_root, module_path, bypass_rules)
    checks.append(tree_check)

    # Check 5: Module list completeness
    modules_check = check_module_list(lines, branch_root, module_path, bypass_rules)
    checks.append(modules_check)

    # Check 6: Command list presence
    commands_check = check_command_list(lines, module_path, bypass_rules)
    checks.append(commands_check)

    # Calculate score
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "readme"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "README"}


def check_readme_exists(readme_path: Path) -> Dict:
    """Check that README.md exists at branch root"""
    if readme_path.exists() and readme_path.is_file():
        return {"name": "README exists", "passed": True, "message": f"Found at {readme_path}"}
    return {"name": "README exists", "passed": False, "message": f"README.md not found at {readme_path.parent}"}


def check_required_sections(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check for required section headers (case-insensitive, ## markdown headers).

    Required (at least one from each group):
    - Architecture OR Directory Structure
    - Commands OR Usage
    - Integration Points OR Depends On OR Provides To
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Required sections", "passed": True, "message": "Bypassed by bypass rules"}

    content_lower = "\n".join(lines).lower()

    # Group 1: Architecture / Directory Structure
    group1_patterns = ["architecture", "directory structure"]
    group1_found = any(re.search(r"^#{1,3}\s+.*" + re.escape(p), content_lower, re.MULTILINE) for p in group1_patterns)

    # Group 2: Commands / Usage
    group2_patterns = ["commands", "usage"]
    group2_found = any(re.search(r"^#{1,3}\s+.*" + re.escape(p), content_lower, re.MULTILINE) for p in group2_patterns)

    # Group 3: Integration Points / Depends On / Provides To
    group3_patterns = ["integration points", "depends on", "provides to"]
    group3_found = any(re.search(r"^#{1,3}\s+.*" + re.escape(p), content_lower, re.MULTILINE) for p in group3_patterns)

    missing = []
    if not group1_found:
        missing.append("Architecture/Directory Structure")
    if not group2_found:
        missing.append("Commands/Usage")
    if not group3_found:
        missing.append("Integration Points/Depends On/Provides To")

    if not missing:
        return {"name": "Required sections", "passed": True, "message": "All required sections found"}

    return {"name": "Required sections", "passed": False, "message": f"Missing sections: {', '.join(missing)}"}


def check_last_updated_freshness(
    lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None
) -> Dict:
    """
    Check that Last Updated date is within 7 days of newest .py file modification.

    Looks for patterns:
    - *Last Updated: YYYY-MM-DD*
    - *Last Updated*: YYYY-MM-DD
    - **Last Updated:** YYYY-MM-DD
    - **Last Updated**: YYYY-MM-DD
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Last Updated freshness", "passed": True, "message": "Bypassed by bypass rules"}

    # Find Last Updated line
    # Accept both italic (*) and bold (**) markdown formatting
    readme_date = None
    date_pattern = re.compile(r"\*{0,2}Last Updated\*{0,2}:\*{0,2}\s*(\d{4}-\d{2}-\d{2})")

    for line in lines:
        match = date_pattern.search(line)
        if match:
            try:
                readme_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            except ValueError:
                logger.info("Malformed date in README: %s", match.group(1))
                readme_date = None  # Malformed date string
            break

    if readme_date is None:
        return {"name": "Last Updated freshness", "passed": False, "message": 'No "Last Updated" date found in README'}

    # Find newest .py file modification time in the branch
    newest_py_mtime = None
    apps_dir = branch_root / "apps"
    if apps_dir.exists():
        for py_file in apps_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            try:
                mtime = datetime.fromtimestamp(py_file.stat().st_mtime)
                if newest_py_mtime is None or mtime > newest_py_mtime:
                    newest_py_mtime = mtime
            except OSError:
                logger.info("Cannot stat %s for freshness check", py_file)
                continue

    if newest_py_mtime is None:
        # No Python files to compare against - pass by default
        return {"name": "Last Updated freshness", "passed": True, "message": "No .py files found to compare against"}

    # Compare: flag if README date is >7 days behind newest code change
    days_behind = (newest_py_mtime - readme_date).days

    if days_behind <= 7:
        return {
            "name": "Last Updated freshness",
            "passed": True,
            "message": f"README date {readme_date.strftime('%Y-%m-%d')} is within 7 days of latest code change",
        }

    return {
        "name": "Last Updated freshness",
        "passed": False,
        "message": f"README date {readme_date.strftime('%Y-%m-%d')} is {days_behind} days behind newest code change ({newest_py_mtime.strftime('%Y-%m-%d')})",
    }


def check_directory_tree(lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check directory tree accuracy.

    If README contains a fenced code block after a "Directory Structure" or
    "Architecture" heading, verify that directories mentioned in the tree
    actually exist on disk.
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Directory tree accuracy", "passed": True, "message": "Bypassed by bypass rules"}

    # Find the tree section: look for a heading with architecture/directory structure,
    # then find the next fenced code block
    content = "\n".join(lines)
    tree_block = _extract_tree_block(content)

    if tree_block is None:
        # No tree section found - pass (it's optional to have one)
        return {
            "name": "Directory tree accuracy",
            "passed": True,
            "message": "No directory tree block found (optional check)",
        }

    # Extract directory names from tree block, line by line
    # Strip inline comments (text after #) to avoid false positives
    # Skip the first non-empty line (root label, e.g., "seedgo/" or "src/aipass/.../spawn/")
    # Common tree formats: "apps/", "├── apps/", "│   ├── handlers/", "  apps/"
    dir_pattern = re.compile(r"[\w\-_.]+/")
    branch_name = branch_root.name.lower()
    mentioned_dirs = set()
    tree_lines = tree_block.split("\n")

    # Skip the first non-empty line (it's the tree root label)
    first_content_skipped = False
    for tree_line in tree_lines:
        if not first_content_skipped and tree_line.strip():
            first_content_skipped = True
            continue
        # Strip inline comments to avoid matching words in comments
        if "#" in tree_line:
            tree_line = tree_line[: tree_line.index("#")]
        for match in dir_pattern.finditer(tree_line):
            dir_name = match.group().rstrip("/")
            # Skip the branch root name itself
            # (trees typically start with the branch name, e.g., "seedgo/")
            if dir_name.lower() == branch_name:
                continue
            if dir_name in ("__pycache__", ".git", "node_modules"):
                continue
            # Skip hidden directories (start with .)
            if dir_name.startswith("."):
                continue
            # Skip glob/wildcard patterns (e.g., "*_check.py" produces "*_check/")
            if "*" in dir_name:
                continue
            mentioned_dirs.add(dir_name)

    if not mentioned_dirs:
        return {"name": "Directory tree accuracy", "passed": True, "message": "No directories detected in tree block"}

    # Check which mentioned directories exist somewhere under branch root
    missing_dirs = []
    for dir_name in mentioned_dirs:
        # Check if this directory exists anywhere in the branch
        found = False
        for _, dirs, _ in os.walk(str(branch_root)):
            if dir_name in dirs:
                found = True
                break
        if not found:
            missing_dirs.append(dir_name)

    if not missing_dirs:
        return {
            "name": "Directory tree accuracy",
            "passed": True,
            "message": f"All {len(mentioned_dirs)} directories in tree verified",
        }

    return {
        "name": "Directory tree accuracy",
        "passed": False,
        "message": f"Directories in tree not found on disk: {', '.join(sorted(missing_dirs))}",
    }


def _extract_tree_block(content: str) -> Optional[str]:
    """
    Extract the fenced code block following an Architecture/Directory Structure heading.

    Returns the code block content, or None if not found.
    """
    # Find heading line
    heading_pattern = re.compile(r"^#{1,3}\s+.*(architecture|directory\s+structure)", re.IGNORECASE | re.MULTILINE)
    heading_match = heading_pattern.search(content)
    if not heading_match:
        return None

    # Look for next fenced code block after the heading
    after_heading = content[heading_match.end() :]
    fence_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
    fence_match = fence_pattern.search(after_heading)
    if not fence_match:
        return None

    return fence_match.group(1)


def check_module_list(lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that all modules in apps/modules/ are mentioned in the README.

    Scans apps/modules/*.py (excluding __init__.py) and checks if each
    module name appears somewhere in the README content.
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Module list completeness", "passed": True, "message": "Bypassed by bypass rules"}

    modules_dir = branch_root / "apps" / "modules"
    if not modules_dir.exists():
        return {
            "name": "Module list completeness",
            "passed": True,
            "message": "No apps/modules/ directory found (skipped)",
        }

    # Get actual module files
    module_files = []
    for py_file in sorted(modules_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module_files.append(py_file.stem)

    if not module_files:
        return {"name": "Module list completeness", "passed": True, "message": "No module files found in apps/modules/"}

    # Check if each module name appears in README
    content_lower = "\n".join(lines).lower()
    missing_modules = []
    for module_name in module_files:
        # Check for module name (with underscores or spaces or as-is)
        name_lower = module_name.lower()
        # Also check with underscores replaced by spaces
        name_spaced = name_lower.replace("_", " ")
        if name_lower not in content_lower and name_spaced not in content_lower:
            missing_modules.append(module_name)

    if not missing_modules:
        return {
            "name": "Module list completeness",
            "passed": True,
            "message": f"All {len(module_files)} modules mentioned in README",
        }

    return {
        "name": "Module list completeness",
        "passed": False,
        "message": f"Modules not mentioned in README: {', '.join(missing_modules)}",
    }


def check_command_list(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that README has a non-empty commands/usage section.

    Finds the Commands or Usage heading and checks that there is content
    between it and the next heading.
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Command list presence", "passed": True, "message": "Bypassed by bypass rules"}

    # Find Commands or Usage heading
    command_heading_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^#{1,3}\s+.*(commands|usage)", stripped, re.IGNORECASE):
            command_heading_idx = i
            break

    if command_heading_idx is None:
        return {
            "name": "Command list presence",
            "passed": False,
            "message": "No Commands/Usage section found in README",
        }

    # Check for content between this heading and next heading (or EOF)
    content_lines = 0
    for i in range(command_heading_idx + 1, len(lines)):
        stripped = lines[i].strip()
        # Stop at next heading
        if re.match(r"^#{1,3}\s+", stripped):
            break
        # Count non-empty lines
        if stripped:
            content_lines += 1

    if content_lines > 0:
        return {
            "name": "Command list presence",
            "passed": True,
            "message": f"Commands/Usage section has {content_lines} content lines",
        }

    return {"name": "Command list presence", "passed": False, "message": "Commands/Usage section is empty"}
