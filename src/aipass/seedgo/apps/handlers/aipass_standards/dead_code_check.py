# =================== AIPass ====================
# Name: dead_code_check.py
# Description: Dead Code Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Dead Code Standards Checker Handler

Detects unused Python modules and handlers within an AIPass branch.

Scans .py files in apps/modules/ and apps/handlers/, then checks whether
anything in the branch's apps/ directory imports or references them.
Files with zero references are flagged as dead code.

Score: referenced_files / total_files * 100, threshold 75%.
"""

import re
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

# Directories to skip when collecting source files
_SKIP_DIRS = {
    "__pycache__",
    ".archive",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "json_templates",
    "logs",
    "tools",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    "site-packages",
    ".trinity",
    ".aipass",
    ".ai_mail.local",
    ".spawn",
    "backups",
    "reports",
    "docs",
    "tests",
    ".sorting_unprocessed",
}


# =============================================
# BYPASS HELPER
# =============================================


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed."""
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


# =============================================
# FILE COLLECTION
# =============================================


def _should_skip(path: Path) -> bool:
    """Check whether any parent directory component is in the skip set."""
    return any(part in _SKIP_DIRS for part in path.parts)


def _collect_scannable_files(apps_dir: Path) -> list[Path]:
    """
    Collect .py files from apps/modules/ and apps/handlers/ that should be
    checked for usage.  Skips __init__.py, __pycache__, .archive, etc.
    """
    targets: list[Path] = []
    for subdir_name in ("modules", "handlers"):
        subdir = apps_dir / subdir_name
        if not subdir.is_dir():
            continue
        for py_file in subdir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            if _should_skip(py_file):
                continue
            targets.append(py_file)
    return sorted(targets)


