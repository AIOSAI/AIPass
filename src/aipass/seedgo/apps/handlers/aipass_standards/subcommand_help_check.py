# =================== AIPass ====================
# Name: subcommand_help_check.py
# Description: Subcommand Help Standards Checker Handler
# Version: 2.0.0
# Created: 2026-07-10
# Modified: 2026-09-20
# =============================================

"""Subcommand Help Standards Checker Handler.

Validates that branch entry points handle <cmd> --help by showing
subcommand-specific help — never executing the command, never silently
falling back to top-level help.

The standard names three ways to get this wrong; until 2026-09-20 this
checker could only see two of them.

RULE 1 — THE GUARD (entry points).
  Every entry point that routes subcommands must intercept --help in the
  remaining args (after command extraction) BEFORE dispatching to handlers.
  Passes on either an explicit subcommand --help guard on remaining args, or
  argparse ``parse_known_args`` (which absorbs --help from any position).

RULE 2 — REACHABLE PER-VERB HELP (any production module).
  The standard's third contract line is "shows top-level help (unhelpful)",
  and nothing enforced it. Drone shipped for months with nineteen per-verb
  git paragraphs behind ``get_help(command)`` that no caller could reach:
  ``print_help()`` was called with no argument, so every ``drone @git VERB
  --help`` returned the top-level index. Rule 1 scored it 100 — correctly,
  by its own terms. The violation was not at the entry point and not at the
  dispatch site; it was in the chain between them (drone fc032265).

  Measured before building (2026-09-20, fleet at HEAD):
    129 help dispatch sites sit in a router that knows the verb, and 125 of
    them hand their printer nothing. That is the NORM, not the violation —
    those printers have no per-verb content to reach, so the top-level page
    is the only right answer and the dispatch site cannot tell the two apart.
    Pre-fix drone was byte-identical in shape to all 125.

  So this rule reads the PROVIDER, not the dispatch site: a help-text
  function that selects per-verb content by testing its own parameter
  against two or more string literals, where every in-module call to it
  omits that argument. Then the per-verb branches are dead by construction.

  Population is small and honestly so: of 213 help-named functions fleet-wide,
  140 take no parameter at all, and exactly 1 carries per-verb content. The
  rule convicts pre-fix drone, clears the cure, and clears all 125 innocent
  sites. One specimen is the whole population, so it is CALIBRATED, not
  validated — it will be exercised the day a second per-verb provider lands.

SCOPE: branch_level. Rule 1 still reports on the entry point only; rule 2
walks every production module, because that is where the species lives.
``check_module`` stays for the checklist hook, which runs per file.
"""

import ast
import re
from pathlib import Path
from typing import Dict, TypeGuard

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"
APPLIES_TO = "production"

_TOPLEVEL_ARG_NAMES = frozenset({"args", "argv"})

_HELP_STRINGS = frozenset({"--help", "-h"})


_ENTRY_NAMES = {"main", "handle_command"}

# "help" has to be a whole word. Matching the substring pulls in every
# ``_local_helpers``/``_helper_kind`` in the tree: an early cut of rule 2 had
# a population of 56 that way, 49 of them not help machinery at all, and its
# precision was an accident of what those helpers happened to be called with.
_NAME_TOKENS = re.compile(r"[^a-z0-9]+")

# Two literals, not one. A provider that tests its parameter once is usually
# guarding ``is None`` or a single alias; per-verb CONTENT means a menu.
_MIN_VERB_LITERALS = 2

# Rule 2 walks the branch itself, so it owns its own corpus.
_SOURCE_DIR = "apps"


def _called_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return names of functions called directly from func_node's body."""
    names: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _find_entry_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return entry functions and their direct delegates from the module top level."""
    all_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_funcs[node.name] = node

    targets: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for name in _ENTRY_NAMES:
        if name not in all_funcs:
            continue
        func = all_funcs[name]
        targets.append(func)
        for called in _called_names(func):
            if called in all_funcs and called.startswith("_") and called not in _ENTRY_NAMES:
                targets.append(all_funcs[called])
    return targets


def _has_argparse_known_args(func_node: ast.AST) -> bool:
    """Return True if the function uses argparse parse_known_args."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "parse_known_args":
            return True
    return False


