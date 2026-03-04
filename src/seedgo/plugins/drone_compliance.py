"""Drone compliance check — verifies modules have proper drone integration.

Checks that Python packages in the aipass ecosystem provide:
1. A drone_adapter module
2. DRONE_MODULE metadata dict (name, version, description)
3. handle_command() function
4. get_help() function

This check runs on __init__.py files to identify packages, then looks
for their drone_adapter.py sibling.
"""

from __future__ import annotations

import ast
from pathlib import Path

from seedgo.models import CheckItem, CheckResult, Severity


def _get_missing_drone_module_keys(tree: ast.AST, required_keys: set[str]) -> set[str]:
    """Extract keys from DRONE_MODULE dict and return missing required keys.

    Args:
        tree: AST tree to search
        required_keys: Set of required key names

    Returns:
        Set of missing key names
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "DRONE_MODULE" for t in node.targets):
            continue

        # Found DRONE_MODULE assignment, check if value is a dict
        if not isinstance(node.value, ast.Dict):
            continue

        # Extract string keys from the dict
        found_keys = set()
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                found_keys.add(key.value)

        return required_keys - found_keys

    # DRONE_MODULE not found or not a dict
    return required_keys

PLUGIN_NAME = "drone-compliance"
PLUGIN_DESCRIPTION = "Verify modules provide drone adapter interface"
PLUGIN_VERSION = "1.0.0"
FILE_TYPES = ["__init__.py"]


def check(file_path: str, config: dict | None = None) -> CheckResult:
    """Check if the package containing this __init__.py is drone-compliant.

    Args:
        file_path: Absolute path to an __init__.py file.
        config: Optional plugin config dict. Supports:
            target_packages (list[str]): Package names to check.
                Defaults to ["aipass", "seedgo"].

    Returns:
        CheckResult with compliance check items.
    """
    path = Path(file_path)

    if not path.exists():
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=True,
            checks=[],
            file_path=file_path,
            metadata={"skipped": True, "reason": "file_not_found"},
        )

    package_dir = path.parent
    package_name = package_dir.name

    # Determine if this package should be checked
    cfg = config or {}
    target_packages = cfg.get("target_packages", ["aipass", "seedgo"])

    should_check = package_name in target_packages

    if not should_check:
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=True,
            checks=[
                CheckItem(
                    name="scope",
                    passed=True,
                    message=f"Package '{package_name}' is not a drone-target module, skipped.",
                    severity=Severity.INFO,
                )
            ],
            score=100,
            file_path=file_path,
            metadata={"skipped": True},
        )

    checks: list[CheckItem] = []
    adapter_path = package_dir / "drone_adapter.py"

    # Check 1: drone_adapter.py exists
    has_adapter = adapter_path.exists()
    checks.append(
        CheckItem(
            name="adapter-exists",
            passed=has_adapter,
            message=(
                f"drone_adapter.py found in {package_name}/"
                if has_adapter
                else f"Missing drone_adapter.py in {package_name}/ — module is not drone-routable"
            ),
            severity=Severity.ERROR if not has_adapter else Severity.INFO,
            fix_hint=(
                "Create drone_adapter.py with DRONE_MODULE, handle_command(), and get_help()"
                if not has_adapter
                else None
            ),
        )
    )

    if not has_adapter:
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=False,
            checks=checks,
            score=0,
            file_path=file_path,
            metadata={},
        )

    # Parse the adapter file with AST
    try:
        source = adapter_path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, OSError) as exc:
        checks.append(
            CheckItem(
                name="adapter-parseable",
                passed=False,
                message=f"drone_adapter.py has syntax error: {exc}",
                severity=Severity.ERROR,
            )
        )
        return CheckResult(
            plugin=PLUGIN_NAME,
            passed=False,
            checks=checks,
            score=0,
            file_path=file_path,
            metadata={},
        )

    # Check 2: DRONE_MODULE dict exists
    has_meta = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "DRONE_MODULE" for t in node.targets)
        for node in ast.walk(tree)
    )
    checks.append(
        CheckItem(
            name="drone-module-meta",
            passed=has_meta,
            message=(
                "DRONE_MODULE metadata dict found"
                if has_meta
                else "Missing DRONE_MODULE dict — drone can't read module metadata"
            ),
            severity=Severity.ERROR if not has_meta else Severity.INFO,
            fix_hint=(
                'Add: DRONE_MODULE = {"name": "...", "version": "...", "description": "..."}'
                if not has_meta
                else None
            ),
        )
    )

    # Check 2b: DRONE_MODULE dict has required keys (name, version, description)
    if has_meta:
        required_keys = {"name", "version", "description"}
        missing_keys = _get_missing_drone_module_keys(tree, required_keys)
        has_all_keys = len(missing_keys) == 0
        checks.append(
            CheckItem(
                name="drone-module-keys",
                passed=has_all_keys,
                message=(
                    "DRONE_MODULE has all required keys (name, version, description)"
                    if has_all_keys
                    else f"DRONE_MODULE missing required keys: {', '.join(sorted(missing_keys))}"
                ),
                severity=Severity.ERROR if not has_all_keys else Severity.INFO,
                fix_hint=(
                    f"Add missing keys to DRONE_MODULE: {', '.join(sorted(missing_keys))}"
                    if not has_all_keys
                    else None
                ),
            )
        )

    # Check 3: handle_command() function exists
    functions = [
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    has_handle = "handle_command" in functions
    checks.append(
        CheckItem(
            name="handle-command",
            passed=has_handle,
            message=(
                "handle_command() function found"
                if has_handle
                else "Missing handle_command() — drone can't route commands to this module"
            ),
            severity=Severity.ERROR if not has_handle else Severity.INFO,
            fix_hint=(
                "Add: def handle_command(command: str, args: list[str] | None = None) -> dict:"
                if not has_handle
                else None
            ),
        )
    )

    # Check 4: get_help() function exists
    has_help = "get_help" in functions
    checks.append(
        CheckItem(
            name="get-help",
            passed=has_help,
            message=(
                "get_help() function found"
                if has_help
                else "Missing get_help() — drone can't show help for this module"
            ),
            severity=Severity.WARNING if not has_help else Severity.INFO,
            fix_hint="Add: def get_help(command: str | None = None) -> str:" if not has_help else None,
        )
    )

    # Check 5: get_introspective() function exists (optional but recommended)
    has_introspective = "get_introspective" in functions
    checks.append(
        CheckItem(
            name="get-introspective",
            passed=has_introspective,
            message=(
                "get_introspective() function found — module supports introspection"
                if has_introspective
                else "Missing get_introspective() — introspection pattern recommended for drone modules"
            ),
            severity=Severity.WARNING if not has_introspective else Severity.INFO,
            fix_hint="Add: def get_introspective() -> dict:" if not has_introspective else None,
        )
    )

    # Score: errors block pass, warnings degrade
    error_checks = [c for c in checks if not c.passed and c.severity == Severity.ERROR]
    all_passed = len(error_checks) == 0

    # Simple scoring: deduct for failures
    failed_errors = len(error_checks)
    failed_warnings = len([c for c in checks if not c.passed and c.severity == Severity.WARNING])
    total_weight = len(checks)
    deductions = failed_errors * 1.0 + failed_warnings * 0.5
    score = int(((total_weight - deductions) / max(total_weight, 1)) * 100)

    return CheckResult(
        plugin=PLUGIN_NAME,
        passed=all_passed,
        checks=checks,
        score=score,
        file_path=file_path,
        metadata={"adapter_path": str(adapter_path)},
    )
