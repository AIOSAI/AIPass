# =================== AIPass ====================
# Name: host_leak_check.py
# Description: v5 - does a test that fakes a platform build its fake data out of the real host
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""Does this test's fake world leak the real host into it?

THE ROW THIS RULE WAS WRITTEN FOR. @ai_mail's `tests/test_wake.py::
test_get_pid_cwd_darwin` forced `sys.platform` to `darwin`, and then built the
fake `lsof` output it hands the parser out of `tmp_path`:

    monkeypatch.setattr("sys.platform", "darwin")
    target = str(tmp_path / "project")

    class FakeResult:
        returncode = 0
        stdout = f"p100\\nn{target}\\n"          # flagged

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
    assert _get_pid_cwd("100") == target

The parser under test accepts one grammar - `line.startswith("n/")` - and on the
Windows runner `tmp_path` renders `C:\\Users\\...`, so the `n/` prefix the parser
requires never appeared. The unit could not parse the line the unit itself had
written, `_get_pid_cwd` answered None, and the assertion read None == a path
(Windows run 35058244702). Nothing was wrong with `_get_pid_cwd`. The test
declared it was on macOS and then asked the real machine for half of its fixture.

THE CLASS, STATED ONCE: A TEST THAT PRETENDS TO BE SOMEWHERE ELSE MUST
MANUFACTURE THE WHOLE OF THAT ELSEWHERE. The moment a faked world takes one
value from the host it is actually running on, the fake is half real, and the
half that is real is the half that differs between runners.

THE ACQUITTAL IS THE REASON THIS RULE IS NARROW, AND IT SITS THREE LINES ABOVE
THE DEFECT IN THE SAME FILE. `test_get_pid_cwd_linux` fakes `sys.platform` and
binds the same `str(tmp_path / "project")`, and it is perfectly portable:

    target = str(tmp_path / "project")
    monkeypatch.setattr(os, "readlink", lambda p: target)
    assert _get_pid_cwd("100") == target        # NOT flagged

The two units differ in one thing. The linux row hands the host path to the
subject as a VALUE and gets it back unchanged - what goes in comes out, in
whatever spelling the host uses. The darwin row wove it into TEXT beside a
literal, and the literal was a POSIX grammar. So this rule does not ask "does
this unit use tmp_path while faking a platform" - measured, that question
returns 23 rows fleet-wide and every one of them is fine. It asks the narrower
question: was a host path woven into composed text.

WHAT IT MEASURED. Over 18 branches and 18,997 test units, on the tree as it
stood when this rule shipped: ZERO rows. The one row it exists for had been
cured hours earlier. The two looser arms that were measured first and rejected:
faking a platform beside any host value at all is 23 rows, all correct code;
weaving a host path into text with no platform fake is 223 rows, all correct
code, because a unit that never claims to be elsewhere is entitled to describe
the machine it is on. The platform fake and the text weaving are each harmless;
only the pair is the species.

THIS IS A REGRESSION GUARD, NOT A FINDER, AND THAT IS WHY `SCORED` IS FALSE. A
rule with zero rows has never been observed against a live positive, so its
precision on real hits is unmeasured - one reconstructed unit is a proof that
the arm fires, not a calibration. Moving a branch's number on a shape that has
never been seen convicting would be exactly the thing `platform_oracle` refuses
when it says an arm that would convict correct tests must not move a number.

WHAT IT CANNOT SEE, AND EVERY LIMIT RUNS TOWARD FEWER FLAGS.
- **It cannot see the parser.** Whether a woven host path is a defect depends on
  production: `_get_pid_cwd`'s darwin arm parses the text and went red, its linux
  arm passes the value through and is green. This reader walks test units and
  does not follow calls, so it nominates the site where the host got into the
  fake world and leaves the parser to a human.
- **It reads the unit, not its helpers.** Composition inside a fixture, a module
  helper or another file is invisible, and so is the platform fake that would
  have paired with it.
- **It never asks the running machine.** A finding means the same thing from
  either leg of the matrix, which is the property the thing it hunts destroys.

STDLIB ONLY, like the rest of the pack: `ast`, `pathlib`, `typing`, the pack's
corpus reader, and one PUBLIC helper from `platform_oracle_check`. That import
is deliberate. `sandbox_names` is already this pack's single answer to "which
names in this unit hold a path under a temporary directory", and a second,
independently drifting copy of that answer in a sibling rule is the duplication
this campaign exists to kill.
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, platform_oracle_check

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "host_leak"

#: NOMINATES, NEVER SCORES - see the module docstring. The rule publishes its
#: full finding list and the measured number, and reports 100.
SCORED: bool = False

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: The oracles a unit can overwrite to claim it is somewhere else. Read as
#: SUFFIXES, because the real spellings reach them through the module under
#: test - @aipass writes `...provider_wire.os.name` and @devpulse writes
#: `wire.sys.platform`, and a reader keyed on the bare dotted name sees neither.
PLATFORM_ORACLES: tuple = (
    "sys.platform",
    "platform.system",
    "platform.machine",
    "platform.release",
    "platform.platform",
    "platform.uname",
    "os.name",
)

#: Call tails that WRITE an attribute rather than read one. `setitem` is here for
#: `monkeypatch.setitem(sys.modules, ...)`-shaped fakes; `object` for
#: `patch.object(sys, "platform", ...)`.
FAKING_CALLS: frozenset = frozenset({"setattr", "patch", "object", "dict", "setitem"})

#: Keyword spellings of a patch target, so `patch(target="sys.platform")` is not
#: a hole the positional reader walks past.
TARGET_KEYWORDS: frozenset = frozenset({"target", "attribute"})

#: Calls that answer with a path belonging to the machine rather than to the
#: test. The sandbox half is NOT here - it is delegated to
#: `platform_oracle_check.sandbox_names`, which is this pack's single definition
#: of "derived from a temporary directory".
HOST_PROBES: frozenset = frozenset(
    {
        "cwd",
        "getcwd",
        "getcwdb",
        "home",
        "expanduser",
        "which",
        "realpath",
        "abspath",
        "gethostname",
        "getlogin",
        "getuser",
    }
)

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# THE PLATFORM FAKE
# =============================================================================


def _names_an_oracle(text: str) -> bool:
    """True when a patch-target string names a platform oracle."""
    return any(text == oracle or text.endswith(f".{oracle}") for oracle in PLATFORM_ORACLES)


def _faked_by_string_target(node: ast.Call) -> str:
    """The oracle a one-string patch target names, or "".

    `monkeypatch.setattr("sys.platform", "darwin")` and `patch("sys.platform")`
    are the same shape to this reader, and they are the two commonest spellings
    in the corpus.
    """
    if not node.args:
        return ""
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str) and _names_an_oracle(first.value):
        return first.value
    return ""


def _faked_by_split_target(node: ast.Call) -> str:
    """The oracle an (object, "attr") patch target names, or "".

    `monkeypatch.setattr(sys, "platform", "linux")` and
    `monkeypatch.setattr(wire.sys, "platform", "darwin")` both land here. Only
    the object's LAST segment is used, because the module under test is reached
    by any number of prefixes and none of them change which attribute is written.
    """
    if len(node.args) < 2:
        return ""
    owner = corpus.dotted_name(node.args[0])
    attribute = node.args[1]
    if not owner or not isinstance(attribute, ast.Constant) or not isinstance(attribute.value, str):
        return ""
    spelling = f"{owner.rsplit('.', 1)[-1]}.{attribute.value}"
    return spelling if _names_an_oracle(spelling) else ""


def _faked_by_keyword(node: ast.Call) -> str:
    """The oracle a keyword patch target names, or ""."""
    for keyword in node.keywords:
        value = keyword.value
        if keyword.arg in TARGET_KEYWORDS and isinstance(value, ast.Constant) and isinstance(value.value, str):
            if _names_an_oracle(value.value):
                return value.value
    return ""


def _faking_calls(unit_node: ast.AST) -> Iterator[ast.Call]:
    """Every call in a unit that could write an attribute.

    NO SEPARATE DECORATOR WALK, AND THAT IS A MEASUREMENT RATHER THAN AN
    OVERSIGHT. `decorator_list` is a field of the FunctionDef node, so
    `ast.walk` already descends into `@patch("sys.platform", "darwin")` - the
    first version of this function carried an explicit second pass over the
    decorators, and deleting it left every behavioural pin green, which is the
    definition of code that is not running the show. It is gone rather than
    pinned, so nobody later "fixes" a bug by editing a dead branch.

    What stays invisible is a fake applied by a CLASS-level or MODULE-level
    mark, which belongs to no unit's node. That is a finding that does not
    happen, so the bias runs toward clean.
    """
    for node in ast.walk(unit_node):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        tail = dotted.rsplit(".", 1)[-1]
        if tail in FAKING_CALLS or dotted.endswith("patch"):
            yield node


def platform_fakes(unit: corpus.TestUnit) -> List[Tuple[int, str]]:
    """Every site where the unit claims to be on a platform it may not be on.

    The public entry point for this half of the rule - the pins ask the question
    here rather than re-deriving it.
    """
    found: List[Tuple[int, str]] = []
    for node in _faking_calls(unit.node):
        oracle = _faked_by_string_target(node) or _faked_by_split_target(node) or _faked_by_keyword(node)
        if oracle:
            found.append((node.lineno, oracle))
    return found


# =============================================================================
# THE HOST-DERIVED NAMES
# =============================================================================


def _is_probe_call(node: ast.AST) -> bool:
    """True when an expression asks the machine for one of its own paths."""
    if not isinstance(node, ast.Call):
        return False
    return corpus.dotted_name(node.func).rsplit(".", 1)[-1] in HOST_PROBES


def _mentions(node: ast.expr, bound: Set[str]) -> bool:
    """True when an expression reads a host-derived name or probes the host."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in bound:
            return True
        if _is_probe_call(child):
            return True
    return False


def host_names(unit: corpus.TestUnit) -> Set[str]:
    """Every name in a unit that holds a path belonging to the machine.

    THE SANDBOX HALF IS NOT RE-DERIVED HERE. `platform_oracle_check.sandbox_names`
    already answers "which names hold a path under a temporary directory" for
    three arms of that rule, and a second copy would be one more chance for two
    rules in one pack to disagree about what "derived from" means. This function
    adds only what that one does not model - the profile and the working
    directory - and grows the union to a fixed point, so `root = Path.home() /
    "x"` then `text = str(root)` carries through both hops.
    """
    bound = set(platform_oracle_check.sandbox_names(unit.node))
    changed = True
    while changed:
        changed = False
        for target, value in _bindings(unit.node):
            if not isinstance(target, ast.Name) or target.id in bound or value is None:
                continue
            if _mentions(value, bound):
                bound.add(target.id)
                changed = True
    return bound


def _bindings(unit_node: ast.AST) -> Iterator[Tuple[ast.expr, ast.expr]]:
    """Every assignment (target, value) pair in a unit.

    THE `with ... as name` HEADER IS DELIBERATELY ABSENT, AND IT IS NOT A HOLE.
    The shape that binds a host path through a context manager is
    `with tempfile.TemporaryDirectory() as td`, and that is the SANDBOX half -
    already resolved, context headers included, by
    `platform_oracle_check.sandbox_names`, whose answer seeds the loop below.
    What this walk adds is the profile and the working directory, and nobody
    writes `with Path.home() as h`. Reading the header here too would be a
    second, independently drifting copy of a walk this pack already owns.
    """
    for node in ast.walk(unit_node):
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            yield node.target, node.value
            continue
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            yield target, node.value


# =============================================================================
# THE WEAVE
# =============================================================================


def _has_text_literal(parts: List[ast.expr]) -> bool:
    """True when any part is a NON-EMPTY string literal.

    THE LITERAL IS THE GRAMMAR, AND IT IS WHY THE EMPTY ONE DOES NOT COUNT.
    `f"n{target}"` is a POSIX line format with a host path dropped into it;
    `f"{target}"` is `str(target)` spelled with more characters and carries no
    claim about shape at all. Requiring a literal is what separates a fake
    protocol line from a stringification.

    THE NON-EMPTY TEST EARNS ITS KEEP ON `BinOp`, NOT ON f-STRINGS. CPython
    gives `f"{target}"` a `JoinedStr` holding ONE `FormattedValue` and no
    `Constant` at all, so the f-string arm is already clean without it. It is
    `"" + target` - a concatenation whose literal half claims nothing - that
    needs the guard, which is where its pin lives.
    """
    return any(isinstance(part, ast.Constant) and isinstance(part.value, str) and part.value for part in parts)


def _fstring_weave(node: ast.JoinedStr, bound: Set[str]) -> str:
    """ "f-string" when an f-string drops a host path beside a literal, else ""."""
    interpolated = [part.value for part in node.values if isinstance(part, ast.FormattedValue)]
    if not any(_mentions(part, bound) for part in interpolated):
        return ""
    return "f-string" if _has_text_literal(list(node.values)) else ""


def _binop_weave(node: ast.BinOp, bound: Set[str]) -> str:
    """ "concat" / "percent" when `+` or `%` glues a host path to a literal."""
    if not isinstance(node.op, (ast.Add, ast.Mod)):
        return ""
    sides = [node.left, node.right]
    if not _has_text_literal(sides):
        return ""
    if not any(_mentions(side, bound) for side in sides):
        return ""
    return "concat" if isinstance(node.op, ast.Add) else "percent"


def _join_weave(node: ast.Call, bound: Set[str]) -> str:
    """ "str.join" when a string literal joins a host path into one line."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "join":
        return ""
    if not isinstance(func.value, ast.Constant) or not isinstance(func.value.value, str) or not func.value.value:
        return ""
    return "str.join" if node.args and _mentions(node.args[0], bound) else ""


def weave_sites(unit: corpus.TestUnit, bound: Set[str]) -> List[Tuple[int, str]]:
    """Every site where the unit weaves a host path into composed text.

    The public entry point for this half of the rule.
    """
    sites: List[Tuple[int, str]] = []
    for node in ast.walk(unit.node):
        spelling = ""
        if isinstance(node, ast.JoinedStr):
            spelling = _fstring_weave(node, bound)
        elif isinstance(node, ast.BinOp):
            spelling = _binop_weave(node, bound)
        elif isinstance(node, ast.Call):
            spelling = _join_weave(node, bound)
        else:
            continue
        if spelling:
            sites.append((node.lineno, spelling))
    return sites


# =============================================================================
# THE ROWS
# =============================================================================


def _row(unit: corpus.TestUnit, fake: Tuple[int, str], site: Tuple[int, str]) -> Dict:
    """One finding, with the coordinates of both halves of the species."""
    fake_line, oracle = fake
    weave_line, spelling = site
    return {
        "species": "FAKE_PLATFORM_HOST_TEXT",
        "nodeid": unit.nodeid,
        "line": unit.line,
        "oracle": oracle,
        "oracle_line": fake_line,
        "weave": spelling,
        "weave_line": weave_line,
        "detail": (
            f"the unit forces {oracle} at line {fake_line}, then weaves a host path into "
            f"{spelling} text at line {weave_line} - the faked world is taking one value "
            f"from the machine it is really running on"
        ),
    }


def unit_rows(unit: corpus.TestUnit) -> List[Dict]:
    """The findings for one unit: at most one, because one unit is one place to look."""
    fakes = platform_fakes(unit)
    if not fakes:
        return []
    bound = host_names(unit)
    if not bound:
        return []
    sites = weave_sites(unit, bound)
    if not sites:
        return []
    # ONE ROW PER UNIT, NOT ONE PER SITE. A unit weaving the host into three
    # strings is one place a reader has to go and look, not three, and the
    # alternative spelling is exactly one edit away - `[_row(unit, fakes[0],
    # site) for site in sites]` - which is why the choice is made here, in the
    # open, rather than left to whichever loop a later edit reaches for.
    return [_row(unit, fakes[0], sites[0])]


def find_host_leaks(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose faked world leaks the real host into it."""
    rows: List[Dict] = []
    for unit in scanned.units():
        rows.extend(unit_rows(unit))
    return rows


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its faked platforms are faked all the way.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory, violations, and measured_score. While `SCORED` is False the
        reported score is 100 and the measured number travels in
        `measured_score` and in a check line naming the fallback. A project with
        no tests reports not_applicable rather than a number, because zero tests
        measured is not zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. A project whose ONLY test file has a syntax error must not report
    # what a project with no tests at all reports. That contract is the whole
    # reason `unparseable` carries a reason, and the one path where nothing else
    # can catch it is the early return below. The ordering here is the fix,
    # inherited from the reference check.
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
            "checks": [{"name": "Faked platform, real host", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_host_leaks(scanned)
    measured_score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Faked platform, real host",
            "passed": not flagged,
            "message": (
                f"{total}/{total} test units that fake a platform manufacture their own fixture text"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units fake a platform and then weave a host path "
                    "into the text they feed the subject: "
                    + ", ".join(row["nodeid"] for row in flagged[:MAX_REPORTED])
                    + (f" (+{len(flagged) - MAX_REPORTED} more)" if len(flagged) > MAX_REPORTED else "")
                )
            ),
        }
    ]

    # THE NOMINATION REPORTS, IT DOES NOT SCORE - AND IT SAYS SO IN THE OUTPUT.
    # This arm measured zero rows on the fleet it shipped against, so its
    # precision against a live positive has never been observed. Reporting 100
    # with the findings still attached is what lets that measurement happen;
    # reporting 100 and dropping the measured number would make the fallback
    # indistinguishable from a rule that found nothing.
    if not SCORED:
        checks.append(
            {
                "name": "Faked platform scoring",
                "passed": True,
                "message": (
                    f"REPORTING, NOT SCORING - this rule nominates while SCORED is False, so the "
                    f"reported score is 100. The measured score is {measured_score} "
                    f"({len(flagged)}/{total} units flagged); the findings above are complete"
                ),
            }
        )

    checks.extend(unreadable)

    return {
        "passed": True,
        "score": measured_score if SCORED else 100,
        "measured_score": measured_score,
        "scored": SCORED,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }
