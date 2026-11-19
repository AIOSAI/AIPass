# =================== AIPass ====================
# Name: naming_check.py
# Description: Naming Standards Checker Handler
# Version: 1.2.0
# Created: 2026-03-05
# Modified: 2026-11-16
# =============================================

"""
Naming Standards Checker Handler

Validates module compliance with AIPass naming standards.
Checks file naming, function naming, variable naming, constant naming.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Optional
from aipass.prax import logger
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE, is_bypassed
from aipass.sentry.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify, hash_lines

# APPLIES_TO: snake_case and column-0 constants are the house style everywhere.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

# A bare dotted name and nothing else — `_h.save_json`, `mod.InvalidDocument`.
# Anchored on both ends so an expression that merely contains an attribute
# access (`a.b + 1`, `a.b[0]`, `a.b if x else y`) is not read as an alias.
_BOUND_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _without_trailing_comment(value: str) -> str:
    """Strip a trailing ``# ...`` so ``x = a.b  # noqa`` still reads as ``a.b``.

    Splitting on the first ``#`` is safe: the one caller hands the result to a pattern that refuses
    anything but a bare dotted name.
    """
    return value.split("#", 1)[0].strip()


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows naming standards"""
    checks = []
    path = Path(module_path)

    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "naming", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .sentry/bypass.json"}],
            "score": 100,
            "standard": "NAMING",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "NAMING",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "NAMING",
        }

    checks.append(_waive_file_level(check_file_naming(module_path, path), module_path, bypass_rules))

    function_naming_check = check_function_naming(content, module_path, bypass_rules)
    if function_naming_check:
        checks.append(function_naming_check)

    constant_naming_check = check_constant_naming(content, module_path, bypass_rules)
    if constant_naming_check:
        checks.append(constant_naming_check)

    class_naming_check = check_class_naming(content, module_path, bypass_rules)
    if class_naming_check:
        checks.append(class_naming_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "naming"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "NAMING"}


def check_file_naming(module_path: str, path: Path) -> Dict:
    """Check file naming conventions"""
    filename = path.stem  # filename without extension

    # Python-reserved package marker — cannot be renamed
    if path.name == "__init__.py":
        return {"name": "File naming", "passed": True, "message": "__init__.py (Python-reserved package marker)"}

    if filename == "json_handler" and "/handlers/json/" in module_path:
        return {
            "name": "File naming",
            "passed": True,
            "message": f"{filename}.py (documented exception - standardized handler)",
        }

    if not re.match(r"^[a-z][a-z0-9_]*$", filename):
        return {
            "name": "File naming",
            "passed": False,
            "message": f"{filename}.py uses invalid characters (use snake_case: lowercase + underscores)",
        }

    if len(path.parts) > 1:
        parent_dir = path.parts[-2]

        if filename.startswith(f"{parent_dir}_"):
            suggested = filename.replace(f"{parent_dir}_", "")
            return {
                "name": "File naming",
                "passed": False,
                "message": f"{filename}.py has redundant prefix (in {parent_dir}/ dir, use {suggested}.py)",
            }

    standard_verbs = [
        "create",
        "ops",
        "load",
        "save",
        "initialize",
        "formatters",
        "decorators",
        "logger",
        "prompts",
        "content",
        "check",
        "handler",
    ]
    uses_standard_verb = any(verb in filename for verb in standard_verbs)

    if uses_standard_verb:
        return {"name": "File naming", "passed": True, "message": f"{filename}.py (snake_case, uses standard verb)"}
    else:
        return {
            "name": "File naming",
            "passed": True,
            "message": f"{filename}.py (snake_case, custom name - consider standard verbs)",
        }


#: unittest's hooks, spelled by the framework: a TestCase that renames them never runs them.
_UNITTEST_HOOKS = frozenset(
    {"setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule", "tearDownModule", "asyncSetUp", "asyncTearDown"}
)


def _protocol_name(func_name: str) -> bool:
    """Whether an inherited protocol, not the author, chose this name (sentry, fleet green leg 9).

    ``ast.NodeVisitor`` dispatches on ``visit_`` plus the node's class name, so only a real ``ast`` node
    class counts after the prefix; unittest's hooks are a fixed list.
    """
    if func_name in _UNITTEST_HOOKS:
        return True
    node = getattr(ast, func_name[len("visit_") :], None) if func_name.startswith("visit_") else None
    return isinstance(node, type) and issubclass(node, ast.AST)


def check_function_naming(content: str, module_path: str = "", bypass_rules: list | None = None) -> Optional[Dict]:
    """Check function naming conventions; each bad name is a site at its def line."""
    function_pattern = r"^\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
    matches = list(re.finditer(function_pattern, content, re.MULTILINE))
    functions = [match.group(1) for match in matches]

    if not functions:
        return None  # No functions to check

    bad_functions = []
    for match in matches:
        func_name = match.group(1)
        if func_name.startswith("__") and func_name.endswith("__"):
            continue
        if _protocol_name(func_name):
            continue

        if not re.match(r"^[a-z_][a-z0-9_]*$", func_name):
            bad_functions.append((content.count("\n", 0, match.start(1)) + 1, func_name))

    failing = _named_sites("Function naming", "Non-snake_case functions", bad_functions, module_path, bypass_rules)
    if failing:
        return failing

    return {
        "name": "Function naming",
        "passed": True,
        "message": f"{len(functions)} functions checked - all snake_case",
    }


