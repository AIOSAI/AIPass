# =================== AIPass ====================
# Name: handlers_check.py
# Description: Handlers Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Handlers Standards Checker Handler

Validates handler compliance with AIPass handler standards.
Checks handler independence, auto-detection pattern, no orchestration.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"

# Cross-handler/orchestration imports are purely import-statement checks, so a
# violation hiding in a package marker file must not be invisible to the audit
# the way it would be for content checkers (dead code, naming, etc.).
INCLUDE_INIT_FILES = True


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if handler follows handler standards

    Args:
        module_path: Path to Python handler to check
        bypass_rules: Optional list of bypass rules to apply

    Returns:
        dict: {
            'passed': bool,           # Overall pass/fail
            'checks': [               # Individual check results
                {
                    'name': str,      # Check name
                    'passed': bool,   # Pass/fail
                    'message': str,   # Details
                }
            ],
            'score': int,             # 0-100 percentage
            'standard': str           # Standard name
        }
    """
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "handlers", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "HANDLERS",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "HANDLERS",
        }

    # Read file
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "HANDLERS",
        }

    # Only check files in handlers/ directory
    is_handler = "apps/handlers/" in module_path
    if not is_handler:
        return {
            "passed": True,
            "checks": [{"name": "Handler check", "passed": True, "message": "Not a handler file (skipped)"}],
            "score": 100,
            "standard": "HANDLERS",
        }

    # Check 1: Handler independence (no cross-handler imports except defaults)
    independence_check = check_handler_independence(content, lines, module_path)
    checks.append(independence_check)

    # Check 2: Auto-detection pattern (if module_name parameter exists)
    auto_detect_check = check_auto_detection(content)
    if auto_detect_check:
        checks.append(auto_detect_check)

    # Check 3: No orchestration logic (handlers shouldn't import modules)
    orchestration_check = check_no_orchestration(content, lines)
    if orchestration_check:
        checks.append(orchestration_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "handlers"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "HANDLERS"}


def _iter_import_modules(content: str) -> Iterator[Tuple[int, str, List[str]]]:
    """
    Parse content and yield (line_number, dotted_module, imported_names) for every
    real import statement — string literals, comments and docstrings can never
    produce a hit because the AST only contains actual import nodes.

    Relative imports (from . import x) are omitted entirely: they can't reference
    an absolute dotted path like "apps.handlers"/"apps.modules" and are always
    same-package, so callers don't need to special-case them.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.info("Skipping import scan: SyntaxError during parse: %s", e)
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            yield node.lineno, node.module or "", [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, []


def _line_text(lines: List[str], lineno: int, fallback: str) -> str:
    """Return the source line at 1-indexed lineno, or a fallback if out of range."""
    if 0 < lineno <= len(lines):
        return lines[lineno - 1].strip()
    return fallback


def _branch_of_path(module_path: str) -> Optional[str]:
    """Return the branch a file lives in, from the path segment before 'apps'.

    src/aipass/trigger/apps/handlers/escalation.py -> 'trigger'
    Absolute paths work too: the repo root ('AIPass') never equals 'apps'.
    """
    path_parts = Path(module_path).parts
    for i, part in enumerate(path_parts):
        if part == "apps" and i > 0:
            return path_parts[i - 1]
    return None


def _branch_of_import(module: str) -> Optional[str]:
    """Return the branch an 'apps.handlers' import targets.

    aipass.trigger.apps.handlers.events.error_detected -> 'trigger'
    Also handles the bare form: aipass.trigger.apps.handlers -> 'trigger'
    """
    prefix = module.split(".apps.handlers", 1)[0]
    parts = prefix.split(".")
    return parts[-1] if parts and parts[-1] else None


def check_handler_independence(content: str, lines: List[str], module_path: str) -> Dict:
    """
    Check handler independence - handlers are private to their own branch.

    The rule is branch-level, matching the published standard:
    - ALLOWED: same-branch handler imports, EVEN ACROSS PACKAGES
      (flow/apps/handlers/plan/create.py -> aipass.flow.apps.handlers.registry.load)
    - ALLOWED: from .decorators import catch_errors (relative, same package)
    - FORBIDDEN: cross-BRANCH handler imports -- another branch's handlers are
      private; consume its modules/ instead.

    Comparing packages instead of branches was the old behaviour. It rejected
    the standard's own documented ALLOWED example, and for a handler sitting at
    the handlers/ root it compared against the FILENAME, so such files could
    never pass whatever they imported.
    """
    forbidden_imports = []

    own_branch = _branch_of_path(module_path)
    if own_branch is None:
        # Not a recognisable branch layout -- the same-branch rule is not
        # evaluable here. Say so rather than flag every import as cross-branch.
        return {
            "name": "Handler independence",
            "passed": True,
            "message": "Branch could not be determined from path (independence rule not evaluated)",
        }

    for lineno, module, _names in _iter_import_modules(content):
        if "apps.handlers" not in module:
            continue

        # Allowed: any handler in this branch, whatever package it sits in
        if _branch_of_import(module) == own_branch:
            continue

        # Forbidden: another branch's handlers are not ours to import
        forbidden_imports.append(f"line {lineno}: {_line_text(lines, lineno, module)}")

    if forbidden_imports:
        return {
            "name": "Handler independence",
            "passed": False,
            "message": "Cross-branch handler imports detected (use that branch's modules/ instead): "
            + "; ".join(forbidden_imports),
        }

    return {"name": "Handler independence", "passed": True, "message": "No forbidden cross-branch handler imports"}


def check_auto_detection(content: str) -> Optional[Dict]:
    """
    Check for auto-detection pattern if handler accepts module_name

    If handler has module_name parameter, should use inspect.stack() auto-detection
    """
    # Check if any function accepts module_name parameter
    has_module_name_param = bool(re.search(r"def\s+\w+\([^)]*module_name", content))

    if not has_module_name_param:
        return None  # No module_name parameter, auto-detection not needed

    # Check for auto-detection implementation
    has_inspect_import = "import inspect" in content
    has_stack_usage = "inspect.stack()" in content
    has_auto_detect_function = "_get_caller_module_name" in content or "get_caller" in content

    if has_auto_detect_function or (has_inspect_import and has_stack_usage):
        return {
            "name": "Auto-detection pattern",
            "passed": True,
            "message": "Auto-detection pattern implemented (inspect.stack())",
        }

    # Has module_name param but no auto-detection
    return {
        "name": "Auto-detection pattern",
        "passed": False,
        "message": "Has module_name parameter but missing auto-detection (use inspect.stack())",
    }


def check_no_orchestration(content: str, lines: List[str]) -> Optional[Dict]:
    """
    Check that handler doesn't import/call modules (orchestration)

    Handlers should be pure implementation, not orchestration.
    FORBIDDEN: from aipass.seedgo.apps.modules import some_module
    """
    module_imports = []

    for lineno, module, _names in _iter_import_modules(content):
        if "apps.modules" not in module:
            continue

        # Allowed: Service imports (prax.apps.modules.logger, cli.apps.modules)
        if "prax.apps.modules.logger" in module or "cli.apps.modules" in module:
            continue

        # Forbidden: Module imports (orchestration)
        module_imports.append(f"line {lineno}: {_line_text(lines, lineno, module)}")

    if module_imports:
        return {
            "name": "No orchestration",
            "passed": False,
            "message": "Handler imports modules (orchestration): " + "; ".join(module_imports),
        }

    return {"name": "No orchestration", "passed": True, "message": "No module imports detected (pure implementation)"}
