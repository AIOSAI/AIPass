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
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

# Every checker in the pack lives under this package's parent.
HANDLERS_ROOT = module_file(__file__).parents[1]
PACK_ROOT = HANDLERS_ROOT / "aipass_standards"


# is_bypassed(file_path, standard, line=None, bypass_rules=None, name=None) -- the
# scope arguments are as passable positionally as by keyword, and most call sites use
# the positional form. Reading only keywords is how the first version of this map
# reported ten live standards as line-blind.
_SHARED_SIGNATURE = ("file_path", "standard", "line", "bypass_rules", "name")
_SHARED_IMPORT = "aipass.seedgo.apps.handlers.bypass.utils"
# Both entry points of the shared matcher, same signature: is_bypassed() answers
# yes/no, matching_rule() hands back the rule for its category/reason annotations.
_SHARED_NAMES = ("is_bypassed", "matching_rule")
_SCOPE_ARG = {"line": "lines", "name": "functions"}

# ---------------------------------------------------------------------------
# The advisory declares its own unreliability, in the advisory.
#
# Three branches measured this list independently and it is wrong in BOTH
# directions. @skills: 27 rules named dead, 6 of the 7 that were measurable were
# LIVE. @aipass: told 41, a control run (re-audit with bypass_rules=[]) proved
# 59 -- including 22 non-test rules this list structurally never mentions.
# @spawn: told 21, measured 41, and one rule dead in both lanes appeared in
# neither list. The cause is structural, not a typo: everything here is computed
# in the AUDIT lane, which walks apps/ and never tests/, so a tests/* rule reads
# as dead while it still suppresses findings in the CHECKLIST lane the edit hook
# runs; and some standards are branch_level and report in prose through
# checks[].message rather than a *_violations list, so a sweep over violation
# RECORDS sees nothing and calls those rules dead too.
#
# Fixing that means simulating the checklist lane per rule. Until someone does,
# the honest move is the one this branch applies to every filter and cap: the
# limitation announces itself, in the output, where the conclusions are read --
# a caveat kept in a plan file or a docstring is a caveat nobody was handed.
# ---------------------------------------------------------------------------
ADVISORY_CAVEAT = (
    "UNVERIFIED — this bypass advisory is wrong in BOTH directions, so it cannot be pruned from on its "
    "own. It calls LIVE rules dead: it is measured in the audit lane, which walks apps/ and never tests/, "
    "so a tests/* rule reads as dead here while it still suppresses findings in the checklist lane the "
    "edit hook runs; branch_level standards report in prose instead of violation records, so their live "
    "rules read as dead too. And it is blind the other way: it never mentions dead rules outside the "
    "shapes it can see. Measured on @skills, 6 of the 7 checkable 'dead' rules were live; @aipass was "
    "told 41 and a control run proved 59.",
    "Do not delete a rule because it is named below. Measure first: re-run the audit with the branch's "
    "bypass rules disabled — that control run is the only evidence that a rule suppresses nothing — and "
    "delete only what it proves dead. Treat the lines below as a place to start looking, not as findings.",
)

# Info lines are stored and re-rendered one at a time (audit artifact,
# audit_display), so the doubt travels on each conclusion as well as at the head
# of the block: a line quoted or read on its own must still arrive marked.
_UNVERIFIED = "unverified: "


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
    """Whether the matcher names in this module mean the shared utility.

    ``bypass_handler.is_bypassed`` shares the name with a different parameter
    ORDER (file_path, branch_path, standard, line), so reading positional
    arguments against the wrong signature yields confident nonsense. Resolve the
    binding before trusting it: a module that defines its own is disqualified,
    and one that imports from the shared package is not.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _SHARED_NAMES:
            return False
        if isinstance(node, ast.ImportFrom) and node.module == _SHARED_IMPORT:
            if any(alias.name in _SHARED_NAMES and alias.asname is None for alias in node.names):
                return True
    return False


@lru_cache(maxsize=1)
def scope_support() -> Dict[str, Set[str]]:
    """Map each standard to the scope kinds its checker can actually evaluate.

    Returns e.g. ``{"cli": {"lines"}, "handlers": set()}`` — an empty set meaning that
    standard only ever gates file-wide, so no ``lines``/``functions`` rule written
    against it can match.

    Read from the checker sources by AST rather than from a maintained list: a list
    would drift the same way the bypass rules themselves did. A standard counts as
    supporting a scope if ANY of its call sites supplies it — a checker that gates
    file-wide at the top of check_module and then re-checks per line still lets a
    ``lines`` rule narrow those per-line findings.
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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or getattr(node.func, "id", None) not in _SHARED_NAMES:
                continue
            standard = _argument(node, "standard")
            if not (isinstance(standard, ast.Constant) and isinstance(standard.value, str)):
                continue
            kinds = support.setdefault(standard.value, set())
            for param, scope in _SCOPE_ARG.items():
                if _is_supplied(_argument(node, param)):
                    kinds.add(scope)
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


@lru_cache(maxsize=1)
def standard_constants() -> Dict[str, Dict[str, str]]:
    """Each standard's module-level string constants, read from the checker sources.

    Read by AST rather than by importing the pack: branch_audit imports this
    module, so importing branch_audit's discover_checkers() back would be a
    cycle. These are module-level string constants, exactly as readable from
    the source as from the loaded module.
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

    A bypass rule suppresses a violation. If the standard is never evaluated on
    that kind of file, there is no violation to suppress and the rule is dead
    weight — not wrong, just no longer doing anything.

    Says nothing about two cases it genuinely cannot see. A wildcard file
    pattern covers both kinds of file at once. And a branch-level checker walks
    the tree itself: test_quality's module-coverage category names PRODUCTION
    modules while the standard is about tests, so reading its rules against the
    per-file lanes' scope would confidently report live rules as dead — the
    same mistake this module already made once by reading half a call site.
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

    Every conclusion here is a SUSPICION, not a finding: see ADVISORY_CAVEAT for
    what this lane cannot see in either direction. The caveat is returned as the
    first two lines whenever there is anything to report, so no renderer, quote
    or artifact can carry the list without it.

    Kept off the violation channel on purpose: bypass hygiene is the branch's own
    housekeeping, not a standards failure.
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
        # Parentheses, not brackets: audit_display renders every info line through
        # Rich, which reads "[handlers]" as a style tag and deletes it. This line
        # named a file and silently swallowed which standard it meant.
        lines.append(
            f"{_UNVERIFIED}{rule.get('file', '?')} ({standard}): {scopes} {verb} — that checker gates "
            f"file-wide and passes no line/name, so this rule looks inert. Widen it to file-wide, or "
            f"confirm with a control run before dropping it."
        )

    # Out-of-scope rules are grouped by standard and NAMED. They were once only
    # counted, to keep a 118-rule cleanup from becoming a 118-line wall. @prax
    # showed that trade is backwards: a branch told '9 of your 10 architecture
    # rules are dead' cannot find the nine except by re-auditing once per rule,
    # so the safe move is to delete none -- the opposite of the nudge's purpose.
    # Grouping keeps it to one line per standard while handing over the
    # identities, and nothing here is capped: a silent cap would recreate the
    # same unactionable count one layer down.
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
