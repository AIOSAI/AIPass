# =================== AIPass ====================
# Name: host_leak_check.py
# Description: v5 - does a test that fakes a platform build its fake data out of the real host
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""Does this test's fake world leak the real host into it?

Reference: host_leak.md
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, platform_oracle_check


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "host_leak"

#: Nominates, never scores: zero live positives, so precision is unmeasured (host_leak.md).
SCORED: bool = False

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Matched as SUFFIXES: real spellings reach them through the module under test
#: (`...provider_wire.os.name`, `wire.sys.platform`).
PLATFORM_ORACLES: tuple = (
    "sys.platform",
    "platform.system",
    "platform.machine",
    "platform.release",
    "platform.platform",
    "platform.uname",
    "os.name",
)

FAKING_CALLS: frozenset = frozenset({"setattr", "patch", "object", "dict", "setitem"})

TARGET_KEYWORDS: frozenset = frozenset({"target", "attribute"})

#: The sandbox half is NOT here: `platform_oracle_check.sandbox_names` is the pack's
#: single definition of "derived from a temporary directory"; do not copy it.
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

MAX_REPORTED: int = 12


def _names_an_oracle(text: str) -> bool:
    """True when a patch-target string names a platform oracle."""
    return any(text == oracle or text.endswith(f".{oracle}") for oracle in PLATFORM_ORACLES)


def _faked_by_string_target(node: ast.Call) -> str:
    """The oracle a one-string patch target names, or ""."""
    if not node.args:
        return ""
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str) and _names_an_oracle(first.value):
        return first.value
    return ""


def _faked_by_split_target(node: ast.Call) -> str:
    """The oracle an (object, "attr") patch target names, or "".

    Only the object's LAST segment counts: the module under test is reached by any prefix.
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

    No separate decorator walk: `ast.walk` already descends into `decorator_list`.
    """
    for node in ast.walk(unit_node):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        tail = dotted.rsplit(".", 1)[-1]
        if tail in FAKING_CALLS or dotted.endswith("patch"):
            yield node


def platform_fakes(unit: corpus.TestUnit) -> List[Tuple[int, str]]:
    """Every site where the unit claims to be on a platform it may not be on."""
    found: List[Tuple[int, str]] = []
    for node in _faking_calls(unit.node):
        oracle = _faked_by_string_target(node) or _faked_by_split_target(node) or _faked_by_keyword(node)
        if oracle:
            found.append((node.lineno, oracle))
    return found


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

    Seeds from `platform_oracle_check.sandbox_names` and adds only home/cwd probes.
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

    `with ... as name` is deliberately absent: `sandbox_names` already reads those headers.
    """
    for node in ast.walk(unit_node):
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            yield node.target, node.value
            continue
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            yield target, node.value


def _has_text_literal(parts: List[ast.expr]) -> bool:
    """True when any part is a NON-EMPTY string literal.

    The literal is the grammar; the non-empty test guards `"" + target`, not f-strings.
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
    """Every site where the unit weaves a host path into composed text."""
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
    # One row per unit, not per site: a unit is one place a reader has to look.
    return [_row(unit, fakes[0], sites[0])]


def find_host_leaks(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose faked world leaks the real host into it."""
    rows: List[Dict] = []
    for unit in scanned.units():
        rows.extend(unit_rows(unit))
    return rows


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its faked platforms are faked all the way.

    `bypass_rules` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # Built before the early return: an all-unparseable project must not read as "no tests".
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

    # Keep the measured number in the output, or the fallback reads like a rule that found nothing.
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
