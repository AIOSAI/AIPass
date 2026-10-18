# =================== AIPass ====================
# Name: entry_point_diff_check.py
# Description: v5 - entry points production declares that no test ever names
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Has the suite ever said this verb out loud?

Reference: entry_point_diff.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "entry_point_diff"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: An unknown name costs a missed finding, never a false one.
COMMAND_CONSTANTS: frozenset = frozenset({"COMMANDS", "HANDLED_COMMANDS", "VERBS", "SUBCOMMANDS"})

#: Route string is argument 0: the spelling flask, fastapi, starlette and aiohttp share.
ROUTE_DECORATORS: frozenset = frozenset({"route", "get", "post", "put", "patch", "delete", "websocket"})

#: Shorter verbs match unrelated strings too often for "mentioned" to be evidence.
MINIMUM_VERB_LENGTH: int = 3

MAX_REPORTED: int = 12


def _constant_strings(node: Optional[ast.AST]) -> List[str]:
    """Every string element of a tuple/list/set literal.

    `None` (bare `COMMANDS: tuple`) falls out of the isinstance; callers need no guard.
    """
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return []
    literals = [element for element in node.elts if isinstance(element, ast.Constant)]
    return [element.value for element in literals if isinstance(element.value, str)]


def _declaring_constant(targets: Sequence[ast.expr]) -> str:
    """The COMMANDS-style name among an assignment's targets, or "".

    The matching name, not targets[0]: `CLI = COMMANDS = (...)` reports COMMANDS.
    """
    for target in targets:
        if isinstance(target, ast.Name) and target.id in COMMAND_CONSTANTS:
            return target.id
    return ""


def _from_assignment(node: Union[ast.Assign, ast.AnnAssign], relpath: str) -> Dict[str, Dict]:
    """Verbs declared by a COMMANDS-style constant assignment."""
    targets: Sequence[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
    constant = _declaring_constant(targets)
    if not constant:
        return {}

    # No `node.value is None` guard: `_constant_strings(None)` already returns [].
    return {
        verb: {"file": relpath, "line": node.lineno, "how": f"declared in {constant}"}
        for verb in _constant_strings(node.value)
    }


def _from_route_decorators(node: Union[ast.FunctionDef, ast.AsyncFunctionDef], relpath: str) -> Dict[str, Dict]:
    """Routes declared by a decorator on a function or coroutine."""
    routes: Dict[str, Dict] = {}
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        tail = corpus.dotted_name(decorator.func).rsplit(".", 1)[-1]
        if tail not in ROUTE_DECORATORS:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            routes[first.value] = {
                "file": relpath,
                "line": decorator.lineno,
                "how": f"@{tail} on {node.name}()",
            }
    return routes


def _declared_in(tree: ast.Module, relpath: str) -> Dict[str, Dict]:
    """Entry point -> declaring site, for one production module."""
    declared: Dict[str, Dict] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            declared.update(_from_assignment(node, relpath))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declared.update(_from_route_decorators(node, relpath))
    return declared


def declared_entry_points(scanned: corpus.Corpus) -> Dict[str, Dict]:
    """Every entry point production declares, across the whole target.

    First declaration wins, so a re-exported verb cannot cost a project twice.
    """
    declared: Dict[str, Dict] = {}
    for relpath in sorted(scanned.production_trees):
        for entry_point, site in _declared_in(scanned.production_trees[relpath], relpath).items():
            declared.setdefault(entry_point, site)
    return declared


def measurable_entry_points(scanned: corpus.Corpus) -> Dict[str, Dict]:
    """Declared entry points long enough for a literal match to be evidence."""
    return {
        entry_point: site
        for entry_point, site in declared_entry_points(scanned).items()
        if len(entry_point) >= MINIMUM_VERB_LENGTH
    }


def mentioned_strings(scanned: corpus.Corpus) -> Set[str]:
    """Every string literal appearing anywhere in the test corpus.

    Whole literals: membership downstream is exact, never a substring test.
    """
    mentioned: Set[str] = set()
    for parsed in scanned.files:
        mentioned.update(corpus.string_constants(parsed.tree))
    return mentioned


def find_unnamed_entry_points(scanned: corpus.Corpus) -> List[Dict]:
    """Every declared entry point the test corpus never names, at its declaring site."""
    mentioned = mentioned_strings(scanned)
    rows: List[Dict] = []
    for entry_point, site in sorted(measurable_entry_points(scanned).items()):
        if entry_point in mentioned:
            continue
        rows.append(
            {
                "species": "WRONG-LAYER",
                "entry_point": entry_point,
                "nodeid": "",
                "file": site["file"],
                "line": site["line"],
                "declared": site["how"],
                "reason": (
                    f"'{entry_point}' is {site['how']} ({site['file']}:{site['line']}), and no string "
                    f"literal anywhere in this project's test corpus names it - nothing in the suite "
                    f"would notice if it stopped working"
                ),
            }
        )
    return rows


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests name the entry points it declares.

    bypass_rules is accepted for the scoring-API contract and unread: advisory gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # Built before the empty-path returns: an unparseable file must never read as an absent one.
    unreadable: List[Dict] = _limit_checks(scanned)

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Entry point coverage", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    declared = measurable_entry_points(scanned)
    if not declared:
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [
                {
                    "name": "Entry point coverage",
                    "passed": True,
                    "message": (
                        f"no entry point was declared in a shape this rule can read across "
                        f"{len(scanned.production_trees)} production file(s) - nothing measured, so "
                        f"nothing scored"
                    ),
                }
            ]
            + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unnamed_entry_points(scanned)
    score = int(((len(declared) - len(flagged)) / len(declared)) * 100)
    checks: List[Dict] = [
        {
            "name": "Entry point coverage",
            "passed": not flagged,
            "message": (
                f"{len(declared) - len(flagged)}/{len(declared)} declared entry point(s) are named "
                f"somewhere in the test corpus"
                if not flagged
                else (
                    f"{len(flagged)}/{len(declared)} declared entry point(s) are named by no test: "
                    + ", ".join(row["entry_point"] for row in flagged[:MAX_REPORTED])
                    + (f" (+{len(flagged) - MAX_REPORTED} more)" if len(flagged) > MAX_REPORTED else "")
                )
            ),
        }
    ]

    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }


def _limit_checks(scanned: corpus.Corpus) -> List[Dict]:
    """The lines saying what could NOT be read, test side and production side.

    Published on every return path: an unread production file hides its findings.
    """
    checks: List[Dict] = []

    if scanned.unparseable:
        checks.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

    production_limit = scanned.production_limits()
    if production_limit:
        checks.append(
            {
                "name": "Production readable",
                "passed": True,
                "message": (
                    f"{production_limit} - an entry point declared inside one of them is invisible "
                    f"to this rule, so this score is biased toward FEWER findings"
                ),
            }
        )

    return checks