def _compare_has_help_string(node: ast.Compare) -> bool:
    """Return True if a Compare node involves a --help string constant."""
    for part in [node.left, *node.comparators]:
        if isinstance(part, ast.Constant) and part.value in _HELP_STRINGS:
            return True
        if isinstance(part, (ast.List, ast.Tuple, ast.Set)):
            for elt in part.elts:
                if isinstance(elt, ast.Constant) and elt.value in _HELP_STRINGS:
                    return True
    return False


def _is_subscript_on_name(node: ast.expr, names: frozenset[str]) -> bool:
    """Return True if node is name[N] where name is in the given set."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id in names
    return False


def _is_toplevel_help_check(node: ast.Compare) -> bool:
    """Return True if this is a top-level args[0] --help check."""
    return _is_subscript_on_name(node.left, _TOPLEVEL_ARG_NAMES)


def _is_help_in_nonargs_var(node: ast.Compare) -> bool:
    """Check for '"--help" in some_var' where some_var is not args/argv."""
    if not isinstance(node.left, ast.Constant) or node.left.value not in _HELP_STRINGS:
        return False
    if not any(isinstance(op, ast.In) for op in node.ops):
        return False
    return any(isinstance(c, ast.Name) and c.id not in _TOPLEVEL_ARG_NAMES for c in node.comparators)


def _is_nonargs_subscript_help(node: ast.Compare) -> bool:
    """Check for 'remaining[0] in ["--help", ...]' where remaining != args."""
    left = node.left
    if not isinstance(left, ast.Subscript) or not isinstance(left.value, ast.Name):
        return False
    return left.value.id not in _TOPLEVEL_ARG_NAMES


def _has_subcommand_help_guard(func_node: ast.AST, func_name: str = "") -> bool:
    """Return True if the function has a subcommand-level --help check.

    Detects patterns like:
      remaining_args[0] in ["--help", "-h"]
      "--help" in remaining_args
      rest[0] == "--help"
    where the variable is NOT the raw args/argv.

    In handle_command(), args IS the subcommand args (not full argv),
    so args[0] checks there count as subcommand guards.
    """
    args_are_subcommand = func_name == "handle_command"
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Compare):
            continue
        if not _compare_has_help_string(node):
            continue
        if _is_toplevel_help_check(node):
            if args_are_subcommand:
                return True
            continue
        if _is_subscript_on_name(node.left, _TOPLEVEL_ARG_NAMES):
            if args_are_subcommand:
                return True
            continue
        if _is_help_in_nonargs_var(node):
            return True
        if _is_nonargs_subscript_help(node):
            return True
        if isinstance(node.left, ast.Name) and node.left.id not in _TOPLEVEL_ARG_NAMES:
            return True
    return False


# =============================================================================
# RULE 2 — per-verb help that no caller can reach
# =============================================================================


def _is_help_name(name: str) -> bool:
    """Whether ``name`` carries "help" as a whole token.

    ``helper`` and ``helpers`` are a different word and must not match, or the
    rule starts reading every private test helper in the branch.
    """
    return "help" in [t for t in _NAME_TOKENS.split(name.lower()) if t]


def _produces_help_text(func_node: ast.AST) -> bool:
    """Whether this function hands back or prints TEXT.

    A provider returns a page; a predicate (``_is_help_flag``) returns a bool.
    Only the first kind can have per-verb content to lose.
    """
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return):
            value = node.value
            if isinstance(value, ast.JoinedStr):
                return True
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "print":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "print":
                return True
    return False


def _verb_literals(func_node: ast.AST, param: str) -> set[str]:
    """The verbs this function selects content with, read off its own body.

    Name-independent on purpose: a branch is free to call the parameter
    ``command``, ``verb`` or ``topic``, and pinning a vocabulary here would
    make the rule learn drone's word rather than the shape.
    """
    verbs: set[str] = set()
    for node in ast.walk(func_node):
        if _tests_param(node, param):
            verbs |= _compared_strings(node)
        elif _indexes_by_param(node, param):
            verbs |= _subscript_keys(func_node, node)
    return verbs


def _tests_param(node: ast.AST, param: str) -> TypeGuard[ast.Compare]:
    """Whether this node compares ``param`` against something.

    A TypeGuard, not a bool: the narrowing has to reach the caller, or the
    reader (and pyright) cannot see why the next line may treat it as one.
    """
    return isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == param


def _indexes_by_param(node: ast.AST, param: str) -> TypeGuard[ast.Subscript]:
    """Whether this node looks a value up BY ``param``."""
    return isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Name) and node.slice.id == param


def _string_constants(nodes) -> set[str]:
    """The string constants among these nodes."""
    return {n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _compared_strings(node: ast.Compare) -> set[str]:
    """Every string this comparison puts the parameter against."""
    verbs = _string_constants(node.comparators)
    for comparator in node.comparators:
        if isinstance(comparator, (ast.List, ast.Tuple, ast.Set)):
            verbs |= _string_constants(comparator.elts)
    return verbs


def _subscript_keys(func_node: ast.AST, node: ast.Subscript) -> set[str]:
    """The menu behind ``pages[command]``, literal or one name-hop away.

    Counting the subscript as a single verb hid every dict-keyed provider
    behind the two-literal floor.
    """
    if isinstance(node.value, ast.Dict):
        return _dict_string_keys(node.value)
    if isinstance(node.value, ast.Name):
        return _bound_dict_keys(func_node, node.value.id)
    return set()


def _dict_string_keys(node: ast.Dict) -> set[str]:
    """The string keys of a dict literal."""
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _bound_dict_keys(scope: ast.AST, name: str) -> set[str]:
    """String keys of the dict literal ``name`` is assigned in this scope."""
    keys: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                keys |= _dict_string_keys(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Dict):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                keys |= _dict_string_keys(node.value)
    return keys


def _per_verb_providers(tree: ast.Module) -> dict[str, tuple[str, int, int]]:
    """Help providers carrying per-verb content: name -> (param, verbs, lineno)."""
    providers: dict[str, tuple[str, int, int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_help_name(node.name) or not _produces_help_text(node):
            continue
        params = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
        params += [a.arg for a in node.args.kwonlyargs]
        if not params:
            continue
        verbs = _verb_literals(node, params[0])
        if len(verbs) >= _MIN_VERB_LITERALS:
            providers[node.name] = (params[0], len(verbs), node.lineno)
    return providers


def _calls_to(tree: ast.Module, name: str) -> list[ast.Call]:
    """Every call to ``name`` in this module, plain or attribute form."""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id == name) or (isinstance(func, ast.Attribute) and func.attr == name):
            calls.append(node)
    return calls


def find_unreachable_verb_help(tree: ast.Module) -> list[str]:
    """Per-verb help providers whose every in-module call omits the verb.

    A provider with NO call site here is left alone: its callers live in
    another module and this lane cannot see them, so there is nothing to
    measure. Silence on what cannot be read beats a guess either way.
    """
    findings: list[str] = []
    for name, (param, verb_count, lineno) in _per_verb_providers(tree).items():
        calls = _calls_to(tree, name)
        if not calls:
            continue
        if any(call.args or call.keywords for call in calls):
            continue
        findings.append(
            f"{name}() at line {lineno} answers {verb_count} verbs through '{param}', "
            f"but all {len(calls)} call(s) omit it — every per-verb request gets the top-level page"
        )
    return findings


def _rule_two_check(tree: ast.Module, label: str) -> Dict:
    """Rule 2 as a checks[] entry."""
    findings = find_unreachable_verb_help(tree)
    if findings:
        return {"name": "Per-verb help reachable", "passed": False, "message": f"{label}: {findings[0]}"}
    return {"name": "Per-verb help reachable", "passed": True, "message": "No per-verb help is stranded"}


def _parse(path: Path) -> ast.Module | None:
    """Parse a file, or None when it cannot be read or parsed."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as e:
        logger.info("subcommand_help: cannot parse %s: %s", path, e)
        return None


