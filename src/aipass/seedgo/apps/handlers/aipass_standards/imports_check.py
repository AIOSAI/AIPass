# =================== AIPass ====================
# Name: imports_check.py
# Description: Imports Standards Checker Handler
# Version: 2.4.0
# Created: 2026-03-05
# Modified: 2026-10-18
# =============================================

"""
Imports Standards Checker Handler

Reference: imports.md
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify

# APPLIES_TO: ordering and grouping read the same in a test file. The prax
# logger sub-rule is the one exception and gates itself below.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows import standards for pip packages."""
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

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
    # A door re-exports and logs nothing, whatever its length.
    is_door = path.name.startswith("door_") and path.parent.name == "modules"

    if not is_init_file:
        checks.append(check_no_aipass_root(import_lines, module_path, bypass_rules))

    if not is_init_file:
        checks.append(check_no_sys_path(import_lines, module_path, bypass_rules))

    exempt = is_init_file or is_small_file or is_door or is_handler
    if not exempt and not applicability.is_test_path(module_path):
        prax_check = check_prax_logger(import_lines, module_path, bypass_rules)
        if prax_check:
            checks.append(prax_check)

    if is_handler:
        handler_check = check_handler_independence(import_lines, module_path, bypass_rules)
        if handler_check:
            checks.append(handler_check)

    order_check = check_import_order(import_lines, module_path, bypass_rules)
    if order_check:
        checks.append(order_check)

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


def filter_docstrings(lines: List[str]) -> List[str]:
    """Blank out docstring and string-body lines, PRESERVING every line's position.

    Blanked, not skipped: every check on the result reports an index into this list as a file line,
    so compacting it would send each one to the wrong line. A fixture string's ``import x`` body is
    blanked too, since it is no import; a source that does not parse is returned unblanked.
    """
    source = "\n".join(line[:-1] if line.endswith("\n") else line for line in lines)
    try:
        kinds = classify(source)
    except UnparseableSource as exc:
        logger.info("imports: unparseable, no line blanked: %s", exc)
        return list(lines)
    blank = kinds.docstrings | kinds.string_bodies
    return ["\n" if i in blank else line for i, line in enumerate(lines, 1)]


def find_import_section_end(lines: List[str]) -> int:
    """Find where import section ends (first def/class)."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("async def "):
            return i
    return len(lines)


#: AIPASS_ROOT as a WHOLE TOKEN: the check means the env var, so ``AIPASS_ROOTS.json``, ``MY_AIPASS_ROOT``
#: and ``AIPASS_ROOT_MAP`` never match.
_AIPASS_ROOT_TOKEN = re.compile(r"\bAIPASS_ROOT\b")


def check_no_aipass_root(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Dict:
    """Check that file does NOT use AIPASS_ROOT."""
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "No AIPASS_ROOT", "passed": True, "message": "Bypassed by bypass rules"}

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code_part = line.split("#")[0] if "#" in line else line
        if _AIPASS_ROOT_TOKEN.search(code_part):
            return {
                "name": "No AIPASS_ROOT",
                "passed": False,
                "message": (
                    f"AIPASS_ROOT found on line {i} (pip packages must not read the AIPASS_ROOT environment variable)"
                ),
            }

    return {"name": "No AIPASS_ROOT", "passed": True, "message": "No AIPASS_ROOT usage (correct for pip packages)"}


def check_no_sys_path(lines: List[str], file_path: str = "", bypass_rules: list | None = None) -> Dict:
    """Check that file does NOT hack sys.path. Pip packages resolve imports via installed package paths."""
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
    """Check that logging is routed through the `aipass.prax` namespace.

    A test file is never asked (the caller gates on ``applicability.is_test_path``): the rule is about
    ROUTING, and a test does not log. ``from aipass.prax import logger`` and ``from aipass import prax``
    both pass: they route identically, and which form is recommended is @prax's contract (imports.md).
    """
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "Prax logger import", "passed": True, "message": "Bypassed by bypass rules"}

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "from aipass.prax" in stripped and "logger" in stripped:
            return {"name": "Prax logger import", "passed": True, "message": f"Found on line {i} (object form)"}
        if _imports_prax_module(stripped):
            return {"name": "Prax logger import", "passed": True, "message": f"Found on line {i} (module form)"}

    return {
        "name": "Prax logger import (recommended)",
        "passed": False,
        "message": (
            "Prax logger import not found (either form: 'from aipass.prax import logger' or 'from aipass import prax')"
        ),
    }


def _imports_prax_module(stripped: str) -> bool:
    """True for `from aipass import prax`, the rebindable module binding.

    Matched on the comma-separated import LIST so `from aipass import cli`
    never counts, and `from aipass import cli, prax` does.
    """
    source, separator, imported = stripped.partition(" import ")
    if not separator or source.strip() != "from aipass":
        return False
    names = imported.split("#")[0].split(",")
    return "prax" in [name.strip().split(" as ")[0].strip() for name in names]


def check_handler_independence(
    lines: List[str], module_path: str = "", bypass_rules: list | None = None
) -> Optional[Dict]:
    """Check that handlers don't import from parent branch modules."""
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
    """Check import order: stdlib -> third-party -> aipass.*"""
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "Import order", "passed": True, "message": "Bypassed by bypass rules"}

    imports = [
        (number, line.strip()) for number, line in enumerate(lines, 1) if line.strip().startswith(("import ", "from "))
    ]

    if not imports:
        return None

    last_stdlib_line = 0
    first_aipass_line = None

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
    """Check that file does NOT use bare or invalid import patterns."""
    if is_bypassed(file_path, "imports", None, bypass_rules):
        return {"name": "No bare imports", "passed": True, "message": "Bypassed by bypass rules"}

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

    old_namespaces = {"seed", "cortex", "nexus", "atlas", "sentinel"}

    violations = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        code_part = line.split("#")[0].strip() if "#" in line else stripped

        if not (code_part.startswith("from ") or code_part.startswith("import ")):
            continue

        if code_part.startswith("from "):
            match = re.match(r"from\s+([\w.]+)", code_part)
            if not match:
                continue
            import_path = match.group(1)
        else:
            match = re.match(r"import\s+([\w.]+)", code_part)
            if not match:
                continue
            import_path = match.group(1)

        parts = import_path.split(".")
        first_part = parts[0] if parts else ""

        if first_part in ("handlers", "modules"):
            violations.append(
                f'Line {i}: bare import "from {import_path}" '
                f"(must use aipass.* namespace, e.g. from aipass.seedgo.apps.standards.aipass.{import_path})"
            )
            continue

        if first_part in old_namespaces and len(parts) > 1:
            violations.append(
                f'Line {i}: old namespace "from {import_path}" (old namespace, must use aipass.* namespace)'
            )
            continue

        if first_part in aipass_modules and len(parts) > 1 and "apps" in parts:
            violations.append(
                f'Line {i}: bare module import "from {import_path}" '
                f"(missing aipass. prefix, should be from aipass.{import_path})"
            )
            continue

    if violations:
        shown = violations[:3]
        extra = f" (+{len(violations) - 3} more)" if len(violations) > 3 else ""
        return {"name": "No bare imports", "passed": False, "message": "; ".join(shown) + extra}

    return {"name": "No bare imports", "passed": True, "message": "All imports use proper aipass.* namespace"}
