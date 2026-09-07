# =================== AIPass ====================
# Name: empty_parametrize_check.py
# Description: v5 - a parametrize table that can vanish at collection time
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""A parametrized test over an empty table reports as passing.

    @pytest.mark.parametrize("item", collect())
    def test_every_found_item_is_valid(item):
        assert item["ok"]

If `collect()` returns `[]`, pytest generates no cases, marks the test SKIPPED,
and the run prints `1 passed, 1 skipped` with exit code 0. That was reproduced
verbatim before the nominator this file ports was written: the instrument
checked nothing and reported the same green a clean tree reports.

WHY THIS IS ITS OWN RULE. Every other reachability question in this pack reads a
skip, a guard or a loop that a reader can find in the source. Here there is no
skip in the source at all - pytest manufactures one from an empty argvalues
sequence. Somebody grepping the file for `skip` finds nothing, which is what
makes this the quietest species of the family.

WHERE IT CAME FROM. A branch building a content-anchored bypass rule found that
its first test file SURVIVED a mutant which blinded the collector to `return []`,
because the anchor checks were parametrized over the collector's output and the
whole file came back "1 passed, 2 skipped". Their arming probe asserted the raw
input list was non-empty, which is a different question from whether the
collector found anything. The cure they reported with it is the fix this rule
asks for: recount the entries INDEPENDENTLY, from the raw data, rather than by
calling the function under judgement.

THE ACQUITTALS MATTER MORE THAN THE FLAGS. A literal table cannot be empty, and
neither can a module constant bound to a non-empty literal, and neither can a
safe builtin wrapped around one - `range(24)` is a table written in shorthand,
not a query. Measured across one fleet before the nominator landed: 312
parametrize sites, 217 of them plain literals this rule never even looks at.

TWO SPECIES, AND THE SECOND IS SMALLER THAN THE FIRST. VANISHING-TABLE is a
computed table in a file with no independent guard at all. SHORT-TABLE is the
same table in a file whose guard asserts only that something was found: a
collector that silently drops ONE entry still satisfies it, every surviving case
still passes, and the run is two cases lighter than it should be. An empty run at
least looks odd; a short one looks like a normal run.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM.

It does not claim a flagged table is empty. A table legitimately empty on some
machines - a platform sweep with no rows on this OS - is the honest case, and no
static reader can tell it from the broken one. This tier nominates; an execution
tier convicts.

THE GUARD IS MATCHED ANYWHERE IN THE FILE, not proven to cover the table in
question, and it is matched loosely: any `len(...)` call inside any assert
counts, which means `assert len(rows) == 0` - an assertion that a collection IS
empty - acquits the file's tables too. Both are deliberate errors toward
ACQUITTING. A false flag on a file that already did the work teaches nothing and
gets a standard switched off.

ONE ARM DOES NOT DECIDE ANYTHING AND IS DOCUMENTED RATHER THAN DRESSED UP. A
count guard is an assert containing `len(...)`, so `_guard_pins_a_count` being
true forces `_has_independent_nonempty_guard` to be true as well: the skip
condition `guarded and counted` is decided entirely by `counted`. It is kept in
that spelling because it states the rule a reader needs - a file is excused when
it has done BOTH things - but no test pins the first operand, because no input
can make it the deciding one.

CLASS-LEVEL PARAMETRIZE IS INVISIBLE HERE. The corpus's units are functions, so
`@pytest.mark.parametrize` applied to a whole test CLASS is not read by this
rule. The nominator it ports has the same gap; it is stated rather than left for
someone to find as a hole in a number.

A CLASS-BODY CONSTANT IS NOT ACQUITTED, AND THAT IS A MEASURED FALSE POSITIVE.
Only module-level assignments are read for the safe-name set, so a table written
as a class attribute beside the tests that use it - `HELP_ARGV = [...]` in the
class body, `@pytest.mark.parametrize("argv", HELP_ARGV)` on the method - is
reported as a computed table although it is a literal the decorator can see. One
live site in the fleet is exactly this shape and is a false flag. The scope is
kept where the ported nominator put it rather than widened on the way past;
widening the safe-name set is a change to what the rule ACQUITS, which is the
half that has to be measured before it moves.

