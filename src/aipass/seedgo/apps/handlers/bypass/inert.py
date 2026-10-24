# =================== AIPass ====================
# Name: inert.py
# Description: Detects bypass rules that can never match, for the audit info channel and the checklist
# Version: 1.2.1
# Created: 2026-08-09
# Modified: 2026-10-24
# =============================================

"""Detects bypass rules whose declared scope can never be evaluated.

A ``lines``/``functions`` rule only matches when the checker passes ``line=``/``name=``;
which ones do is read from the checker sources, never hardcoded.
"""

import ast
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

HANDLERS_ROOT = module_file(__file__).parents[1]
PACK_ROOT = HANDLERS_ROOT / "aipass_standards"


# Most call sites pass the scope arguments positionally; reading keywords only
# reports live standards as line-blind.
_SHARED_SIGNATURE = ("file_path", "standard", "line", "bypass_rules", "name")
_SHARED_IMPORT = "aipass.seedgo.apps.handlers.bypass.utils"
_SHARED_NAMES = ("is_bypassed", "matching_rule")
_SCOPE_ARG = {"line": "lines", "name": "functions"}

# The advisory is computed in the audit lane only (its corpus, prose-reporting
# branch_level standards unseen), so it carries its own caveat in its output.
ADVISORY_CAVEAT = (
    "UNVERIFIED — this bypass advisory is wrong in BOTH directions, so it cannot be pruned from on its "
    "own. It calls LIVE rules dead: it is measured in the audit lane, which walks apps/, shared/ and only "
    "the test_*.py and conftest.py files under tests/, so a rule on any other tests/ file reads as dead "
    "here while it still suppresses findings in the checklist lane the edit hook runs; branch_level standards report in prose instead of violation records, so their live "
    "rules read as dead too. And it is blind the other way: it never mentions dead rules outside the "
    "shapes it can see. Measured on @skills, 6 of the 7 checkable 'dead' rules were live; @aipass was "
    "told 41 and a control run proved 59.",
    "Do not delete a rule because it is named below. Measure first: re-run the audit with the branch's "
    "bypass rules disabled — that control run is the only evidence that a rule suppresses nothing — and "
    "delete only what it proves dead. Treat the lines below as a place to start looking, not as findings.",
)

# Info lines are stored and re-rendered one at a time, so each carries the doubt.
_UNVERIFIED = "unverified: "
UNREADABLE = "bypass.json unreadable, so none of its rules was judged: "


def _argument(call: ast.Call, param: str) -> ast.expr | None:
    """The expression passed for one parameter, by keyword or by position."""
    for kw in call.keywords:
        if kw.arg == param:
            return kw.value
    index = _SHARED_SIGNATURE.index(param)
    return call.args[index] if len(call.args) > index else None


def _is_supplied(node: ast.expr | None) -> bool:
    """A literal None is the same as passing nothing; anything else may be a real value."""
    if node is None:
        return False
    return not (isinstance(node, ast.Constant) and node.value is None)


def _binds_shared_matcher(tree: ast.AST) -> bool:
    """Whether the matcher names in this module mean the shared utility, not a local same-named function."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _SHARED_NAMES:
            return False
        if isinstance(node, ast.ImportFrom) and node.module == _SHARED_IMPORT:
            if any(alias.name in _SHARED_NAMES and alias.asname is None for alias in node.names):
                return True
    return False


def _module_strings(tree: ast.Module) -> Dict[str, str]:
    """Top-level ``NAME = "text"`` bindings, so ``STANDARD_KEY`` reads as its value."""
    strings: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value, targets = node.value, node.targets
        elif isinstance(node, ast.AnnAssign):
            value, targets = node.value, [node.target]
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                strings[target.id] = value.value
    return strings


def _standard_named(node: ast.expr | None, strings: Dict[str, str]) -> str | None:
    """The standard a call passes: a string literal, or a module constant holding one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return strings.get(node.id)
    return None


