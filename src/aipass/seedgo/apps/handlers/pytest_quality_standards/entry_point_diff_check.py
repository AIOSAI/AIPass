# =================== AIPass ====================
# Name: entry_point_diff_check.py
# Description: v5 - entry points production declares that no test ever names
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Has the suite ever said this verb out loud?

PORTED FROM THE TAXONOMY NOMINATOR of the same name onto the v5 scoring API.
Every other check in this pack reads a test and asks what it proves. This one
reads PRODUCTION first, enumerates the entry points it DECLARES - CLI verbs in a
`COMMANDS`-style tuple, HTTP routes on a decorator - and diffs them against every
string literal in the test corpus. A declared entry point no test mentions
anywhere is an entry point nothing covers, however green the line-coverage number
over the handler behind it.

IN WAVE 1 THIS FOUND SIX UNEXERCISED HTTP ROUTES over a 97-percent-covered
handler lane, and it was the only security-consequential finding in the sweep.
The cost estimate recorded by the branch that proposed it was ten lines of code.

THE COMPARISON IS AN EXACT LITERAL MATCH, AND THAT CUTS BOTH WAYS. A verb is
"mentioned" when the WHOLE string literal equals it, anywhere in the test corpus:
an argument, a parametrize entry, a fixture table, a module-level list. It is the
weakest test of coverage that still means something - a verb passed to a function
that immediately discards it acquits, and the execution tier is where "mentioned"
becomes "exercised".

It is NOT a substring search, and the nominator this was ported from described it
loosely enough to suggest otherwise. The words "purge-all" inside a prose
docstring or a comment do not acquit `purge-all`, because a substring search over
raw text is precisely the v4 defect this pack exists to delete: it is what let a
file of pattern strings with no code score 94 percent, and it would let any
branch clear this rule by writing its verbs into a comment. So the rule
over-CONVICTS where the mention is only prose, rather than over-acquitting where
the mention is only a substring. Wrong in the direction that produces a finding a
human can dismiss in ten seconds, never in the direction that produces a green
number nobody earned.

THE DENOMINATOR IS ENTRY POINTS, NOT TEST UNITS, AND THAT IS A DELIBERATE BREAK
FROM ITS SIBLINGS. Every other check in this pack scores flagged units over total
units. This rule's finding is an ABSENCE - there is no unit at fault, so scoring
it over units would produce 100 on every project forever, a number that cannot
move and therefore says nothing. What is measured is the share of DECLARED entry
points the suite names. A project that declares none reports not_applicable for
the same reason a project with no tests does: nothing measured is not nothing
found.

WHAT THIS FILE CANNOT SEE, STATED RATHER THAN IMPLIED. A verb assembled at
runtime (`f"{prefix}-install"`, a dict built in a loop, a plugin registry filled
by an entry-point group) is invisible to a static reader and is never counted, so
it is never flagged - the bias runs toward FEWER findings. A route reached only
through a mounted sub-app is a known false positive. And because this rule reads
production, a production file that will not parse declares nothing it can read;
that is why `production_limits()` is published beside the score on every return
path. A hole and an unread file look identical from outside, and the difference
is the entire honesty of the claim "no test mentions it".

ONE ARM CAME ACROSS DEAD AND IS NOT HERE. The nominator guarded `_from_assignment`
with `if node.value is None: return {}` for the `COMMANDS: tuple` annotation
shape. It never decided anything - `_constant_strings(None)` fails its isinstance
and returns `[]`, so the result is `{}` either way - and deleting it left every
behavioural pin green. It is gone rather than carried forward and pinned, so
nobody later "fixes" a real bug by editing a branch that never fires. The
behaviour it appeared to protect is pinned instead, at `_constant_strings`.

STDLIB ONLY, like the rest of the pack: `ast`, `pathlib`, `typing`, and the
pack's own corpus reader. That constraint is the reason the pack exists.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "entry_point_diff"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Module-level tuple/list names that declare a module's CLI verbs. Kept short
#: and conventional: a name this list does not know declares nothing this rule
#: can read, which costs a missed finding and never a false one.
COMMAND_CONSTANTS: frozenset = frozenset({"COMMANDS", "HANDLED_COMMANDS", "VERBS", "SUBCOMMANDS"})

#: Decorator names that declare an HTTP route. The route string is argument 0,
#: which is the spelling flask, fastapi, starlette and aiohttp all share.
ROUTE_DECORATORS: frozenset = frozenset({"route", "get", "post", "put", "patch", "delete", "websocket"})

#: Verbs too short for a literal match to mean anything. A two-character verb
#: appears inside unrelated strings often enough that "mentioned" stops being
#: evidence, so short verbs are not measured rather than measured badly.
MINIMUM_VERB_LENGTH: int = 3

