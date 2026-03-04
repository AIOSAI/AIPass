"""
Seed Go Plugin: silent-failure-detection

Detects silent failure patterns in Python code:
- except: pass (bare except with only pass)
- except Exception: pass (catches all exceptions and silently ignores)

Silent failures hide errors and make debugging extremely difficult. They can
mask critical issues like KeyboardInterrupt, SystemExit, or legitimate bugs.

Best practice: Always log exceptions or provide meaningful error handling.
If ignoring an exception is intentional, add a comment explaining why.
"""

import ast
from pathlib import Path

from seedgo.models import CheckItem, CheckResult, Severity

PLUGIN_NAME = "silent-failure-detection"
PLUGIN_DESCRIPTION = "Detect silent failure patterns (except: pass)"
FILE_TYPES = ["*.py"]
PLUGIN_VERSION = "1.0.0"


class SilentFailureVisitor(ast.NodeVisitor):
    """AST visitor that detects silent failure patterns in exception handlers.

    Identifies except blocks that only contain a pass statement, which silently
    swallow exceptions without logging or handling them.
    """

    def __init__(self):
        self.violations: list[CheckItem] = []

    def visit_Try(self, node: ast.Try) -> None:
        """Visit try/except blocks and check for silent failures.

        Args:
            node: The Try node to check
        """
        for handler in node.handlers:
            if self._is_silent_failure(handler):
                exception_type = self._get_exception_type_name(handler)
                self.violations.append(
                    CheckItem(
                        name="silent-failure",
                        passed=False,
                        message=f"Silent failure at line {handler.lineno}: {exception_type} with only 'pass' — exceptions are hidden",
                        severity=Severity.ERROR,
                        line=handler.lineno,
                        fix_hint=self._get_fix_hint(exception_type),
                    )
                )

        # Continue visiting child nodes
        self.generic_visit(node)

    def _is_silent_failure(self, handler: ast.ExceptHandler) -> bool:
        """Check if an exception handler is a silent failure.

        A silent failure is an except block that only contains a pass statement
        (or is empty, which is treated as pass).

        Args:
            handler: The exception handler to check

        Returns:
            True if this is a silent failure pattern
        """
        # Empty handler body or only pass statement
        if not handler.body:
            return True

        # Single pass statement
        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
            return True

        # Multiple statements, but all are pass (unusual but possible)
        if all(isinstance(stmt, ast.Pass) for stmt in handler.body):
            return True

        return False

    def _get_exception_type_name(self, handler: ast.ExceptHandler) -> str:
        """Extract the exception type name from a handler.

        Args:
            handler: The exception handler

        Returns:
            String representation of the exception type (e.g., "except:", "except Exception:")
        """
        if handler.type is None:
            return "except:"

        # Handle simple names like "Exception"
        if isinstance(handler.type, ast.Name):
            return f"except {handler.type.id}:"

        # Handle tuple of exceptions like (ValueError, TypeError)
        if isinstance(handler.type, ast.Tuple):
            names = []
            for elt in handler.type.elts:
                if isinstance(elt, ast.Name):
                    names.append(elt.id)
            if names:
                return f"except ({', '.join(names)}):"

        # Fallback for complex types
        return "except <unknown>:"

    def _get_fix_hint(self, exception_type: str) -> str:
        """Generate a fix hint based on the exception type.

        Args:
            exception_type: The exception type string

        Returns:
            Actionable fix hint
        """
        if exception_type == "except:":
            return (
                "Replace with 'except Exception:' and add logging or error handling. "
                "If ignoring is intentional, add a comment explaining why."
            )
        else:
            return (
                "Add logging (e.g., logger.warning('Ignoring error', exc_info=True)) "
                "or meaningful error handling. If ignoring is intentional, add a comment explaining why."
            )


def check(file_path: str, config: dict | None = None) -> CheckResult:
    """Check a Python file for silent failure patterns.

    Args:
        file_path: Absolute path to the Python file to check.
        config: Optional plugin config dict (unused by this plugin).

    Returns:
        CheckResult with one CheckItem per silent failure found.
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
                    name="silent-failure-detection",
                    passed=True,
                    message="Empty file — no code to check.",
                    severity=Severity.ERROR,
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

    # Use visitor pattern to find silent failures
    visitor = SilentFailureVisitor()
    visitor.visit(tree)
    violations = visitor.violations

    if violations:
        passed = False
        checks = violations
    else:
        passed = True
        checks = [
            CheckItem(
                name="silent-failure-detection",
                passed=True,
                message="No silent failure patterns found.",
                severity=Severity.ERROR,
            )
        ]

    return CheckResult(
        plugin=PLUGIN_NAME,
        passed=passed,
        checks=checks,
        file_path=file_path,
        metadata={"violations_found": len(violations)},
    )