@lru_cache(maxsize=1)
def scope_support() -> Dict[str, Set[str]]:
    """Map each standard to the scope kinds its checker can actually evaluate.

    ANY call site supplying a scope counts: a file-wide gate plus per-line re-checks still narrows.
    """
    support: Dict[str, Set[str]] = {}
    for source in sorted(HANDLERS_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as e:
            logger.info("Skipping %s while mapping bypass scope support: %s", source, e)
            continue
        if not _binds_shared_matcher(tree):
            continue
        strings = _module_strings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or getattr(node.func, "id", None) not in _SHARED_NAMES:
                continue
            standard = _standard_named(_argument(node, "standard"), strings)
            if standard is None:
                continue
            kinds = support.setdefault(standard, set())
            for param, scope in _SCOPE_ARG.items():
                if _is_supplied(_argument(node, param)):
                    kinds.add(scope)
    return support


def inert_scopes(rule: dict) -> Tuple[str, ...]:
    """The scope keys on this rule that its standard's checker can never evaluate."""
    declared = tuple(key for key in ("lines", "functions") if rule.get(key))
    if not declared:
        return ()

    standard = rule.get("standard")
    support = scope_support()
    if standard:
        # An unknown standard is a separate defect; this channel reports scope only.
        if standard not in support:
            return ()
        evaluable = support[standard]
    else:
        evaluable = set().union(*support.values()) if support else set()

    return tuple(key for key in declared if key not in evaluable)


def inert_notes(file_path: str, standard: str, bypass_rules: list | None) -> list[str]:
    """One line per rule naming this file and standard whose scope can never match.

    File and standard match as :func:`bypass.utils.matching_rule` does; a note, never a verdict change.
    """
    file_posix = Path(file_path).as_posix()
    notes = []
    for rule in bypass_rules or []:
        if not isinstance(rule, dict) or rule.get("standard") != standard:
            continue
        rule_file = rule.get("file") or ""
        if not rule_file or Path(rule_file).as_posix() not in file_posix:
            continue
        for key in inert_scopes(rule):
            passed = "line" if key == "lines" else "name"
            notes.append(
                f"bypass rule '{key}' {rule[key]} closes nothing: this checker passes no {passed}, "
                f"so only a file-wide rule bypasses it"
            )
    return notes


@lru_cache(maxsize=1)
def standard_constants() -> Dict[str, Dict[str, str]]:
    """Each standard's module-level string constants, read from the checker sources.

    By AST, not import: branch_audit imports this module, so importing it back is a cycle.
    """
    declared: Dict[str, Dict[str, str]] = {}
    for source in sorted(PACK_ROOT.glob("*_check.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as e:
            logger.info("Skipping %s while reading checker constants: %s", source, e)
            continue
        constants = declared.setdefault(source.stem.removesuffix("_check"), {})
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("APPLIES_TO", "AUDIT_SCOPE"):
                    constants[target.id] = node.value.value
    return declared


def out_of_scope_reason(rule: dict) -> str | None:
    """Why this rule can no longer match, when its file is outside its standard's scope.

    Silent on wildcard files and branch_level checkers, which walk the tree themselves.
    """
    path = rule.get("file")
    if not path or any(ch in path for ch in "*?["):
        return None
    if applicability.is_retired_path(path):
        return "retired code is not checked by either lane, so this rule suppresses nothing"

    standard = rule.get("standard")
    if not standard:
        return None
    constants = standard_constants().get(standard, {})
    if constants.get("AUDIT_SCOPE") == "branch_level":
        return None
    declared = constants.get("APPLIES_TO", applicability.DEFAULT_APPLIES_TO)
    if declared == applicability.EVERYWHERE:
        return None
    if applicability.is_test_path(path) == (declared == applicability.TESTS):
        return None
    kind = "a test file" if applicability.is_test_path(path) else "production code"
    return f"{standard} applies to {declared} only and this is {kind}, so this rule suppresses nothing"


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines about a branch's bypass rules, led by their caveat.

    The caveat leads whenever anything is reported; an unreadable bypass.json answers one line, never [].
    """
    bypass_file = Path(branch_path) / ".seedgo" / "bypass.json"
    if not bypass_file.exists():
        return []

    try:
        rules = json.loads(bypass_file.read_text(encoding="utf-8")).get("bypass", [])
    except (OSError, ValueError) as e:
        logger.info("Cannot read %s for inert-rule info: %s", bypass_file, e)
        return [f"{UNREADABLE}{bypass_file} ({e})"]

    lines = []
    out_of_scope: Dict[str, list[str]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        standard = rule.get("standard") or "all standards"

        if out_of_scope_reason(rule):
            out_of_scope.setdefault(standard, []).append(rule.get("file", "?"))
            continue

        inert = inert_scopes(rule)
        if not inert:
            continue
        scopes = " and ".join(f"'{key}'" for key in inert)
        verb = "never match" if len(inert) > 1 else "never matches"
        # Parentheses, not brackets: audit_display renders through Rich, which eats "[handlers]".
        lines.append(
            f"{_UNVERIFIED}{rule.get('file', '?')} ({standard}): {scopes} {verb} — that checker gates "
            f"file-wide and passes no line/name, so this rule looks inert. Widen it to file-wide, or "
            f"confirm with a control run before dropping it."
        )

    # Named, not counted, and uncapped: a branch cannot act on a bare count.
    if out_of_scope:
        total = sum(len(files) for files in out_of_scope.values())
        lines.append(
            f"{_UNVERIFIED}{total} bypass rules may no longer suppress anything — those standards no "
            f"longer apply to that kind of file in the audit lane. This is the direction that has "
            f"misfired on live rules; confirm with a control run before deleting any of them:"
        )
        for standard, files in sorted(out_of_scope.items(), key=lambda item: (-len(item[1]), item[0])):
            lines.append(f"  {standard} ({len(files)}): {', '.join(sorted(files))}")

    if not lines:
        return []

    json_handler.log_operation(
        "inert_bypass_rules_found",
        {"branch": str(branch_path), "count": len(lines), "standard": "bypass"},
    )
    return [*ADVISORY_CAVEAT, *lines]