def _is_production(file_path: str) -> bool:
    """APPLIES_TO = "production", read through the shared gate.

    Both lanes consult applicability.py so scope can never be decided twice
    and differently — that disagreement is the reason the module exists.
    """
    return not applicability.is_test_path(file_path) and not applicability.is_retired_path(file_path)


def _rule_one_check(tree: ast.Module) -> Dict:
    """Rule 1 — the subcommand --help guard, unchanged since 1.0.0."""
    entry_funcs = _find_entry_functions(tree)
    if not entry_funcs:
        return {
            "name": "Subcommand help",
            "passed": True,
            "message": "No main/handle_command entry function found (skipped)",
        }

    for func in entry_funcs:
        if _has_argparse_known_args(func):
            return {
                "name": "Subcommand help",
                "passed": True,
                "message": f"argparse parse_known_args in {func.name}() absorbs --help",
            }
        if _has_subcommand_help_guard(func, func.name):
            return {
                "name": "Subcommand help",
                "passed": True,
                "message": f"Subcommand --help guard found in {func.name}()",
            }

    func_names = ", ".join(f.name for f in entry_funcs)
    return {
        "name": "Subcommand help",
        "passed": False,
        "message": (
            f"No subcommand --help guard in {func_names}() — "
            "<cmd> --help will execute the command or fall to top-level help"
        ),
    }


