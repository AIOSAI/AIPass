# =================== AIPass ====================
# Name: imports_check.py
# Description: Imports Standards Checker Handler
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Imports Standards Checker Handler

Validates module compliance with AIPass import standards for pip packages.
Checks for clean pip-style imports: no AIPASS_ROOT, no sys.path hacking,
proper aipass.* namespace usage, correct import order.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"


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
    Check if module follows import standards for pip packages.

    Checks:
    1. No AIPASS_ROOT usage (pip packages don't need it)
    2. No sys.path hacking (pip packages resolve via installed paths)
    3. Prax logger via aipass.prax namespace (if applicable)
    4. Handler independence (no parent module imports)
    5. Import order (stdlib -> third-party -> aipass.*)
    6. No bare/invalid imports (must use aipass.* namespace)
    """
    checks = []
    path = Path(module_path)

    # Python package marker — no imports required by convention
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Package marker",
                    "passed": True,
                    "message": "__init__.py — Python package marker, no import checks",
                }
            ],
            "score": 100,
            "standard": "IMPORTS",
        }

    if is_bypassed(module_path, "imports", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "IMPORTS",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "IMPORTS",
        }

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
            "standard": "IMPORTS",
        }

    filtered_lines = filter_docstrings(lines)
    import_section_end = find_import_section_end(filtered_lines)
    import_lines = filtered_lines[:import_section_end]

    is_handler = "/handlers/" in module_path
    is_init_file = path.name == "__init__.py"
    is_small_file = len([line for line in lines if line.strip() and not line.strip().startswith("#")]) < 20

    # Check 1: No AIPASS_ROOT (pip packages must not use it)
    if not is_init_file:
        checks.append(check_no_aipass_root(import_lines, module_path, bypass_rules))

    # Check 2: No sys.path hacking (pip packages resolve via installed paths)
    if not is_init_file:
        checks.append(check_no_sys_path(import_lines, module_path, bypass_rules))

    # Check 3: Prax logger via aipass.prax (not for handlers, small files, or __init__)
    if not is_init_file and not is_small_file and not is_handler:
        prax_check = check_prax_logger(import_lines, module_path, bypass_rules)
        if prax_check:
            checks.append(prax_check)

    # Check 4: Handler independence (handlers must not import parent modules)
    if is_handler:
        handler_check = check_handler_independence(import_lines, module_path, bypass_rules)
        if handler_check:
            checks.append(handler_check)

    # Check 5: Import order (stdlib -> third-party -> aipass.*)
    order_check = check_import_order(import_lines, module_path, bypass_rules)
    if order_check:
        checks.append(order_check)

    # Check 6: No bare/invalid imports (must use aipass.* namespace)
    if not is_init_file:
        bare_check = check_no_bare_imports(import_lines, module_path, bypass_rules)
        if bare_check:
            checks.append(bare_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "imports"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "IMPORTS"}


def _process_docstring_marker(stripped, in_docstring, docstring_marker):
    marker = '"""' if '"""' in stripped else "'''"
    marker_count = stripped.count(marker)

    if not in_docstring:
        if marker_count >= 2:
            return True, in_docstring, docstring_marker
        elif marker_count == 1:
            return True, True, marker
    else:
        if marker == docstring_marker and marker_count >= 1:
            return True, False, None

    return False, in_docstring, docstring_marker


def filter_docstrings(lines: List[str]) -> List[str]:
    """Filter out docstrings from lines to prevent false positives."""
    filtered_lines = []
    in_docstring = False
    docstring_marker = None

    for line in lines:
        stripped = line.strip()

        if '"""' in stripped or "'''" in stripped:
            skip, in_docstring, docstring_marker = _process_docstring_marker(stripped, in_docstring, docstring_marker)
            if skip:
                continue

        if in_docstring:
            continue

        filtered_lines.append(line)

    return filtered_lines


def find_import_section_end(lines: List[str]) -> int:
    """Find where import section ends (first def/class)."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("async def "):
            return i
    return len(lines)


def check_no_aipass_root(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Dict:
    """
    Check that file does NOT use AIPASS_ROOT.
    Pip packages resolve paths via installed package paths, not AIPASS_ROOT.
    """
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "No AIPASS_ROOT", "passed": True, "message": "Bypassed by bypass rules"}

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code_part = line.split("#")[0] if "#" in line else line
        if "AIPASS_ROOT" in code_part:
            return {
                "name": "No AIPASS_ROOT",
                "passed": False,
                "message": f"AIPASS_ROOT found on line {i} (pip packages must not use AIPASS_ROOT)",
            }

    return {"name": "No AIPASS_ROOT", "passed": True, "message": "No AIPASS_ROOT usage (correct for pip packages)"}


def check_no_sys_path(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Dict:
    """
    Check that file does NOT hack sys.path.
    Pip packages resolve imports via installed package paths.
    """
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "No sys.path hacking", "passed": True, "message": "Bypassed by bypass rules"}

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code_part = line.split("#")[0] if "#" in line else line
        if re.search(r"sys\.path\.(insert|append)\s*\(", code_part):
            return {
                "name": "No sys.path hacking",
                "passed": False,
                "message": f"sys.path manipulation found on line {i} (pip packages must not hack sys.path)",
            }

    return {
        "name": "No sys.path hacking",
        "passed": True,
        "message": "No sys.path manipulation (correct for pip packages)",
    }


def check_prax_logger(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check for Prax logger import via aipass.prax namespace.
    Pattern: from aipass.prax import logger
    """
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "Prax logger import", "passed": True, "message": "Bypassed by bypass rules"}

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "from aipass.prax" in line and "logger" in line:
            return {"name": "Prax logger import", "passed": True, "message": f"Found on line {i}"}

    return {
        "name": "Prax logger import (recommended)",
        "passed": False,
        "message": "Prax logger import not found (recommended: from aipass.prax import logger)",
    }


