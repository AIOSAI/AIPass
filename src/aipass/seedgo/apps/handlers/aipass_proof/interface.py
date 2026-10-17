# =================== AIPass ====================
# Name: interface.py
# Description: Verify checker interface (AUDIT_SCOPE + function signature)
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""Interface Proof -- Verify each checker declares AUDIT_SCOPE and correct function signature.

Every *_check.py in a standards pack must:
  1. Declare AUDIT_SCOPE at module level (one of: all_files, entry_point, branch_level)
  2. Implement the correct entry function (check_module or check_branch)
  3. Have the correct first parameter (module_path or branch_path) plus bypass_rules
"""

from __future__ import annotations

import ast
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS

VALID_SCOPES = {"all_files", "entry_point", "branch_level"}

_SKIP_DIRS = SOURCE_SKIP_DIRS


def _extract_audit_scope(tree: ast.Module) -> str | None:
    """Return the string value of AUDIT_SCOPE if defined at module level."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "AUDIT_SCOPE":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    return node.value.value
    return None


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    """Return the FunctionDef node for *name* if it exists at module level."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _check_params(func: ast.FunctionDef, expected_first: str) -> tuple[bool, str]:
    """Verify the function has (expected_first, bypass_rules=None)."""
    args = func.args
    positional = [a.arg for a in args.posonlyargs] + [a.arg for a in args.args]

    if not positional:
        return False, "no parameters"

    if positional[0] != expected_first:
        return False, f"first param is '{positional[0]}', expected '{expected_first}'"

    if len(positional) < 2 or positional[1] != "bypass_rules":
        kw_names = [a.arg for a in args.kwonlyargs]
        if "bypass_rules" not in kw_names:
            return False, "missing 'bypass_rules' parameter"

    return True, "ok"


def _should_skip(path: Path) -> bool:
    """Return True if the file should be excluded from scanning."""
    if path.name == "__init__.py":
        return True
    if path.name.startswith("_") and not path.name.startswith("__"):
        return True
    for part in path.parts:
        if part in _SKIP_DIRS:
            return True
    return False


def scan(pack_dir: Path) -> dict:
    """Scan all *_check.py files in *pack_dir* and verify interface compliance."""
    results: list[dict] = []
    issues: list[str] = []

    if not pack_dir.is_dir():
        msg = f"Pack directory not found: {pack_dir}"
        logger.warning(msg)
        return {
            "passed": False,
            "total": 0,
            "pass_count": 0,
            "fail_count": 0,
            "results": results,
            "issues": [msg],
            "summary": msg,
        }

    check_files = sorted(pack_dir.glob("*_check.py"))

    for check_file in check_files:
        if _should_skip(check_file):
            continue

        name = check_file.stem  # e.g. "cli_check"
        standard_name = name.removesuffix("_check")  # e.g. "cli"

        entry: dict = {
            "file": check_file.name,
            "standard": standard_name,
            "audit_scope": None,
            "scope_valid": False,
            "has_function": False,
            "expected_function": None,
            "params_ok": False,
            "params_detail": "",
            "compliant": False,
            "issues": [],
        }

        try:
            source = check_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(check_file))
        except SyntaxError as exc:
            logger.info("Skipped %s: SyntaxError during parse", check_file.name)
            err = f"{check_file.name}: SyntaxError: {exc.msg} (line {exc.lineno})"
            entry["issues"].append(err)
            issues.append(err)
            results.append(entry)
            continue

        scope = _extract_audit_scope(tree)
        entry["audit_scope"] = scope

        if scope is None:
            err = f"{check_file.name}: AUDIT_SCOPE not defined"
            entry["issues"].append(err)
            issues.append(err)
        elif scope not in VALID_SCOPES:
            err = f"{check_file.name}: AUDIT_SCOPE='{scope}' not in {VALID_SCOPES}"
            entry["issues"].append(err)
            issues.append(err)
        else:
            entry["scope_valid"] = True

        if scope in ("all_files", "entry_point", None):
            expected_func = "check_module"
            expected_first_param = "module_path"
        else:  # branch_level
            expected_func = "check_branch"
            expected_first_param = "branch_path"

        entry["expected_function"] = expected_func

        func_node = _find_function(tree, expected_func)

        if func_node is None:
            err = f"{check_file.name}: missing {expected_func}()"
            entry["has_function"] = False
            entry["issues"].append(err)
            issues.append(err)
        else:
            entry["has_function"] = True

            ok, detail = _check_params(func_node, expected_first_param)
            entry["params_ok"] = ok
            entry["params_detail"] = detail
            if not ok:
                err = f"{check_file.name}: {expected_func}() params: {detail}"
                entry["issues"].append(err)
                issues.append(err)

        entry["compliant"] = entry["scope_valid"] and entry["has_function"] and entry["params_ok"]
        results.append(entry)

    pass_count = sum(1 for r in results if r["compliant"])
    fail_count = len(results) - pass_count
    total = len(results)
    passed = fail_count == 0 and total > 0

    if passed:
        summary = f"All {total} checkers comply with the interface."
    elif total == 0:
        summary = "No *_check.py files found in pack directory."
    else:
        summary = f"{fail_count}/{total} checkers have interface issues."

    logger.info(f"interface proof: {summary}")

    json_handler.log_operation("proof_scan", {"proof": "interface", "passed": passed})

    return {
        "passed": passed,
        "total": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "results": results,
        "issues": issues,
        "summary": summary,
    }
