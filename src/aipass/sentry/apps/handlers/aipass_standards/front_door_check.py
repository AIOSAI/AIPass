# =================== AIPass ====================
# Name: front_door_check.py
# Description: Front Door Standards Checker - a cross-branch import goes through the branch's package top file
# Version: 1.1.0
# Created: 2026-11-16
# Modified: 2026-11-16
# =============================================

"""Front Door Standards Checker

Reference: front_door.md. One finding per site (line, enclosing function): an import of another
branch that reaches under its ``apps/``. Detection is ``front_door_count.scan_source``, the same
reading the ``front-door`` verb counts with. A lines, functions or whole-file bypass row waives.
A second door (``modules_check.is_second_door``) is one more finding, line 1, that no row waives.
"""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards.check_support import read_text, result
from aipass.sentry.apps.handlers.aipass_standards.front_door_count import (
    APPS_KINDS,
    Reading,
    owner_of_path,
    scan_source,
)
from aipass.sentry.apps.handlers.aipass_standards.modules_check import is_second_door
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"
APPLIES_TO = "everywhere"
# An import hides in a package marker as easily as anywhere: the door file itself is judged too.
INCLUDE_INIT_FILES = True

STANDARD = "FRONT_DOOR"
STANDARD_KEY = "front_door"
MODULE_LEVEL = "<module>"


def _enclosing(tree: ast.AST) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function in source order, so the innermost def holding a line is the last match."""
    found = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return sorted(found, key=lambda n: n.lineno)


def _function_at(functions: List[ast.FunctionDef | ast.AsyncFunctionDef], line: int) -> str:
    """The innermost def holding the line, else ``<module>``."""
    name = MODULE_LEVEL
    for node in functions:
        if node.lineno <= line <= (node.end_lineno or node.lineno):
            name = node.name
    return name


def _message(file_name: str, reading: Reading) -> str:
    """One site's finding, with the door spelling that cures it."""
    how = {"statement": "import", "type_only": "TYPE_CHECKING import", "string": "string import"}[reading.via]
    return (
        f"{file_name}:{reading.line} {how} of {reading.target} reaches under {reading.branch}'s apps/ "
        f"- import it from the door: from aipass.{reading.branch} import <name>"
    )


def _second_door(path: Path) -> Dict:
    """The finding for a module under apps/modules that hands its branch's handler names outward."""
    branch = owner_of_path(str(path))
    return {
        "name": "Front door",
        "passed": False,
        "line": 1,
        "function": MODULE_LEVEL,
        "message": (
            f"{path.name} is a second door (retired pattern): it hands {branch}'s handler names out from apps/modules. "
            f"A branch has one door, its package top file: from aipass.{branch} import <name>; "
            f"retire this module once no other branch imports it"
        ),
    }


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list."""
    return [{"name": "Front door", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Convict every unwaived cross-branch import that reaches under another branch's apps/."""
    path = Path(module_path)
    if not path.exists():
        return result(False, _one_check(False, f"File not found: {module_path}"), 0, STANDARD)
    source = read_text(path, tag=STANDARD_KEY)
    if source is None:
        return result(False, _one_check(False, f"Error reading file: {module_path}"), 0, STANDARD)
    try:
        readings = scan_source(source, owner_of_path(module_path))
        functions = _enclosing(ast.parse(source))
    except (SyntaxError, ValueError) as exc:
        logger.warning("[front_door] Unparseable %s: %s", module_path, exc)
        return result(False, _one_check(False, f"Cannot be read as Python, imports unjudged: {exc}"), 0, STANDARD)

    # Never waived: the owner ruled a second door a retired pattern with no exception.
    checks = [_second_door(path)] if is_second_door(module_path, source) else []
    for reading in readings:
        if reading.kind not in APPS_KINDS:
            continue
        function = _function_at(functions, reading.line)
        if is_bypassed(module_path, STANDARD_KEY, reading.line, bypass_rules, function):
            continue
        checks.append(
            {
                "name": "Front door",
                "passed": False,
                "line": reading.line,
                "function": function,
                "message": _message(path.name, reading),
            }
        )
    if not checks:
        return result(True, _one_check(True, "Every cross-branch import goes through a front door"), 100, STANDARD)
    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "sites": len(checks)}
    )
    return result(False, checks, 0, STANDARD)
