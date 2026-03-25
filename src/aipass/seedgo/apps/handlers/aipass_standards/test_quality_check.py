# =================== AIPass ====================
# Name: test_quality_check.py
# Description: Test Quality Standards Checker — 10 standard categories
# Version: 3.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Test Quality Standards Checker Handler

Branch-level checker that scans ALL test files in a branch's tests/
directory and evaluates coverage across 10 standard test categories.

Does NOT require specific filenames. Does NOT run pytest -- analyses
test files statically via text scan.

Scoring model:
    Score = (total_items_covered / total_items) * 100
"""

from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

# -- Standard test categories and their detection patterns --------------------
STANDARD_CATEGORIES: dict[str, dict[str, list[str]]] = {
    # Category 1: JSON Handler (8 items)
    "json_handler": {
        "default_factory": [
            "_create_default",
            "_get_default_template",
            "_get_default",
            "_default_template",
            "load_template",
            "_default_config",
        ],
        "validate": ["validate_json_structure"],
        "get_path": ["get_json_path"],
        "ensure_exists": ["ensure_json_exists"],
        "load": ["load_json"],
        "save": ["save_json"],
        "log_operation": ["log_operation"],
        "ensure_module": ["ensure_module_jsons"],
    },
    # Category 2: CLI Routing (9 items)
    "cli_routing": {
        "help_flag": ["--help"],
        "short_help": ['"-h"', "'-h'"],
        "help_word": ['"help"', "'help'"],
        "no_args": ["test_no_args", "test_introspection", "no_args"],
        "unknown_command": ["unknown_command", "invalid_command", "unrecognized"],
        "return_bool": ["is True", "is False"],
        "print_help": ["print_help"],
        "print_introspection": ["print_introspection"],
        "output_capture": ["capsys", "capfd", "StringIO"],
    },
    # Category 3: Conftest Fixtures (6 items)
    "conftest_fixtures": {
        "temp_dir": ["tmp_path", "temp_test_dir", "temp_dir"],
        "sample_data": ["sample_test_data", "sample_data"],
        "mock_infrastructure": ["mock_infrastructure", "autouse"],
        "mock_logger": ["mock_logger", "mock_log"],
        "mock_json_handler": ["mock_json_handler", "mock_json"],
        "cleanup": ["rmtree", "yield", "teardown"],
    },
    # Category 4: Error Resilience (4 items)
    "error_resilience": {
        "missing_file": ["FileNotFoundError", "missing_file", "file_not_found"],
        "corrupt_json": ["JSONDecodeError", "corrupt", "malformed"],
        "empty_file": ["empty_file", "empty_content"],
        "nonexistent_dir": ["nonexistent", "missing_dir", "not_a_dir"],
    },
    # Category 5: Return Type Contracts (4 items)
    "return_type_contracts": {
        "command_returns_bool": [
            "isinstance(result, bool)",
            "returns_bool",
            "return_type",
        ],
        "paths_return_path": ["isinstance(result, Path)", "pathlib.Path"],
        "ensure_returns_bool": ["ensure_json_exists", "is True"],
        "load_correct_type": ["isinstance(result, dict)", "isinstance(data, dict)"],
    },
    # Category 6: Exception Contracts (3 items)
    "exception_contracts": {
        "create_default_raises": [
            "pytest.raises(ValueError)",
            "ValueError",
            "_create_default",
        ],
        "save_invalid_raises": ["pytest.raises", "save_json"],
        "invalid_mode_raises": [
            "pytest.raises(ValueError)",
            "invalid_mode",
            "invalid_type",
        ],
    },
    # Category 7: Data Structure Contracts (3 items)
    "data_structure_contracts": {
        "config_keys": ["module_name", "config_keys"],
        "data_keys": ["last_updated", "data_keys"],
        "log_entry_field": ["log_entry", "operation"],
    },
    # Category 8: Success/Failure Paths (4 items)
    "success_failure_paths": {
        "known_routes_true": ["assert result is True", "== True"],
        "unknown_returns_false": ["assert result is False", "== False"],
        "help_preempts": ["--help"],
        "no_args_triggers": ["print_introspection"],
    },
    # Category 9: Init/Provisioning (4 items)
    "init_provisioning": {
        "creates_files": [".exists()", "ensure_json_exists"],
        "auto_creates_dir": ["mkdir", "makedirs"],
        "no_overwrite": ["overwrite", "no_clobber", "already_exists"],
        "returns_dict": ["isinstance(result, dict)", "json_type"],
    },
    # Category 10: Infrastructure Mocking (3 items)
    "infrastructure_mocking": {
        "autouse_fixtures": ["autouse=True", "autouse"],
        "sys_modules_mock": ["sys.modules"],
        "reimport_after_mock": ["importlib.reload", "reload("],
    },
}

TOTAL_ITEMS = sum(
    len(items) for items in STANDARD_CATEGORIES.values()
)


# =============================================
# BYPASS HELPER
# =============================================

def is_bypassed(
    file_path: str,
    standard: str,
    line: int | None = None,
    bypass_rules: list | None = None,
) -> bool:
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
# FILE HELPERS
# =============================================

def _read_file_safe(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.info("Cannot read %s for test quality analysis", path)
        return ""


def _find_all_test_files(branch_path: Path) -> list[Path]:
    """Find all test files and conftest.py in the branch's tests/ directory.

    Scans for any test_*.py file plus conftest.py -- no naming requirements.
    """
    tests_dir = branch_path / "tests"
    if not tests_dir.is_dir():
        return []

    results: list[Path] = []
    for p in sorted(tests_dir.iterdir()):
        if not p.is_file() or p.suffix != ".py":
            continue
        if p.name.startswith("test_") or p.name == "conftest.py":
            results.append(p)

    return results


# =============================================
# ANALYSIS
# =============================================

def _detect_all_coverage(
    file_sources: list[tuple[str, str]],
) -> dict[str, dict[str, str | None]]:
    """Scan test file sources for coverage across all standard categories.

    For each category, for each item, checks if ANY pattern matches in ANY
    source file. Returns the first file that covers each item.

    Args:
        file_sources: List of (filename, source_text) tuples.

    Returns:
        dict mapping category -> {item -> covering_filename or None}
    """
    coverage: dict[str, dict[str, str | None]] = {}

    for category, items in STANDARD_CATEGORIES.items():
        coverage[category] = {}
        for item_name, patterns in items.items():
            covering_file: str | None = None
            for filename, source in file_sources:
                for pattern in patterns:
                    if pattern in source:
                        covering_file = filename
                        break
                if covering_file is not None:
                    break
            coverage[category][item_name] = covering_file

    return coverage


# =============================================
# BRANCH-LEVEL CHECK
# =============================================

def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Run test quality analysis on a branch.

    Scans all test_*.py and conftest.py files in tests/ and evaluates
    coverage across 10 standard test categories.
    Score = total items covered / total items.

    Args:
        branch_path: Path to branch root directory.
        bypass_rules: Optional list of bypass rules from .seedgo/bypass.json.

    Returns:
        dict: {passed, score, checks, standard: 'TEST_QUALITY'}
    """
    checks: list[dict] = []
    bp = Path(branch_path)

    # Check if entire standard is bypassed
    if is_bypassed(branch_path, "test_quality", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "TEST_QUALITY",
        }

    # Validate branch path exists
    if not bp.is_dir():
        return {
            "passed": False,
            "checks": [
                {
                    "name": "Branch exists",
                    "passed": False,
                    "message": f"Branch directory not found: {branch_path}",
                }
            ],
            "score": 0,
            "standard": "TEST_QUALITY",
        }

    # Phase 1: Find all test files
    test_files = _find_all_test_files(bp)

    if not test_files:
        checks.append({
            "name": "Test files",
            "passed": False,
            "message": "No test_*.py or conftest.py files found in tests/ directory",
        })

        json_handler.log_operation(
            "check_completed",
            {
                "branch": branch_path,
                "score": 0,
                "standard": "test_quality",
                "test_files": 0,
                "items_covered": 0,
            },
        )

        return {
            "passed": False,
            "score": 0,
            "checks": checks,
            "standard": "TEST_QUALITY",
        }

    checks.append({
        "name": "Test files",
        "passed": True,
        "message": f"Found {len(test_files)} test file(s) in tests/",
    })

    # Phase 2: Read all test file sources
    file_sources: list[tuple[str, str]] = []
    for tf in test_files:
        source = _read_file_safe(tf)
        if source:
            file_sources.append((tf.name, source))

    # Phase 3: Detect coverage across all categories
    all_coverage = _detect_all_coverage(file_sources)

    total_items_covered = 0

    # Per-category summary checks
    for category, item_coverage in all_coverage.items():
        cat_total = len(item_coverage)
        cat_covered = sum(1 for f in item_coverage.values() if f is not None)
        total_items_covered += cat_covered
        missing_items = [
            item for item, f in item_coverage.items() if f is None
        ]

        if cat_covered == cat_total:
            checks.append({
                "name": category,
                "passed": True,
                "message": f"{category}: {cat_covered}/{cat_total} covered",
            })
        else:
            checks.append({
                "name": category,
                "passed": False,
                "message": (
                    f"{category}: {cat_covered}/{cat_total} covered "
                    f"(missing: {', '.join(missing_items)})"
                ),
            })

    # Score = coverage percentage
    score = int((total_items_covered / TOTAL_ITEMS) * 100)

    # Overall pass at 75%
    overall_passed = score >= 75

    # Overall summary check
    if overall_passed:
        checks.append({
            "name": "Overall coverage",
            "passed": True,
            "message": (
                f"{total_items_covered}/{TOTAL_ITEMS} items covered "
                f"across {len(STANDARD_CATEGORIES)} categories ({score}%)"
            ),
        })
    else:
        checks.append({
            "name": "Overall coverage",
            "passed": False,
            "message": (
                f"{total_items_covered}/{TOTAL_ITEMS} items covered "
                f"across {len(STANDARD_CATEGORIES)} categories ({score}%) "
                f"-- minimum 75% required"
            ),
        })

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "test_quality",
            "test_files": len(test_files),
            "items_covered": total_items_covered,
            "items_total": TOTAL_ITEMS,
            "category_detail": {
                cat: {
                    "covered": sum(
                        1 for f in items.values() if f is not None
                    ),
                    "total": len(items),
                }
                for cat, items in all_coverage.items()
            },
        },
    )

    return {
        "passed": overall_passed,
        "score": score,
        "checks": checks,
        "standard": "TEST_QUALITY",
    }