#: How many flagged entry points to name in the result. The full list lives in
#: the report artifact; a check message that prints hundreds of lines is
#: unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# READING WHAT PRODUCTION DECLARES
# =============================================================================


def _constant_strings(node: Optional[ast.AST]) -> List[str]:
    """Every string element of a tuple/list/set literal.

    A non-literal value - `COMMANDS = load_commands()` - yields nothing, and
    that is the runtime-assembly blind spot named in the module docstring
    rather than a case worth guessing at. `None` is accepted for the same
    reason: an annotation with no value (`COMMANDS: tuple`) declares a shape
    and no verbs, and it falls out of the isinstance rather than needing a
    guard of its own at the call site.
    """
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return []
    literals = [element for element in node.elts if isinstance(element, ast.Constant)]
    return [element.value for element in literals if isinstance(element.value, str)]


def _declaring_constant(targets: Sequence[ast.expr]) -> str:
    """The COMMANDS-style name among an assignment's targets, or "".

    THE MATCHING NAME, NOT THE FIRST NAME. The nominator this was ported from
    reported `names[0]`, so `CLI = COMMANDS = ("run",)` told a reader the verb
    was "declared in CLI" - a name that is not in COMMAND_CONSTANTS and is not
    why the verb was found. A reader who goes looking for the reason and finds
    a name the rule never matched on stops trusting the row.
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

    # AN ANNOTATION WITHOUT A VALUE - `COMMANDS: tuple` - IS A DECLARATION OF
    # SHAPE, NOT OF VERBS, AND IT NEEDS NO GUARD HERE. The nominator this was
    # ported from carried `if node.value is None: return {}` at this line, and
    # it never once decided anything: `_constant_strings(None)` fails its
    # isinstance and returns [], so the dict comprehension is empty either way.
    # Deleting it left every behavioural pin green, which is the definition of
    # code that is not running the show. It is gone rather than pinned, so
    # nobody later "fixes" a real bug by editing a branch that never fires -
    # the same call corpus.py made on its dead With/AsyncWith arm.
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
    """Entry point -> declaring site, for one production module.

    `ast.walk` rather than a scan of `tree.body`, so a verb tuple defined
    inside a class body or a factory function is still read. That is generous
    in the direction of finding MORE declarations, which is the direction that
    produces findings rather than hiding them.
    """
    declared: Dict[str, Dict] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            declared.update(_from_assignment(node, relpath))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declared.update(_from_route_decorators(node, relpath))
    return declared


def declared_entry_points(scanned: corpus.Corpus) -> Dict[str, Dict]:
    """Every entry point production declares, across the whole target.

    ONE ROW PER ENTRY POINT, FIRST DECLARATION WINS. A verb re-exported from
    two modules is one thing a test can name, not two, so it must not be able
    to cost a project twice. Files are read in sorted order so the site a
    reader is sent to does not depend on filesystem walk order.
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


# =============================================================================
# READING WHAT THE TESTS SAY
# =============================================================================


def mentioned_strings(scanned: corpus.Corpus) -> Set[str]:
    """Every string literal appearing anywhere in the test corpus.

    Whole-file, not per-unit: a verb named in a module-level parametrize table
    or a shared fixture is named by the suite, and attributing the mention to a
    single unit would manufacture findings out of file layout.

    The set holds WHOLE literals. Membership downstream is therefore exact, not
    a substring test - see the module docstring for why that direction is the
    only safe one.
    """
    mentioned: Set[str] = set()
    for parsed in scanned.files:
        mentioned.update(corpus.string_constants(parsed.tree))
    return mentioned


def find_unnamed_entry_points(scanned: corpus.Corpus) -> List[Dict]:
    """Every declared entry point the test corpus never names.

    The public entry point for this rule - the report lane and the tests both
    ask the question here rather than re-deriving it. Rows are attributed to
    the DECLARING site, because the defect is an absence and there is no test
    to point at; the reader still needs somewhere to go.
    """
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


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests name the entry points it declares.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory. A project with no tests, or with no declared entry point,
        reports not_applicable rather than a number, because zero measured is
        not zero found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version of the reference check returned "no test files
    # found" before this ran, so a project whose ONLY test file had a syntax
    # error reported exactly what a project with no tests at all reports. A
    # broken file must never read as an absent one - that is the whole contract
    # `unparseable` exists to keep, and it was defeated on the one path where
    # nothing else could catch it. The ordering here is the fix, inherited.
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

    THE PRODUCTION LINE IS THE MOST IMPORTANT LINE THIS CHECK EMITS. The claim
    it makes is "production declares X and no test names it", and that claim is
    only honest beside a count of the production files it could not read. An
    unreadable file declares nothing, so every entry point inside it is a
    finding that never happens - the bias runs toward CLEAN, which is the
    direction nobody goes looking. Publishing it beside the score is what stops
    a hole and an unread file from looking identical from outside.
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