def check_handler_independence(
    lines: List[str], module_path: str = "", bypass_rules: list | None = None
) -> Optional[Dict]:
    """
    Check that handlers don't import from parent branch modules.
    Allowed: from aipass.prax import ... (infrastructure)
    Allowed: from aipass.cli import ... (infrastructure)
    Forbidden: from <parent>.apps.modules import ...
    """
    if is_bypassed(module_path, "imports", None, bypass_rules):
        return {"name": "Handler independence", "passed": True, "message": "Bypassed by bypass rules"}

    parent_branch = None
    if module_path:
        path_parts = Path(module_path).parts
        for i, part in enumerate(path_parts):
            if part == "apps" and i > 0:
                parent_branch = path_parts[i - 1]
                break

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if ".apps.modules" in line and ("from " in line or "import " in line):
            code_part = line.split("#")[0] if "#" in line else line
            if ".apps.modules" not in code_part:
                continue

            # Allowed: aipass.prax, aipass.cli (infrastructure services)
            if "aipass.prax" in code_part or "aipass.cli" in code_part:
                continue

            if parent_branch and f"{parent_branch}.apps.modules" in code_part:
                return {
                    "name": "Handler independence",
                    "passed": False,
                    "message": f"Handler importing from parent module on line {i} (violates independence rule)",
                }

            if not parent_branch:
                return {
                    "name": "Handler independence",
                    "passed": False,
                    "message": f"Handler importing from branch module on line {i} (violates independence rule)",
                }

    return {"name": "Handler independence", "passed": True, "message": "No forbidden module imports detected"}


