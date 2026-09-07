# =================== AIPass ====================
# Name: posix_literal_check.py
# Description: v5 - a rooted path literal put through a resolver
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

r"""Does this test hardcode one platform's idea of a root?

    slash_tmp = Path("/tmp").resolve()
    assert slash_tmp in roots

On POSIX that is `/tmp`. On Windows `/tmp` is DRIVE-RELATIVE: ntpath attaches the
current drive and `resolve()` hands back `D:\tmp`. The same line therefore means a
different thing on the other half of the matrix, and the assertion underneath it
accuses code that is working perfectly.

WHERE IT CAME FROM. A windows-setup leg went red on a return-value pin written the
same morning to catch a platform assumption: it compared against `RESOLVED: /tmp`
and CI handed it `D:\tmp`. The species was named in the report and the acquittal
rate asked for before it became a rule, which is the right order to do it in.

THE MEASUREMENT THAT DECIDED THE SHAPE, taken before the original nominator was
written, over 721 test files and 32,841 assert statements:

  - "an assert containing a rooted string literal" ........ 501 sites, 112 files
  - "a rooted literal reaching any callable named
     resolve / realpath / abspath" ....................... 10 sites, 3 files
  - THIS RULE (the receiver must BE a path constructor, or
     the callee an os.path-shaped function) ............... 4 sites, 1 file

The middle arm is the instructive one. Six of its ten sites were
`target_module.resolve("@canary", {...})` - a BRANCH-NAME resolver that happens to
share a verb with pathlib, holding a rooted literal in a dict value it never
resolves. A rule keyed on the method NAME nominates those six forever, and a rule
with that acquittal rate teaches a fleet to ignore it inside a week. Keyed on the
RECEIVER instead, it nominates none of them. That is the whole design.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM. It does not claim a flagged line is
wrong. A test that deliberately exercises POSIX spelling - a fence refusing
`/etc/passwd`, a parser fed a known-rooted input - is a legitimate site and stays.
What the flag buys is that the decision gets MADE rather than inherited from
whichever platform the author happened to be standing on.

IT ALSO SAYS NOTHING ABOUT THE MACHINE IT RUNS ON. `"/tmp"` is judged by its first
character and `"C:/tmp"` by its second and third, as text, never by asking the
running interpreter what it would do with them. A rule about portability that
consulted the host would be reporting a different standard on every leg of a
matrix, which is the defect it exists to find. It is also why this file's own pins
can be written on any host and mean the same thing.

ITS HONEST LIMITS, all of them in the direction of FEWER flags:

  - it reads the RECEIVER, so `home = Path("/tmp")` followed by `home.resolve()`
    is invisible. Chasing the value through a variable would mean following
    assignments, and the moment it does that it starts nominating the whole fleet.
  - `from os.path import realpath` then `realpath("/tmp")` is invisible: the call
    target is a bare name, and the module gate wants a dotted receiver whose last
    segment ends in `path` (`os.path`, `ntpath`, `posixpath`). `import os.path as
    osp` defeats it for the same reason.
  - it walks TEST UNITS, so a literal resolved in a fixture, in a module-level
    constant or in a helper the unit calls is not seen. Nothing here follows a
    call.
  - a rooted literal that is never resolved is not read at all. 501 sites carry
    one; four of them put it through a resolver, and the other 497 are data.

WHAT WAS DROPPED IN THE PORT, NAMED RATHER THAN CARRIED. The original nominator
re-tested `isinstance(call.func, ast.Attribute)` at the top of BOTH detector
helpers, and its only caller had already filtered on exactly that - neither guard
could ever fail. Removing them changes no answer; the check now lives once, at the
walker, where the filter actually happens. The same version then re-tested
`isinstance(literal, ast.Constant)` on what the helpers returned, and both helpers
only ever returned a node the rooted-literal predicate had already accepted - and
that predicate opens with the same isinstance. It was always true. Here the helpers
return `Optional[ast.Constant]` so the type carries the fact, instead of a branch
that looks like a check and is really a decoration.

STDLIB ONLY - `ast`, `pathlib`, `typing`, and the pack's own corpus reader. That
constraint is the reason the pack exists and can be lifted onto any project.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "posix_literal"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Constructors whose first argument is a path. A `.resolve()` hanging off one of
#: these is pathlib's resolve and no other object's - which is what keeps a
#: branch-name resolver sharing the verb out of the results.
PATH_CONSTRUCTORS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

#: Module-level functions that normalise a path against process state.
RESOLVER_FUNCTIONS: frozenset = frozenset({"realpath", "abspath"})

#: What the receiver of a resolver function has to look like. `os.path`,
#: `posixpath` and `ntpath` all end in it; `registry`, `shutil` and `helper` do
#: not, and a `helper.abspath(...)` is somebody else's method.
RESOLVER_MODULE_SUFFIX: str = "path"

#: The method whose receiver is read rather than whose name is trusted.
RESOLVE_METHOD: str = "resolve"

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def rooted_literal(node: ast.AST) -> Optional[ast.Constant]:
    """The node itself when it is a string literal that starts at a root.

    Args:
        node: Any AST node.

    Returns:
        The constant for `"/tmp"`, `"\\\\server"` and `"C:/tmp"`; None for
        `"tmp"`, for the empty string and for anything that is not a string.
    """
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    text = node.value
    if not text:
        return None
    if text[0] in ("/", "\\"):
        return node
    if len(text) > 2 and text[0].isalpha() and text[1] == ":" and text[2] in ("/", "\\"):
        return node
    return None


def _receiver_literal(func: ast.Attribute) -> Optional[ast.Constant]:
    """The rooted literal a `.resolve()` receiver was constructed from.

    Keyed on the RECEIVER and never on the method name: `Path("/tmp").resolve()`
    is pathlib, while `registry.resolve("@canary", ...)` is a branch-name lookup
    that happens to share a verb. Measured before choosing - the name test
    nominates six such sites fleet-wide and this one nominates none of them.

    Args:
        func: The attribute a call hangs off.

    Returns:
        The literal node, or None.
    """
    if func.attr != RESOLVE_METHOD:
        return None
    receiver = func.value
    if not isinstance(receiver, ast.Call) or not isinstance(receiver.func, ast.Name):
        return None
    if receiver.func.id not in PATH_CONSTRUCTORS or not receiver.args:
        return None
    return rooted_literal(receiver.args[0])


def _argument_literal(call: ast.Call, func: ast.Attribute) -> Optional[ast.Constant]:
    """The rooted literal an `os.path.realpath`-shaped call was handed.

    Args:
        call: The call node, read for its arguments.
        func: The attribute the call hangs off, read for the module it names.

    Returns:
        The literal node, or None.
    """
    if func.attr not in RESOLVER_FUNCTIONS or not call.args:
        return None
    if not corpus.dotted_name(func.value).endswith(RESOLVER_MODULE_SUFFIX):
        return None
    return rooted_literal(call.args[0])


def resolved_literals(unit: corpus.TestUnit) -> List[Tuple[str, int]]:
    """Every rooted literal this unit puts through a resolver.

    The public entry point for the rule's reading - the report lane and the tests
    both ask the question here rather than re-deriving it.

    Args:
        unit: One test unit.

    Returns:
        `(literal_text, lineno)` pairs, in source order. The line is the CALL's,
        because that is the line a reader has to go and look at.
    """
    found: List[Tuple[str, int]] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        literal = _receiver_literal(node.func)
        if literal is None:
            literal = _argument_literal(node, node.func)
        if literal is not None:
            found.append((str(literal.value), node.lineno))
    return found


def _finding(unit: corpus.TestUnit, line: int, text: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": "POSIX-LITERAL",
        "literal": text,
        "reason": (
            f"rooted path literal {text!r} put through a resolver - a rooted literal is "
            f"DRIVE-RELATIVE under ntpath, so this line means something else on the other "
            f"half of the matrix"
        ),
    }


def find_rooted_literals(scanned: corpus.Corpus) -> List[Dict]:
    """Every resolved rooted literal in the corpus, unit order preserved."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for text, line in resolved_literals(unit):
            rows.append(_finding(unit, line, text))
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. A unit resolving four rooted literals
    is one unit a reader has to go and look at; counting the findings would let a
    single loop-heavy test drive a project's score below zero, and a score that
    can go negative is one nobody believes twice.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests hardcode one platform's root.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory. A project with no tests reports not_applicable rather than a
        number, because zero tests measured is not zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version of the reference check returned "no test files
    # found" before this ran, so a project whose ONLY test file had a syntax
    # error reported exactly what a project with no tests at all reports. A
    # broken file must never read as an absent one - that is the whole contract
    # `unparseable` exists to keep, and it was defeated on the one path where
    # nothing else could catch it. The ordering here is the fix, inherited.
    unreadable: List[Dict] = []
    if scanned.unparseable:
        unreadable.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

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
            "checks": [{"name": "Rooted path literals", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_rooted_literals(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Rooted path literals",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units keep their path claims off a single dialect"
                if not units
                else (
                    f"{len(units)}/{total} test units put a rooted path literal through a resolver: "
                    + ", ".join(units[:MAX_REPORTED])
                    + (f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else "")
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