#: MODULE GLOBALS PYTEST READS BY NAME: an UPPER_CASE rename silently stops them working. Exempted by
#: name, not by file: this checker is handed content, never a path.
PYTEST_CONTRACT_GLOBALS = frozenset(
    {
        "collect_ignore",
        "collect_ignore_glob",
        "pytest_plugins",
        "pytestmark",
    }
)


def check_constant_naming(content: str, module_path: str = "", bypass_rules: list | None = None) -> Optional[Dict]:
    """Check constant naming conventions; each bad name is a site at its assignment line."""
    imported_names = set()
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("from ") and " import " in stripped:
            import_part = stripped.split(" import ", 1)[1]
            for item in import_part.split(","):
                item = item.strip()
                if " as " in item:
                    imported_names.add(item.split(" as ")[1].strip())
                else:
                    imported_names.add(item.strip())

    # Column 0 only: local variables are always indented.
    constants = []
    bad_constants = []
    try:
        kinds = classify(content)
        # A string literal's continuation lines are its text, never a column-0 assignment.
        skip = kinds.prose | kinds.string_bodies
    except UnparseableSource as exc:
        logger.info("naming: unparseable, only # lines are prose: %s", exc)
        skip = hash_lines(content)

    for lineno, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if lineno in skip:
            continue

        if line and (line[0] == " " or line[0] == "\t"):
            continue

        if "=" not in stripped or stripped.startswith("#"):
            continue

        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$", stripped)
        if not match:
            continue

        const_name = match.group(1)
        assigned_value = match.group(2)

        if const_name.startswith("__") and const_name.endswith("__"):
            continue

        if const_name in PYTEST_CONTRACT_GLOBALS:
            continue

        if const_name in imported_names:
            continue

        if "(" in assigned_value:
            continue

        # A bound alias (`save_json = _h.save_json`) names another object's member, not a constant; PEP 8 spells
        # it lowercase. Given up: convicting `max_entries = settings.LIMIT`, which reads identically.
        if _BOUND_ALIAS_RE.match(_without_trailing_comment(assigned_value)):
            continue

        if assigned_value.strip() in imported_names:
            continue

        constants.append(const_name)

        if not const_name.isupper():
            bad_constants.append((lineno, const_name))

    if not constants:
        return None  # No constants found

    failing = _named_sites("Constant naming", "Non-UPPER_CASE constants", bad_constants, module_path, bypass_rules)
    if failing:
        return failing

    return {
        "name": "Constant naming",
        "passed": True,
        "message": f"{len(constants)} constants checked - all UPPER_CASE",
    }


def check_class_naming(content: str, module_path: str = "", bypass_rules: list | None = None) -> Optional[Dict]:
    """Check class naming conventions; each bad name is a site at its class line."""
    class_pattern = r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(:]"
    matches = list(re.finditer(class_pattern, content, re.MULTILINE))

    if not matches:
        return None  # No classes to check

    bad_classes = []
    for match in matches:
        # Check for PascalCase (PEP 8 sanctions a single leading underscore for internal classes)
        if not re.match(r"^_?[A-Z][a-zA-Z0-9]*$", match.group(1)):
            bad_classes.append((content.count("\n", 0, match.start(1)) + 1, match.group(1)))

    failing = _named_sites("Class naming", "Non-PascalCase classes", bad_classes, module_path, bypass_rules)
    if failing:
        return failing

    return {"name": "Class naming", "passed": True, "message": f"{len(matches)} classes checked - all PascalCase"}


def _named_sites(check: str, label: str, sites: list, module_path: str, bypass_rules: list | None) -> Optional[Dict]:
    """The failing verdict naming every site no row waives, a pass when rows waive them all, else None.

    The name itself is the site: a row waives it by ``functions: [name]`` or by its line.
    """
    if not sites:
        return None
    open_sites = [
        (line, name)
        for line, name in sites
        if not is_bypassed(module_path, "naming", line=line, bypass_rules=bypass_rules, name=name)
    ]
    if not open_sites:
        return {"name": check, "passed": True, "message": f"{label}: all {len(sites)} waived by scoped bypass rows"}
    return {
        "name": check,
        "passed": False,
        "message": f"{label}: " + ", ".join(f"{name} (line {line})" for line, name in open_sites),
    }


def _waive_file_level(check: Dict, module_path: str, bypass_rules: list | None) -> Dict:
    """A failing file-level check passed by a row naming FILE_SCOPE under functions."""
    if check["passed"] or not is_bypassed(module_path, "naming", bypass_rules=bypass_rules, name=FILE_SCOPE):
        return check
    return {**check, "passed": True, "message": f"Waived by a {FILE_SCOPE} bypass row: {check['message']}"}
