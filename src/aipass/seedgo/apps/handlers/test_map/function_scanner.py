# =================== AIPass ====================
# Name: function_scanner.py
# Description: AST-based public function scanner for branch test coverage mapping
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
AST-based public function scanner.

Scans a branch's apps/modules/ and apps/handlers/ for public function
definitions, cross-references against tests/, and builds a coverage map.
Excludes standard infrastructure functions (json_handler, CLI routing).
"""

import ast
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


# -- Standard functions to exclude (already covered by test_quality checker) --

# CLI routing — every branch has these, not custom logic
CLI_ROUTING_FUNCTIONS = frozenset(
    {
        "handle_command",
        "print_introspection",
        "print_help",
        "main",
    }
)

# json_handler standard functions — covered by test_quality checker
JSON_HANDLER_FUNCTIONS = frozenset(
    {
        "validate_json_structure",
        "get_json_path",
        "ensure_json_exists",
        "load_json",
        "save_json",
        "log_operation",
        "ensure_module_jsons",
        "load_template",
    }
)

# Bypass helper present in many checkers
CHECKER_BOILERPLATE = frozenset(
    {
        "is_bypassed",
    }
)

EXCLUDED_FUNCTIONS = CLI_ROUTING_FUNCTIONS | JSON_HANDLER_FUNCTIONS | CHECKER_BOILERPLATE


# =============================================================================
# AST SCANNING
# =============================================================================


def _read_file_safe(path: Path) -> str:
    """Read file contents, returning empty string on error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.info("Failed to read file %s: %s", path, e)
        return ""


def _extract_public_functions(file_path: Path) -> list[dict]:
    """Extract public function definitions from a Python file via AST.

    Returns list of dicts: {name, line, file}
    Only top-level and class-level defs. Skips _private and excluded names.
    """
    source = _read_file_safe(file_path)
    if not source:
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        logger.info("Syntax error parsing %s — skipped", file_path)
        return []

    functions = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        # Skip private, dunder, and excluded standard functions
        if name.startswith("_"):
            continue
        if name in EXCLUDED_FUNCTIONS:
            continue
        functions.append(
            {
                "name": name,
                "line": node.lineno,
                "file": str(file_path),
            }
        )

    return functions


def _should_skip_file(py_file: Path) -> bool:
    """Check if file should be skipped based on naming/path rules."""
    if py_file.name.startswith("_"):
        return True
    return any(part.startswith(".") for part in py_file.parts)


def _get_relative_path(file_path: Path, branch_path: Path) -> str:
    """Get relative path, falling back to absolute if not under branch."""
    try:
        return str(file_path.relative_to(branch_path))
    except ValueError:
        logger.info("File %s is not under branch path %s, using absolute path", file_path, branch_path)
        return str(file_path)


def _scan_source_files(branch_path: Path) -> list[dict]:
    """Scan apps/modules/ and apps/handlers/ for public functions.

    Returns list of dicts: {name, line, file, relative_path}
    """
    all_functions = []
    apps_dir = branch_path / "apps"

    scan_dirs = [
        apps_dir / "modules",
        apps_dir / "handlers",
    ]

    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            if _should_skip_file(py_file):
                continue
            funcs = _extract_public_functions(py_file)
            rel = _get_relative_path(py_file, branch_path)
            for func in funcs:
                func["relative_path"] = rel
            all_functions.extend(funcs)

    return all_functions


def _test_files_source(branch_path: Path) -> str:
    """Concatenate all test file sources for matching."""
    tests_dir = branch_path / "tests"
    if not tests_dir.is_dir():
        return ""

    sources = []
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        source = _read_file_safe(test_file)
        if source:
            sources.append(source)

    return "\n".join(sources)


# =============================================================================
# PUBLIC API
# =============================================================================


def scan_branch(branch_path: str) -> dict:
    """Scan a branch and build its custom function coverage map.

    Args:
        branch_path: Absolute path to branch root directory.

    Returns:
        dict with keys:
            branch: branch name
            total_functions: count of public custom functions
            tested_functions: count of functions referenced in tests
            coverage_pct: percentage
            files: list of {relative_path, functions: [{name, line, tested, test_file}]}
    """
    bp = Path(branch_path)
    branch_name = bp.name

    # Scan source for public functions
    all_functions = _scan_source_files(bp)

    # Get concatenated test source for matching
    test_source = _test_files_source(bp)

    # Also build a set of test file names for reporting which test covers
    tests_dir = bp / "tests"
    test_files_map: dict[str, str] = {}  # function_name -> test_file_name
    if tests_dir.is_dir():
        for test_file in sorted(tests_dir.rglob("test_*.py")):
            source = _read_file_safe(test_file)
            if not source:
                continue
            for func in all_functions:
                if func["name"] in source and func["name"] not in test_files_map:
                    test_files_map[func["name"]] = test_file.name

    # Build per-file coverage map
    files_map: dict[str, list[dict]] = {}
    tested_count = 0

    for func in all_functions:
        rel_path = func["relative_path"]
        is_tested = func["name"] in test_source
        if is_tested:
            tested_count += 1

        if rel_path not in files_map:
            files_map[rel_path] = []

        files_map[rel_path].append(
            {
                "name": func["name"],
                "line": func["line"],
                "tested": is_tested,
                "test_file": test_files_map.get(func["name"]),
            }
        )

    total = len(all_functions)
    pct = int((tested_count / total) * 100) if total > 0 else 0

    logger.info(
        "test_map scan: %s — %d/%d custom functions tested (%d%%)",
        branch_name,
        tested_count,
        total,
        pct,
    )

    json_handler.log_operation(
        "test_map_scan",
        {
            "branch": branch_name,
            "total_functions": total,
            "tested_functions": tested_count,
            "coverage_pct": pct,
        },
    )

    return {
        "branch": branch_name,
        "total_functions": total,
        "tested_functions": tested_count,
        "coverage_pct": pct,
        "files": [
            {
                "relative_path": rel_path,
                "functions": funcs,
            }
            for rel_path, funcs in sorted(files_map.items())
        ],
    }