def _result(checks: list[Dict]) -> Dict:
    """Assemble the standard result. Binary, as this standard has always been."""
    passed = all(c["passed"] for c in checks)
    return {
        "passed": passed,
        "checks": checks,
        "score": 100 if passed else 0,
        "standard": "SUBCOMMAND_HELP",
    }


def _bypassed_result() -> Dict:
    return {
        "passed": True,
        "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
        "score": 100,
        "standard": "SUBCOMMAND_HELP",
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one file. Entry points get both rules; any other module gets rule 2.

    This is the checklist lane's door (the PostToolUse hook runs per file).
    The audit lane calls ``check_branch`` instead — rule 2's corpus is the
    branch, not the entry point, because that is where the species lives.
    """
    path = Path(module_path)

    if is_bypassed(module_path, "subcommand_help", bypass_rules=bypass_rules):
        return _bypassed_result()

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "SUBCOMMAND_HELP",
        }

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "SUBCOMMAND_HELP",
        }

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        logger.info("Skipped %s: SyntaxError during parse", path)
        return {
            "passed": False,
            "checks": [{"name": "File parseable", "passed": False, "message": f"Syntax error: {e}"}],
            "score": 0,
            "standard": "SUBCOMMAND_HELP",
        }

    is_entry = path.parent.name == _SOURCE_DIR
    checks = [_rule_one_check(tree)] if is_entry else []
    checks.append(_rule_two_check(tree, path.name))
    if not is_entry:
        checks.insert(0, {"name": "Subcommand help", "passed": True, "message": "Not an entry point (skipped)"})

    result = _result(checks)
    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": result["score"], "standard": "subcommand_help"},
    )
    return result


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Rule 1 on the entry point, rule 2 on every production module.

    Rule 2 had to leave entry_point scope to exist at all: drone's stranded
    per-verb help lived in ``apps/modules/git_module.py``, a file the audit
    lane never handed this checker.
    """
    branch = Path(branch_path)
    if is_bypassed(str(branch), "subcommand_help", bypass_rules=bypass_rules):
        return _bypassed_result()

    entry_file = branch / _SOURCE_DIR / f"{branch.name}.py"
    checks: list[Dict] = []

    if entry_file.exists():
        tree = _parse(entry_file)
        checks.append(
            _rule_one_check(tree)
            if tree is not None
            else {"name": "Subcommand help", "passed": False, "message": f"Cannot parse {entry_file.name}"}
        )
    else:
        checks.append(
            {"name": "Subcommand help", "passed": True, "message": f"No entry point at apps/{branch.name}.py (skipped)"}
        )

    stranded: list[str] = []
    scanned = 0
    for source_file in sorted((branch / _SOURCE_DIR).rglob("*.py")):
        if not _is_production(str(source_file)):
            continue
        if is_bypassed(str(source_file), "subcommand_help", bypass_rules=bypass_rules):
            continue
        tree = _parse(source_file)
        if tree is None:
            continue
        scanned += 1
        stranded += [f"{source_file.name}: {f}" for f in find_unreachable_verb_help(tree)]

    if stranded:
        checks.append(
            {
                "name": "Per-verb help reachable",
                "passed": False,
                "message": f"{len(stranded)} stranded across {scanned} module(s) — {stranded[0]}",
            }
        )
    else:
        checks.append(
            {
                "name": "Per-verb help reachable",
                "passed": True,
                "message": f"No per-verb help is stranded ({scanned} module(s) read)",
            }
        )

    result = _result(checks)
    json_handler.log_operation(
        "check_completed",
        {"branch": str(branch_path), "score": result["score"], "standard": "subcommand_help"},
    )
    return result
