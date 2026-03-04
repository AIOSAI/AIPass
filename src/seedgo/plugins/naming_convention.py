"""
Seed Go Plugin: naming-convention

Enforces Python naming conventions:
- snake_case for functions, variables, and module names
- PascalCase for classes
- UPPER_CASE for module-level constants

This is a fundamental Python style rule (PEP 8) that improves code readability
and consistency across projects.
"""

import ast
import re
from pathlib import Path

from seedgo.models import CheckItem, CheckResult, Severity

PLUGIN_NAME = "naming-convention"
PLUGIN_DESCRIPTION = "Enforce Python naming conventions (PEP 8)"
FILE_TYPES = ["*.py"]
PLUGIN_VERSION = "1.0.0"

# Naming patterns
_SNAKE_CASE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_UPPER_CASE_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Common exceptions that are acceptable
_COMMON_EXCEPTIONS = {
    # Common single-letter variables
    "i", "j", "k", "n", "x", "y", "z", "a", "b", "c",
    # Common acronyms/names that are conventionally capitalized
    "T", "K", "V",
    # Special methods and variables
    "_", "__",
}


def _is_constant(node: ast.Assign | ast.AnnAssign, scope: str) -> bool:
    """Determine if an assignment is a module-level constant.

    Constants are defined as module-level assignments where:
    1. The name is in UPPER_CASE
    2. The assignment is at module level (not in a function/class)

    Args:
        node: Assignment node
        scope: "module", "class", or "function"

    Returns:
        True if this appears to be a constant
    """
    if scope != "module":
        return False

    # Get target names
    if isinstance(node, ast.Assign):
        targets = node.targets
    else:  # AnnAssign
        targets = [node.target]

    for target in targets:
        if isinstance(target, ast.Name):
            # Consider it a constant if it matches UPPER_CASE pattern
            if _UPPER_CASE_RE.match(target.id):
                return True

    return False


def check(file_path: str, config: dict | None = None) -> CheckResult:
    """Check a Python file for naming convention violations.

    Args:
        file_path: Absolute path to the Python file to check.
        config: Optional plugin config dict (unused by this plugin).

    Returns:
        CheckResult with one CheckItem per naming violation found.
    """
    _ = config  # Part of plugin interface contract

    try:
        source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=True,
            checks=[],
            file_path=file_path,
            metadata={"skipped": True, "reason": "file_read_error"},
        )

    if not source.strip():
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=True,
            checks=[
                CheckItem(
                    name="naming-convention",
                    passed=True,
                    message="Empty file — no names to check.",
                    severity=Severity.WARNING,
                )
            ],
            file_path=file_path,
        )

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=True,
            checks=[],
            file_path=file_path,
            metadata={"skipped": True, "reason": "syntax_error"},
        )

    violations: list[CheckItem] = []

    # Check module name (file name)
    module_name = Path(file_path).stem
    if module_name not in ("__init__", "__main__") and not _SNAKE_CASE_RE.match(module_name):
        violations.append(
            CheckItem(
                name="module-name",
                passed=False,
                message=f"Module name '{module_name}' should be snake_case",
                severity=Severity.WARNING,
                fix_hint=f"Rename file to use snake_case (e.g., {_to_snake_case(module_name)}.py)",
            )
        )

    # Walk the AST and check naming
    for node in ast.walk(tree):
        # Check class names (should be PascalCase)
        if isinstance(node, ast.ClassDef):
            if not _PASCAL_CASE_RE.match(node.name) and node.name not in _COMMON_EXCEPTIONS:
                violations.append(
                    CheckItem(
                        name="class-name",
                        passed=False,
                        message=f"Class '{node.name}' at line {node.lineno} should be PascalCase",
                        severity=Severity.WARNING,
                        line=node.lineno,
                        fix_hint=f"Rename to PascalCase (e.g., {_to_pascal_case(node.name)})",
                    )
                )

        # Check function names (should be snake_case)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip dunder methods
            if node.name.startswith("__") and node.name.endswith("__"):
                continue

            if not _SNAKE_CASE_RE.match(node.name) and node.name not in _COMMON_EXCEPTIONS:
                violations.append(
                    CheckItem(
                        name="function-name",
                        passed=False,
                        message=f"Function '{node.name}' at line {node.lineno} should be snake_case",
                        severity=Severity.WARNING,
                        line=node.lineno,
                        fix_hint=f"Rename to snake_case (e.g., {_to_snake_case(node.name)})",
                    )
                )

    # Check module-level variables and constants
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            # Determine if this is a constant or variable
            is_const = _is_constant(node, "module")

            # Get target names
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:  # AnnAssign
                targets = [node.target]

            for target in targets:
                if isinstance(target, ast.Name):
                    name = target.id

                    # Skip special variables
                    if name.startswith("__") and name.endswith("__"):
                        continue

                    if name in _COMMON_EXCEPTIONS:
                        continue

                    # Check naming based on whether it's a constant
                    if is_const:
                        if not _UPPER_CASE_RE.match(name):
                            violations.append(
                                CheckItem(
                                    name="constant-name",
                                    passed=False,
                                    message=f"Module-level constant '{name}' at line {node.lineno} should be UPPER_CASE",
                                    severity=Severity.WARNING,
                                    line=node.lineno,
                                    fix_hint=f"Rename to UPPER_CASE (e.g., {name.upper()})",
                                )
                            )
                    else:
                        if not _SNAKE_CASE_RE.match(name):
                            violations.append(
                                CheckItem(
                                    name="variable-name",
                                    passed=False,
                                    message=f"Module-level variable '{name}' at line {node.lineno} should be snake_case",
                                    severity=Severity.WARNING,
                                    line=node.lineno,
                                    fix_hint=f"Rename to snake_case (e.g., {_to_snake_case(name)})",
                                )
                            )

    if violations:
        passed = False
        checks = violations
    else:
        passed = True
        checks = [
            CheckItem(
                name="naming-convention",
                passed=True,
                message="All names follow Python naming conventions (PEP 8).",
                severity=Severity.WARNING,
            )
        ]

    return CheckResult(
        plugin=PLUGIN_NAME,
        passed=passed,
        checks=checks,
        file_path=file_path,
        metadata={"violations_found": len(violations)},
    )


def _to_snake_case(name: str) -> str:
    """Convert a name to snake_case suggestion.

    Args:
        name: Original name

    Returns:
        Suggested snake_case version
    """
    # Simple conversion: insert underscores before uppercase letters
    result = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return result


def _to_pascal_case(name: str) -> str:
    """Convert a name to PascalCase suggestion.

    Args:
        name: Original name

    Returns:
        Suggested PascalCase version
    """
    # Split on underscores and capitalize each word
    words = name.split("_")
    return "".join(word.capitalize() for word in words if word)