STDLIB ONLY, like the rest of the pack: `ast`, `pathlib`, `typing`, and the
pack's own corpus reader. That constraint is the reason the pack exists.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "empty_parametrize"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Builtins that cannot invent emptiness on their own: handed a non-empty
#: argument they return something non-empty. `range` is here because
#: `range(24)` is a table written in shorthand, not a query.
SAFE_BUILTINS: frozenset = frozenset({"range", "sorted", "list", "tuple", "reversed", "enumerate", "set"})

#: The mark whose second positional argument is the table.
PARAMETRIZE_NAME: str = "parametrize"

#: How much of the table expression to quote back at a reader. The point is
#: recognition, not reproduction - the file and line are in the row already.
EVIDENCE_CHARS: int = 120

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def _module_literal_names(parsed: corpus.TestFile) -> Set[str]:
    """Module-level names bound to a non-empty literal container.

    Only the module body is read, and only assignments in it. A name bound
    inside a function is genuinely out of reach; a name bound in a CLASS body
    is not - see the module docstring for the live false positive that costs,
    and why the scope is not widened here in passing.

    Args:
        parsed: The parsed test module.

    Returns:
        Names that cannot be empty at collection time.
    """
    safe: Set[str] = set()
    for node in parsed.tree.body:
        if isinstance(node, ast.Assign):
            targets: List[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and value.elts:
            safe.update(t.id for t in targets if isinstance(t, ast.Name))
        elif isinstance(value, ast.Dict) and value.keys:
            safe.update(t.id for t in targets if isinstance(t, ast.Name))
    return safe


def _cannot_be_empty(value: ast.expr, safe_names: Set[str]) -> bool:
    """True when this argvalues expression is non-empty by construction.

    Unwraps ONE layer of a safe builtin, so `sorted(WORLDS)` is judged on
    `WORLDS`. One layer deliberately: following an arbitrary chain would make
    this an interpreter, and nothing in this pack runs the subject.

    Args:
        value: The second positional argument to `parametrize`.
        safe_names: Module names bound to non-empty literals.

    Returns:
        True if the table cannot vanish.
    """
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return bool(value.elts)
    if isinstance(value, ast.Dict):
        return bool(value.keys)
    if isinstance(value, ast.Constant):
        return bool(value.value)
    if isinstance(value, ast.Name):
        return value.id in safe_names
    if isinstance(value, ast.Call):
        name = corpus.dotted_name(value.func).rsplit(".", 1)[-1]
        if name not in SAFE_BUILTINS or not value.args:
            return False
        return _cannot_be_empty(value.args[0], safe_names)
    return False


def _has_independent_nonempty_guard(parsed: corpus.TestFile) -> bool:
    """True when some assertion in this file measures a length at all.

    The cure, detected in the shape it is usually written: an assertion around
    a `len(...)` call somewhere in the file. Matched file-wide rather than
    proven to cover the table in question - see the module docstring on erring
    toward acquitting.

    Args:
        parsed: The parsed test module.

    Returns:
        True if an arming probe of that shape exists.
    """
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Call) and corpus.dotted_name(sub.func).rsplit(".", 1)[-1] == "len":
                return True
    return False


def _guard_pins_a_count(parsed: corpus.TestFile) -> bool:
    """True when some assertion compares a length against an expected value.

    A guard asserting `len(x)` is truthy answers "did it find anything". A
    guard asserting `len(x) == expected` answers "did it find them all", and
    only the second one notices a table that came back one entry short.

    `len(x) == 0` is excluded: that is an emptiness assertion, not a count.

    Args:
        parsed: The parsed test module.

    Returns:
        True if a count-pinning assertion exists anywhere in the file.
    """
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if not isinstance(sub, ast.Compare):
                continue
            if not (isinstance(sub.left, ast.Call) and corpus.dotted_name(sub.left.func).rsplit(".", 1)[-1] == "len"):
                continue
            for op, comparator in zip(sub.ops, sub.comparators):
                if not isinstance(op, ast.Eq):
                    continue
                if isinstance(comparator, ast.Constant) and comparator.value == 0:
                    continue
                return True
    return False


