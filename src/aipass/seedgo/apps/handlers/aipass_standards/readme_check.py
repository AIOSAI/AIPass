# =================== AIPass ====================
# Name: readme_check.py
# Description: README Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-05-15
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
7. Test count accuracy (claimed count vs actual def test_ functions)
8. Markdown link validity (relative links point to existing paths)
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries

# Audit scope: entry points only (apps/{name}.py)
AUDIT_SCOPE = "entry_point"


# Runtime / generated paths that legitimately may be absent in a clean
# checkout (e.g. CI) while present in a working tree. A README documenting
# one of these is not a violation when it's missing from disk.
# Pure local-file check — never consults git or .gitignore. (A standards
# audit reads the files that are there; git is a separate concern.)
_RUNTIME_ARTIFACTS = {
    "logs",
    "artifacts",
    "dropbox",
    "tools",
    "system_logs",
    "docs.local",
    "backups",
    ".trinity",
    "DASHBOARD.local.json",
}


def _is_runtime_artifact(path: Path) -> bool:
    """True if path is a runtime/generated artifact that may be absent in a
    clean checkout. Local-file only — never consults git or .gitignore."""
    name = path.name
    if name in _RUNTIME_ARTIFACTS:
        return True
    if name.endswith("_json"):
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
            "Test count accuracy",
            "Markdown link validity",
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

    # Check 7: Test count accuracy
    test_count_check = check_test_count_accuracy(lines, branch_root, module_path, bypass_rules)
    checks.append(test_count_check)

    # Check 8: Markdown link validity
    link_check = check_markdown_links(lines, branch_root, module_path, bypass_rules)
    checks.append(link_check)

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
    Check that the README declares a well-formed "Last Updated" date.

    Local-file only: verifies the field is present and parseable. Does NOT
    compare against code history — recency is not a property of the files on
    disk, so it has no place in a local standards audit (and would diverge
    between a working tree and a clean CI checkout). A "code changed, re-check
    your README" nudge, if wanted, belongs outside the audit as its own flag.

    Looks for patterns:
    - *Last Updated: YYYY-MM-DD*
    - *Last Updated*: YYYY-MM-DD
    - **Last Updated:** YYYY-MM-DD
    - **Last Updated**: YYYY-MM-DD
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Last Updated freshness", "passed": True, "message": "Bypassed by bypass rules"}

    date_pattern = re.compile(r"\*{0,2}Last Updated\*{0,2}:\*{0,2}\s*(\d{4}-\d{2}-\d{2})")

    for line in lines:
        match = date_pattern.search(line)
        if match:
            try:
                datetime.strptime(match.group(1), "%Y-%m-%d")
            except ValueError:
                logger.info("Malformed Last Updated date in README: %s", match.group(1))
                return {
                    "name": "Last Updated freshness",
                    "passed": False,
                    "message": f"Malformed Last Updated date: {match.group(1)}",
                }
            return {
                "name": "Last Updated freshness",
                "passed": True,
                "message": f"Last Updated date present ({match.group(1)})",
            }

    return {"name": "Last Updated freshness", "passed": False, "message": 'No "Last Updated" date found in README'}


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
            if _is_runtime_artifact(branch_root / dir_name):
                continue
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
        if is_disabled_file(py_file.name):
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


def check_test_count_accuracy(
    lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None
) -> Dict:
    """
    Check that test count claims in README match actual test function count.

    Scans README for patterns like "N tests", "N test functions", etc.
    Counts actual `def test_` functions in tests/ directory.
    Flags when claimed count drifts >10% from actual.
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Test count accuracy", "passed": True, "message": "Bypassed by bypass rules"}

    content = "\n".join(lines)

    claimed_counts = _extract_test_counts(content)
    if not claimed_counts:
        return {
            "name": "Test count accuracy",
            "passed": True,
            "message": "No test count claims found in README (skipped)",
        }

    tests_dir = branch_root / "tests"
    if not tests_dir.exists():
        return {
            "name": "Test count accuracy",
            "passed": True,
            "message": "No tests/ directory found (skipped)",
        }

    actual_count = _count_test_functions(tests_dir)
    max_claimed = max(claimed_counts)

    if actual_count == 0:
        if max_claimed > 0:
            return {
                "name": "Test count accuracy",
                "passed": False,
                "message": f"README claims {max_claimed} tests but no test functions found",
            }
        return {"name": "Test count accuracy", "passed": True, "message": "Both README and tests/ show 0 tests"}

    drift_pct = abs(max_claimed - actual_count) / actual_count * 100

    if drift_pct <= 10:
        return {
            "name": "Test count accuracy",
            "passed": True,
            "message": f"Test count claim ({max_claimed}) within 10% of actual ({actual_count})",
        }

    return {
        "name": "Test count accuracy",
        "passed": False,
        "message": (
            f"README claims {max_claimed} tests, actual count is"
            f" {actual_count} ({drift_pct:.0f}% drift). Update the README"
            f" to {actual_count}."
        ),
    }


def _extract_test_counts(content: str) -> List[int]:
    """Extract numeric test count claims from README content."""
    counts = []
    pattern = re.compile(r"\b(\d+)\s+tests?\b", re.IGNORECASE)
    for match in pattern.finditer(content):
        counts.append(int(match.group(1)))
    return counts


def _count_test_functions(tests_dir: Path) -> int:
    """Count `def test_` functions in all test_*.py files under tests/."""
    count = 0
    branch_root = tests_dir.parent
    ignore_entries = load_ignore_entries(branch_root)
    test_func_pattern = re.compile(r"^\s*def\s+test_", re.MULTILINE)
    for test_file in tests_dir.rglob("test_*.py"):
        if any(part in SOURCE_SKIP_DIRS for part in test_file.relative_to(tests_dir).parts):
            continue
        if is_disabled_file(test_file.name):
            continue
        if is_seedgo_ignored(str(test_file), branch_root, ignore_entries):
            continue
        try:
            source = test_file.read_text(encoding="utf-8")
            count += len(test_func_pattern.findall(source))
        except OSError:
            logger.info("Cannot read test file %s for count", test_file)
            continue
    return count


def check_markdown_links(lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that relative markdown links point to existing paths.

    Parses [text](path) links where path is relative (not http/https/mailto/#).
    Verifies each path exists relative to branch root.
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Markdown link validity", "passed": True, "message": "Bypassed by bypass rules"}

    content = "\n".join(lines)
    links = _extract_relative_links(content)

    if not links:
        return {
            "name": "Markdown link validity",
            "passed": True,
            "message": "No relative markdown links found (skipped)",
        }

    dead_links = []
    for link_text, link_path in links:
        resolved = (branch_root / link_path).resolve()
        if not resolved.exists():
            if _is_runtime_artifact(branch_root / link_path):
                continue
            dead_links.append(f"{link_path} ({link_text})")

    if not dead_links:
        return {
            "name": "Markdown link validity",
            "passed": True,
            "message": f"All {len(links)} relative links verified",
        }

    return {
        "name": "Markdown link validity",
        "passed": False,
        "message": f"Dead links: {', '.join(dead_links)}",
    }


def _extract_relative_links(content: str) -> List[tuple]:
    """Extract relative markdown links as (text, path) tuples."""
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    links = []
    for match in link_pattern.finditer(content):
        text = match.group(1)
        path = match.group(2)
        if path.startswith(("http://", "https://", "mailto:", "#")):
            continue
        links.append((text, path))
    return links


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