def _collect_source_text(apps_dir: Path) -> str:
    """
    Read ALL .py files under apps/ into a single string for searching.
    This is the corpus we search for references.
    """
    parts: list[str] = []
    for py_file in apps_dir.rglob("*.py"):
        if _should_skip(py_file):
            continue
        try:
            parts.append(py_file.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            logger.info("Skipped unreadable file during source collection: %s", py_file)
            continue
    return "\n".join(parts)


# =============================================
# REFERENCE CHECKING
# =============================================


def _build_import_path(py_file: Path, branch_path: Path, branch_name: str) -> str:
    """
    Build the dotted import path for a file.

    For src/aipass/prax/apps/handlers/monitoring/log_watcher.py:
      -> aipass.prax.apps.handlers.monitoring.log_watcher

    For src/commons/apps/modules/post_manager.py:
      -> commons.apps.modules.post_manager
    """
    try:
        rel = py_file.relative_to(branch_path)
    except ValueError:
        logger.info("File %s not relative to branch %s, using stem", py_file, branch_path)
        return py_file.stem

    parts = list(rel.with_suffix("").parts)

    # If the branch is under src/aipass/, prefix is aipass.{branch}
    # If under src/{name}/ (commons, skills), prefix is just {name}
    if "aipass" in branch_path.parts:
        return f"aipass.{branch_name}.{'.'.join(parts)}"
    return f"{branch_name}.{'.'.join(parts)}"


def _check_file_used(
    py_file: Path,
    branch_path: Path,
    branch_name: str,
    source_text: str,
    entry_point_name: str,
) -> bool:
    """
    Determine if a .py file is referenced anywhere in the branch source.

    A file counts as "used" if ANY of these hold:
    1. __init__.py (package structure) -- always used
    2. Entry point (apps/{branch}.py) -- always used
    3. Glob/discovery convention (*_check.py, *_content.py) -- always used
    4. Import by dotted path or relative path found in corpus
    5. Stem appears in an import statement in corpus
    6. Filename string reference in corpus
    """
    stem = py_file.stem

    # Rule 1: __init__.py is always used
    if py_file.name == "__init__.py":
        return True

    # Rule 2: entry point
    if py_file.name == f"{entry_point_name}.py" and py_file.parent.name == "apps":
        return True

    # Rule 3: glob/discovery convention files
    for suffix_pattern in ("_check", "_content"):
        glob_lit = f'glob("*{suffix_pattern}.py")'
        glob_lit_sq = f"glob('*{suffix_pattern}.py')"
        if stem.endswith(suffix_pattern) and (glob_lit in source_text or glob_lit_sq in source_text):
            return True

    # Rule 4: full dotted import path
    import_path = _build_import_path(py_file, branch_path, branch_name)
    if import_path in source_text:
        return True

    # Also check relative paths within the branch
    try:
        rel = py_file.relative_to(branch_path / "apps")
        rel_dotted = ".".join(rel.with_suffix("").parts)
        if rel_dotted in source_text:
            return True
    except ValueError:
        logger.info("File %s not relative to apps dir, skipping relative path check", py_file)

    # Rule 5: stem appears in import statements
    esc = re.escape(stem)
    import_patterns = [
        rf"from\s+\S*\.{esc}\s+import\b",
        rf"import\s+\S*\.{esc}\b",
        rf"from\s+\S+\s+import\s+[^#\n]*\b{esc}\b",
    ]
    for pat in import_patterns:
        if re.search(pat, source_text):
            return True

    # importlib.import_module with the stem
    if re.search(
        rf'import_module\([^)]*["\'].*\.{esc}["\']',
        source_text,
    ):
        return True

    # Glob-based auto-discovery for direct children of modules/
    try:
        rel_to_apps = py_file.relative_to(branch_path / "apps")
        parts = rel_to_apps.parts
        if len(parts) == 2 and parts[0] == "modules":
            if 'glob("*.py")' in source_text or "glob('*.py')" in source_text:
                return True
    except ValueError:
        logger.info("File %s not relative to apps dir, skipping glob discovery check", py_file)

    # Rule 6: filename string reference
    filename = py_file.name
    if re.search(rf'["\']{re.escape(filename)}["\']', source_text):
        return True

    return False


# =============================================
# BRANCH-LEVEL CHECK (audit pipeline entry)
# =============================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """
    Check a branch for dead code (unreferenced modules and handlers).

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo)
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,
            'score': int,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'standard': 'DEAD_CODE'
        }
    """
    bp = Path(branch_path)

    # Check if entire standard is bypassed
    if is_bypassed(branch_path, "dead_code", bypass_rules=bypass_rules):
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "DEAD_CODE",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "dead_code"},
        )
        return result

    apps_dir = bp / "apps"
    if not apps_dir.is_dir():
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Dead code files",
                    "passed": True,
                    "message": f"No apps/ directory found in {branch_path}",
                }
            ],
            "score": 100,
            "standard": "DEAD_CODE",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "dead_code"},
        )
        return result

    # Determine branch name and entry point
    branch_name = bp.name
    entry_point_name = branch_name

    # Collect scannable files
    targets = _collect_scannable_files(apps_dir)
    if not targets:
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Dead code files",
                    "passed": True,
                    "message": "No modules or handlers found to check",
                }
            ],
            "score": 100,
            "standard": "DEAD_CODE",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "dead_code"},
        )
        return result

    # Build the source corpus (all .py content from apps/)
    source_text = _collect_source_text(apps_dir)

    # Check each target for references
    total_files = len(targets)
    dead_files: list[str] = []

    for target in targets:
        used = _check_file_used(target, bp, branch_name, source_text, entry_point_name)
        if not used:
            # Check per-file bypass
            try:
                rel = target.relative_to(apps_dir)
            except ValueError:
                logger.info("File %s not relative to apps dir, using full path", target)
                rel = target
            if not is_bypassed(str(rel), "dead_code", bypass_rules=bypass_rules):
                dead_files.append(str(rel))

    referenced_files = total_files - len(dead_files)
    score = int(referenced_files / total_files * 100) if total_files > 0 else 100

    # Build the single check result
    if dead_files:
        dead_list = ", ".join(dead_files[:10])
        suffix = f" (+{len(dead_files) - 10} more)" if len(dead_files) > 10 else ""
        message = f"{len(dead_files)}/{total_files} files unreferenced: {dead_list}{suffix}"
    else:
        message = f"All {total_files} files referenced -- no dead code"

    check_passed = len(dead_files) == 0
    checks = [
        {
            "name": "Dead code files",
            "passed": check_passed,
            "message": message,
        }
    ]

    overall_passed = score >= 75

    result = {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "DEAD_CODE",
    }

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": "dead_code"},
    )
    return result