def _parametrize_tables(unit: corpus.TestUnit) -> List[Tuple[ast.expr, int]]:
    """Every `parametrize` decorator on a unit as (argvalues, lineno).

    A decorator with fewer than two positional arguments carries no table -
    that is `parametrize` used with keyword arguments, or something else
    wearing the name - and is passed over rather than guessed at.

    Args:
        unit: The test unit to read.

    Returns:
        One entry per parametrize decorator carrying argvalues.
    """
    tables: List[Tuple[ast.expr, int]] = []
    for decorator in unit.node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if corpus.dotted_name(decorator.func).rsplit(".", 1)[-1] != PARAMETRIZE_NAME:
            continue
        if len(decorator.args) < 2:
            continue
        tables.append((decorator.args[1], decorator.lineno))
    return tables


def _finding(species: str, unit: corpus.TestUnit, line: int, reason: str, argvalues: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it.

    Args:
        species: VANISHING-TABLE or SHORT-TABLE.
        unit: The unit the finding belongs to.
        line: The decorator's line, not the def's - the table is what to look at.
        reason: What the reader will see when they get there.
        argvalues: The table expression, quoted back for recognition.

    Returns:
        The finding row.
    """
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": species,
        "reason": reason,
        "argvalues": argvalues[:EVIDENCE_CHARS],
    }


def file_flags(parsed: corpus.TestFile) -> List[Dict]:
    """Every vanishing-table finding in one file, with the evidence for each.

    The public entry point for this rule - the report lane and the tests both
    ask the question here rather than re-deriving it. It takes a FILE and not a
    unit because both acquittals are file-scoped: the guard may be written in a
    different test than the one that carries the table, and the module
    constants a table names are bound at the top of the file.

    Args:
        parsed: The parsed test module.

    Returns:
        Finding rows for this file, unit order preserved.
    """
    guarded = _has_independent_nonempty_guard(parsed)
    counted = _guard_pins_a_count(parsed)
    if guarded and counted:
        return []

    safe_names = _module_literal_names(parsed)
    rows: List[Dict] = []
    for unit in parsed.units:
        for argvalues, lineno in _parametrize_tables(unit):
            if _cannot_be_empty(argvalues, safe_names):
                continue
            quoted = ast.unparse(argvalues)
            if guarded:
                rows.append(
                    _finding(
                        "SHORT-TABLE",
                        unit,
                        lineno,
                        f"parametrize table computed at collection time ({quoted[:60]}) - the file's guard "
                        f"asserts the collection is NON-EMPTY, which a collector that drops one entry still "
                        f"satisfies; pin the expected COUNT from raw data",
                        quoted,
                    )
                )
                continue
            rows.append(
                _finding(
                    "VANISHING-TABLE",
                    unit,
                    lineno,
                    f"parametrize table computed at collection time ({quoted[:60]}) - an empty result is "
                    f"reported as SKIPPED and the suite summary reads green",
                    quoted,
                )
            )
    return rows


def find_vanishing_tables(scanned: corpus.Corpus) -> List[Dict]:
    """Every parametrize table that could vanish without the suite noticing.

    Args:
        scanned: The parsed corpus.

    Returns:
        Finding rows across every file, file order preserved.
    """
    rows: List[Dict] = []
    for parsed in scanned.files:
        rows.extend(file_flags(parsed))
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. A unit stacking three parametrize
    decorators is one unit somebody has to go and look at; counting the
    findings would let one test be subtracted three times, push the flagged
    total past the unit total, and report a NEGATIVE score that no caller
    checks for.

    Args:
        rows: Finding rows.

    Returns:
        Distinct nodeids in the order they were first seen.
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
    """Score a project on whether its parametrize tables can vanish.

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
            "checks": [{"name": "Parametrize table", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_vanishing_tables(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Parametrize table",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units carry no parametrize table that could vanish"
                if not units
                else (
                    f"{len(units)}/{total} test units parametrize over a table computed at collection time: "
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