def check_import_order(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check import order: stdlib -> third-party -> aipass.*

    For pip packages, the order should be:
    1. Standard library (import os, from pathlib, etc.)
    2. Third-party packages (import rich, etc.)
    3. aipass.* namespace imports (from aipass.prax, from aipass.cli, etc.)
    """
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "Import order", "passed": True, "message": "Bypassed by bypass rules"}

    imports = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append((i, stripped))

    if not imports:
        return None

    # Track where aipass.* imports appear vs stdlib
    last_stdlib_line = 0
    first_aipass_line = None

    # Common stdlib modules
    stdlib_prefixes = (
        "import os",
        "import sys",
        "import re",
        "import json",
        "import time",
        "import logging",
        "import subprocess",
        "import shutil",
        "import copy",
        "import hashlib",
        "import datetime",
        "import tempfile",
        "import ast",
        "import argparse",
        "import importlib",
        "import inspect",
        "import unittest",
        "from pathlib",
        "from typing",
        "from datetime",
        "from collections",
        "from functools",
        "from dataclasses",
        "from enum",
        "from abc",
        "from io",
        "from os",
        "from contextlib",
    )

    for line_num, import_stmt in imports:
        if any(import_stmt.startswith(p) for p in stdlib_prefixes):
            last_stdlib_line = line_num
        elif "from aipass." in import_stmt or import_stmt.startswith("import aipass"):
            if first_aipass_line is None:
                first_aipass_line = line_num

    if first_aipass_line and last_stdlib_line and first_aipass_line < last_stdlib_line:
        return {
            "name": "Import order",
            "passed": False,
            "message": f"aipass.* import (line {first_aipass_line}) before stdlib import (line {last_stdlib_line})",
        }

    return {"name": "Import order", "passed": True, "message": "Import order correct (stdlib before aipass.*)"}


def check_no_bare_imports(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check that file does NOT use bare or invalid import patterns.

    INVALID patterns:
    - from handlers.{name} import ...  (bare handler import, missing namespace)
    - from modules.{name} import ...   (bare module import, missing namespace)
    - from {module}.apps...            (bare module, missing aipass. prefix)
    - from <old>.apps...               (old namespace, now aipass.seedgo)
    - from prax.apps...                (bare, should be from aipass.prax...)

    VALID patterns:
    - from aipass.{module}.apps.modules.{name} import ...
    - from aipass.{module}.apps.handlers.{name} import ...
    - from .{name} import ...  (relative re-export in __init__.py ONLY — excluded by caller)
    - Standard library / third-party imports
    """
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "No bare imports", "passed": True, "message": "Bypassed by bypass rules"}

    # Known AIPass module names (used to detect bare module imports like "from drone.apps...")
    aipass_modules = {
        "drone",
        "seedgo",
        "prax",
        "cli",
        "flow",
        "ai_mail",
        "api",
        "trigger",
        "spawn",
        "devpulse",
    }

    # Old namespaces that should not appear
    old_namespaces = {"seed", "cortex", "nexus", "atlas", "sentinel"}

    violations = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        code_part = line.split("#")[0].strip() if "#" in line else stripped

        # Only check import statements
        if not (code_part.startswith("from ") or code_part.startswith("import ")):
            continue

        # Extract the module path from "from X import Y" or "import X"
        if code_part.startswith("from "):
            # "from X.Y.Z import thing" -> extract "X.Y.Z"
            match = re.match(r"from\s+([\w.]+)", code_part)
            if not match:
                continue
            import_path = match.group(1)
        else:
            # "import X.Y.Z" -> extract "X.Y.Z"
            match = re.match(r"import\s+([\w.]+)", code_part)
            if not match:
                continue
            import_path = match.group(1)

        parts = import_path.split(".")
        first_part = parts[0] if parts else ""

        # Check 1: Bare handler/module imports (from handlers.X or from modules.X)
        if first_part in ("handlers", "modules"):
            violations.append(
                f'Line {i}: bare import "from {import_path}" '
                f"(must use aipass.* namespace, e.g. from aipass.seedgo.apps.standards.aipass.{import_path})"
            )
            continue

        # Check 2: Old namespaces (pre-AIPass imports that should not appear)
        if first_part in old_namespaces and len(parts) > 1:
            violations.append(
                f'Line {i}: old namespace "from {import_path}" (old namespace, must use aipass.* namespace)'
            )
            continue

        # Check 3: Bare AIPass module imports (from drone.apps... instead of from aipass.drone.apps...)
        if first_part in aipass_modules and len(parts) > 1 and "apps" in parts:
            violations.append(
                f'Line {i}: bare module import "from {import_path}" '
                f"(missing aipass. prefix, should be from aipass.{import_path})"
            )
            continue

    if violations:
        # Show up to 3 violations in the message
        shown = violations[:3]
        extra = f" (+{len(violations) - 3} more)" if len(violations) > 3 else ""
        return {"name": "No bare imports", "passed": False, "message": "; ".join(shown) + extra}

    return {"name": "No bare imports", "passed": True, "message": "All imports use proper aipass.* namespace"}
