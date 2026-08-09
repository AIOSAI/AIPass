# =================== AIPass ====================
# Name: inert.py
# Description: Detects bypass rules that can never match, for the audit info channel
# Version: 1.0.0
# Created: 2026-08-09
# Modified: 2026-08-09
# =============================================

"""Detects bypass rules whose declared scope can never be evaluated.

``is_bypassed`` only honours a rule's ``lines``/``functions`` scope when the
calling checker actually supplies ``line=``/``name=``. Most checkers gate the
whole standard once at the top of ``check_module`` and supply neither — so a
``lines`` rule written against one of those standards is INERT: it narrows
nothing because it never matches at all.

Before FPLAN-0382 such a rule fell through to a match and silently suppressed
the entire file. Now it correctly does nothing — which is just as silent from
the author's chair. This module makes it speak, on the audit's non-scored info
channel, by reading which parameters each standard's checker actually passes
straight out of the checker sources. Nothing here is hardcoded, so a checker
that starts threading ``line=`` stops being reported the moment it does.
"""

import ast
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Every checker in the pack lives under this package's parent.
HANDLERS_ROOT = Path(__file__).resolve().parents[1]


def _standard_of(call: ast.Call) -> str | None:
    """The standard a single is_bypassed() call gates, if it is a plain literal."""
    node: ast.expr | None = None
    for kw in call.keywords:
        if kw.arg == "standard":
            node = kw.value
    if node is None and len(call.args) >= 2:
        node = call.args[1]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


@lru_cache(maxsize=1)
def scope_support() -> Dict[str, Set[str]]:
    """Map each standard to the scope kinds its checker can actually evaluate.

    Returns e.g. ``{"cli": {"lines"}, "encapsulation": {"lines"}, "handlers": set()}``
    — an empty set meaning that standard gates file-wide only, so no ``lines`` or
    ``functions`` rule written against it can ever match.

    Read from the checker sources by AST rather than from a maintained list: a
    list would drift the same way the bypass rules themselves did.
    """
    support: Dict[str, Set[str]] = {}
    for source in sorted(HANDLERS_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as e:
            logger.info("Skipping %s while mapping bypass scope support: %s", source, e)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called != "is_bypassed":
                continue
            standard = _standard_of(node)
            if standard is None:
                continue
            supplied = {kw.arg for kw in node.keywords}
            kinds = support.setdefault(standard, set())
            if "line" in supplied:
                kinds.add("lines")
            if "name" in supplied:
                kinds.add("functions")
    return support


def inert_scopes(rule: dict) -> Tuple[str, ...]:
    """The scope keys on this rule that its standard's checker can never evaluate.

    Empty when the rule is fine — unscoped, or scoped on something the checker
    supplies. A rule with no ``standard`` key applies to every standard, so it is
    only inert if no checker anywhere supplies that scope kind.
    """
    declared = tuple(key for key in ("lines", "functions") if rule.get(key))
    if not declared:
        return ()

    standard = rule.get("standard")
    support = scope_support()
    if standard:
        # An unknown standard is a separate defect (a rule against nothing); this
        # channel reports scope, so say nothing rather than guess.
        if standard not in support:
            return ()
        evaluable = support[standard]
    else:
        evaluable = set().union(*support.values()) if support else set()

    return tuple(key for key in declared if key not in evaluable)


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines naming every inert bypass rule in a branch.

    A rule reported here is not suppressing anything and never was — deleting it
    changes no score. Kept off the violation channel on purpose: bypass hygiene is
    the branch's own housekeeping, not a standards failure.
    """
    bypass_file = Path(branch_path) / ".seedgo" / "bypass.json"
    if not bypass_file.exists():
        return []

    try:
        rules = json.loads(bypass_file.read_text(encoding="utf-8")).get("bypass", [])
    except (OSError, ValueError) as e:
        logger.info("Cannot read %s for inert-rule info: %s", bypass_file, e)
        return []

    lines = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        inert = inert_scopes(rule)
        if not inert:
            continue
        standard = rule.get("standard") or "all standards"
        scopes = " and ".join(f"'{key}'" for key in inert)
        verb = "never match" if len(inert) > 1 else "never matches"
        lines.append(
            f"{rule.get('file', '?')} [{standard}]: {scopes} {verb} — that checker gates file-wide "
            f"and passes no line/name, so this rule is inert. Scope it file-wide or drop it."
        )

    if lines:
        json_handler.log_operation(
            "inert_bypass_rules_found",
            {"branch": str(branch_path), "count": len(lines), "standard": "bypass"},
        )
    return lines
