"""
Seed Go Plugin: file-module-size

Flags Python files that exceed the recommended size limit.

Seed's internal standard: files should be <= 400 lines of code (excluding
blank lines, comments, and docstrings).

Large files are a code smell indicating:
- Too many responsibilities (SRP violation)
- Difficult to navigate and understand
- Hard to test thoroughly
- Likely candidates for refactoring

This is a WARNING, not an ERROR, because sometimes large files are unavoidable
or refactoring isn't immediately feasible.
"""

import ast
from pathlib import Path

from seedgo.models import CheckItem, CheckResult, Severity

PLUGIN_NAME = "file-module-size"
PLUGIN_DESCRIPTION = "Flag files exceeding 400 lines of code"
FILE_TYPES = ["*.py"]
PLUGIN_VERSION = "1.0.0"

# Default size limit (can be overridden in config)
DEFAULT_MAX_LINES = 400


def _count_code_lines(source: str) -> tuple[int, int]:
    """Count code lines in a Python file, excluding blanks, comments, and docstrings.

    Args:
        source: Python source code as a string

    Returns:
        Tuple of (total_lines, code_lines)
    """
    lines = source.splitlines()
    total_lines = len(lines)

    # Parse the AST to identify docstrings
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # If we can't parse, count all non-blank non-comment lines
        return total_lines, _count_simple_code_lines(lines)

    # Collect line numbers of all docstrings
    docstring_lines = set()
    for node in ast.walk(tree):
        # Only check nodes that can have docstrings
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            docstring = ast.get_docstring(node, clean=False)
            if docstring:
                # Docstring is the first statement if it's a constant string
                if node.body and isinstance(node.body[0], ast.Expr):
                    expr = node.body[0]
                    if isinstance(expr.value, ast.Constant) and isinstance(expr.value.value, str):
                        # Mark all lines from the start to end of this string literal
                        start_line = expr.lineno
                        end_line = expr.end_lineno or start_line
                        for line_num in range(start_line, end_line + 1):
                            docstring_lines.add(line_num)

    # Count code lines (non-blank, non-comment, non-docstring)
    code_lines = 0
    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            continue

        # Skip comment lines
        if stripped.startswith("#"):
            continue

        # Skip docstring lines
        if line_num in docstring_lines:
            continue

        # This is a code line
        code_lines += 1

    return total_lines, code_lines


def _count_simple_code_lines(lines: list[str]) -> int:
    """Simple line counting when AST parsing fails.

    Counts non-blank, non-comment lines (can't exclude docstrings without AST).

    Args:
        lines: List of source code lines

    Returns:
        Number of code lines
    """
    code_lines = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            code_lines += 1
    return code_lines


def _suggest_split_points(source: str) -> str:
    """Analyze the file and suggest logical split points.

    Args:
        source: Python source code

    Returns:
        String with suggestions for refactoring
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "Consider breaking into smaller modules"

    # Count top-level classes and functions
    classes = []
    functions = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)

    suggestions = []

    if len(classes) > 1:
        suggestions.append(f"Split {len(classes)} classes into separate files")

    if len(functions) > 5:
        suggestions.append(f"Group {len(functions)} module-level functions by responsibility")

    if classes and functions:
        suggestions.append("Separate utility functions from class definitions")

    if not suggestions:
        suggestions.append("Consider breaking into smaller modules by responsibility")

    return "; ".join(suggestions)


def check(file_path: str, config: dict | None = None) -> CheckResult:
    """Check if a Python file exceeds the size limit.

    Args:
        file_path: Absolute path to the Python file to check.
        config: Optional plugin config dict. Supports:
            max_lines (int): Maximum allowed code lines. Defaults to 400.

    Returns:
        CheckResult with file size check.
    """
    cfg = config or {}
    max_lines = cfg.get("max_lines", DEFAULT_MAX_LINES)

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
                    name="file-size",
                    passed=True,
                    message="Empty file.",
                    severity=Severity.WARNING,
                )
            ],
            file_path=file_path,
        )

    total_lines, code_lines = _count_code_lines(source)

    if code_lines <= max_lines:
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=True,
            checks=[
                CheckItem(
                    name="file-size",
                    passed=True,
                    message=f"File has {code_lines} code lines (within {max_lines} limit).",
                    severity=Severity.WARNING,
                )
            ],
            file_path=file_path,
            metadata={"total_lines": total_lines, "code_lines": code_lines, "max_lines": max_lines},
        )

    # File is too large
    suggestions = _suggest_split_points(source)
    overage = code_lines - max_lines

    return CheckResult(
        plugin=PLUGIN_NAME,
        passed=False,
        checks=[
            CheckItem(
                name="file-size",
                passed=False,
                message=f"File has {code_lines} code lines, exceeds limit of {max_lines} by {overage} lines",
                severity=Severity.WARNING,
                fix_hint=f"Consider breaking this file into smaller modules. {suggestions}",
            )
        ],
        file_path=file_path,
        metadata={"total_lines": total_lines, "code_lines": code_lines, "max_lines": max_lines},
    )
