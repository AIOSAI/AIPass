# =================== AIPass ====================
# Name: entry_point_diff_check.py
# Description: nominator - declared entry points no test ever names (WRONG-LAYER)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""TAXONOMY rule 10 — the verb the suite has never once said out loud.

Reference: entry_point_diff.md
"""

import ast
from typing import Dict, List, Set

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_entry_point_diff"

#: Module-level tuple/list names that declare a module's CLI verbs.
COMMAND_CONSTANTS: frozenset = frozenset({"COMMANDS", "HANDLED_COMMANDS", "VERBS", "SUBCOMMANDS"})

#: Decorator names that declare an HTTP route. The route string is arg 0.
ROUTE_DECORATORS: frozenset = frozenset({"route", "get", "post", "put", "patch", "delete", "websocket"})

#: Verbs too short or too generic for a literal match to mean anything.
MINIMUM_VERB_LENGTH = 3

#: Reads production, so an unparseable production file under-reports; `nominators`
#: merges the corpus's count into this group's limits when set.
READS_PRODUCTION = True

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 10 - entry-point diff",
    "species": ["WRONG-LAYER"],
    "flags": [
        "a CLI verb declared in a COMMANDS/HANDLED_COMMANDS tuple that no string literal in the test corpus ever names",
        "an HTTP route declared by a @route/@get/@post decorator that no test literal names",
    ],
    "exempts": [
        "a verb shorter than 3 characters is skipped - a literal match on it means nothing",
        "a route reached only through a mounted sub-app is a known false positive (TAXONOMY)",
    ],
    "fix": "add a test that names the entry point, or delete the entry point - but see Law M11 first.",
    "limits": [
        "'mentioned' is the weakest possible test: an exact string literal anywhere in the "
        "corpus acquits, including in a docstring. This over-acquits on purpose - a guessing "
        "nominator is worse than a blind spot with a name",
        "a verb assembled at runtime is invisible to a static reader",
    ],
    "evidence": (
        "6 unexercised HTTP routes over a 97%-covered handler lane - the only "
        "security-consequential finding in wave 1 (TAXONOMY section 5 rule 10)"
    ),
}


def _constant_strings(node: ast.AST) -> List[str]:
    """Every string element of a tuple/list/set literal."""
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return []
    literals = [element for element in node.elts if isinstance(element, ast.Constant)]
    return [element.value for element in literals if isinstance(element.value, str)]


def _declared_in(tree: ast.Module) -> Dict[str, str]:
    """Entry point -> how it was declared, for one production module."""
    declared: Dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            declared.update(_from_assignment(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declared.update(_from_route_decorators(node))

    return declared


def _from_assignment(node) -> Dict[str, str]:
    """Verbs declared by a module-level COMMANDS-style constant."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = [t.id for t in targets if isinstance(t, ast.Name)]
    if not any(name in COMMAND_CONSTANTS for name in names):
        return {}

    value = node.value
    if value is None:
        return {}
    return {verb: f"declared in {names[0]}" for verb in _constant_strings(value)}


def _from_route_decorators(node) -> Dict[str, str]:
    """Routes declared by a decorator on a function."""
    routes: Dict[str, str] = {}
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        tail = corpus.dotted_name(decorator.func).rsplit(".", 1)[-1]
        if tail not in ROUTE_DECORATORS:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            routes[first.value] = f"@{tail} on {node.name}()"
    return routes


def _declared_entry_points(scanned: corpus.Corpus) -> Dict[str, str]:
    """Every entry point production declares, across the whole target."""
    declared: Dict[str, str] = {}

    # An unparseable file is counted by the corpus and published via `production_limits`.
    for tree in scanned.production_trees.values():
        declared.update(_declared_in(tree))

    return declared


def _mentioned_strings(scanned: corpus.Corpus) -> Set[str]:
    """Every string literal appearing anywhere in the test corpus."""
    mentioned: Set[str] = set()
    for parsed in scanned.files:
        mentioned.update(corpus.string_constants(parsed.tree))
    return mentioned


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every declared entry point the test corpus never names.

    Attributed to the corpus, not a unit: the defect is an absence; the row carries the declaring site.
    """
    declared = _declared_entry_points(scanned)
    mentioned = _mentioned_strings(scanned)
    rows: List[dict] = []

    for entry_point, how in sorted(declared.items()):
        if len(entry_point) < MINIMUM_VERB_LENGTH or entry_point in mentioned:
            continue
        rows.append(
            {
                "species": "WRONG-LAYER",
                "file": "(no test file - this is an absence)",
                "line": 0,
                "nodeid": "",
                "test": "",
                "verdict": corpus.VERDICT_SUSPECT,
                "why": (
                    f"'{entry_point}' is {how}, and no string literal anywhere in this target's "
                    f"test corpus names it - nothing in the suite would notice if it stopped working"
                ),
                "deletion_safety": dict(corpus.DELETION_SAFETY_UNPROBED),
                "evidence": {"entry_point": entry_point, "declared": how},
            }
        )

    return rows
