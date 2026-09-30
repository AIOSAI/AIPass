# =================== AIPass ====================
# Name: uncalled_public_function_check.py
# Description: Uncalled Public Function Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Uncalled Public Function Standards Checker Handler

Crack class O from the 2026-09-22 eyes-on review of @backup's tests: a public
function of a test file's DECLARED SUBJECT module -- the path in its one-line
docstring, test template v1 item 6 -- that no test in the branch ever calls.
The file claims to test that module; one of the module's public functions is
not tested by anything.

THE CRISP PART IS WHAT COUNTS AS CALLED, and it is the whole rule:

  * Named in a ``Call``, or an attribute access that is then called, IS
    called. ``share_mod.run_share(file_arg)`` is a call.
  * Named ONLY as a ``patch`` / ``monkeypatch.setattr`` target -- replaced and
    never run -- is NOT called. That is shape O1, and @backup's
    ``apps/backup.py:125 discover_modules`` is it exactly: four sites in
    ``test_cli_routing.py`` replace it with ``return_value=[fake_module]`` and
    nothing anywhere runs the real importlib discovery.
  * REACHED ONLY THROUGH THE PRODUCT is the false conviction to avoid, and the
    dispatch asked how I decide it. A name-level call graph over the branch's
    whole ``apps/``, seeded with every function name the tests DO call and
    closed to a fixed point: if the function is in that closure, some test
    already drives a real path into it and the rule acquits. That guard is not
    decoration -- it acquits 19 of the 21 candidates, including
    ``route_command`` and every ``print_introspection``, which ``main()``
    reaches for tests that call ``main()``.

  A name-level graph collapses two modules that both define ``run``, so it
  over-acquits rather than under-acquits. For a SCORED rule that is the right
  direction, and the number it acquits is reported rather than hidden.

CHECK FIRST, measured 2026-09-22 over the fleet:

  * 2 files convicted, 2 hits. @backup both: ``apps/backup.py:125
    discover_modules`` (O1) and ``apps/handlers/report/result.py:50
    new_result`` (O2 -- defined once and referenced nowhere in apps/ or
    tests/).
  * ONLY 69 OF THE FLEET'S 561 TEST FILES DECLARE A SUBJECT PATH AT ALL. That
    is the headline and it caps the rule: O cannot judge a file that never
    says what it tests. ``file_top``'s item 6 sub-rule convicts the other 492,
    and every file it cures hands this rule a new subject to read.
  * 21 uncalled public functions in those 69 files' subjects: 19 reachable
    through the product (acquitted), 1 O1, 1 O2.

THE DISPATCH SAID 16 FILES AND 23 HITS. Mine is 2 and 2, and the correction is
almost entirely the reachability guard plus reading the docstring properly: a
subject line can name TWO modules (``Tests for apps/modules/share.py and
apps/handlers/drive/share.py``) and a rule that takes only the first match
mis-attributes half of them.

WHERE I DISAGREE WITH THE DISPATCH, WITH THE LINE NUMBER:

  ``apps/modules/share.py run_share`` is given as the evidence line, "replaced
  at test_share.py 100, 112, 122 and never runs anywhere in the suite." It
  runs. ``test_caller_path.py:86`` calls ``share_mod.run_share(file_arg)`` for
  real, with Drive mocked beneath it. The brief's own wording is "no test
  anywhere in the branch's tests/ calls", so this rule ACQUITS it and is right
  to. The three ``test_share.py`` monkeypatches are real -- ``discarded_patch``
  already looked at them and found them SOUND, because they are recorders that
  are asserted -- but they are not the whole suite's relationship to that
  function.

  ``apps/handlers/diff/generator.py generate_diff_content`` is offered
  conditionally, "if generator.py is within the subject of a backup test
  file". It is not. ``test_versioned_engine.py`` declares
  ``apps/handlers/copy/versioned.py`` and ``apps/modules/restore.py``, and no
  @backup test file names ``generator.py``. The rule does not see it, which is
  correct and is also a hole: a module nothing declares as a subject is
  invisible to O no matter how untested it is.

  ``apps/modules/restore.py``'s bare-basename fallback is a coverage gap
  inside a function, not a function. O does not see it and should not, exactly
  as the dispatch said.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: the file says in its own docstring
that it tests this module. If a public function of that module is never
called, never reachable from anything called, and named only where it is being
replaced, then nothing in the suite has ever run it. There is no threshold and
nothing to tune.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD = "UNCALLED_PUBLIC_FUNCTION"
STANDARD_KEY = "uncalled_public_function"

#: A subject path as test template v1 item 6 spells it: a repo-relative .py path.
SUBJECT = re.compile(r"((?:apps|lib)[\w./-]*\.py)")

#: The three verbs that REPLACE a function rather than run it.
_PATCH_VERBS: frozenset[str] = frozenset({"patch", "object", "setattr"})

REPLACED = "O1 replaced by a patch and never run"
UNREACHED = "O2 never named by a test and unreachable from one"

CURE = "call it in a test, or retire it"


def _tail_name(node: ast.AST) -> str:
    """The last name in a call target: ``a.b.c`` -> ``c``, ``f`` -> ``f``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _parse(path: Path) -> ast.Module | None:
    """A file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError) as exc:
        logger.info("[uncalled_public_function] Unparseable, nothing scanned: %s", exc)
        return None


def subjects_of(tree: ast.Module, branch_root: Path) -> List[Path]:
    """Every module a test file's one-line docstring says it tests.

    ``findall``, not ``search``: ``Tests for apps/modules/share.py and
    apps/handlers/drive/share.py`` declares TWO subjects, and taking only the
    first mis-attributes the second module's functions to nobody.
    """
    docstring = ast.get_docstring(tree) or ""
    first = docstring.splitlines()[0] if docstring else ""
    return [path for path in (branch_root / m for m in SUBJECT.findall(first)) if path.is_file()]


def _named_target(node: ast.AST) -> str:
    """The name a patch argument points at, string target or object attribute."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.rsplit(".", 1)[-1]
    return _tail_name(node)


def _read_tests(tests_dir: Path, branch_root: Path) -> Tuple[Set[str], Set[str], Set[str], List[Path]]:
    """(called, replaced, named outside a patch, every declared subject)."""
    called: Set[str] = set()
    replaced: Set[str] = set()
    elsewhere: Set[str] = set()
    subjects: List[Path] = []
    for path in sorted(tests_dir.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        subjects.extend(subjects_of(tree, branch_root))
        skip = _patch_targets(tree, replaced)
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.Call):
                called.add(_tail_name(node.func))
            elif isinstance(node, ast.Name):
                elsewhere.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                elsewhere.add(node.value.rsplit(".", 1)[-1])
    return called, replaced, elsewhere, subjects


def _patch_targets(tree: ast.Module, replaced: Set[str]) -> Set[int]:
    """Record every patched name and return the nodes that naming occupies.

    The target of a patch is not a mention of the function anywhere else, so
    those nodes are skipped when the "named outside a patch" set is built.
    """
    skip: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _tail_name(node.func) not in _PATCH_VERBS:
            continue
        for argument in node.args[:2]:
            replaced.add(_named_target(argument))
            skip |= {id(inner) for inner in ast.walk(argument)}
    return skip


def product_graph(branch_root: Path) -> Dict[str, Set[str]]:
    """Function name -> the names it calls, over the branch's whole ``apps/``."""
    graph: Dict[str, Set[str]] = {}
    for path in sorted((branch_root / "apps").rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            edges = {_tail_name(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
            graph.setdefault(function.name, set()).update(edges)
    return graph


def reachable(graph: Dict[str, Set[str]], seeds: Set[str]) -> Set[str]:
    """Everything the product can get to from what the tests actually call."""
    seen: Set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack.extend(graph.get(name, ()))
    return seen


def _publics(path: Path) -> List[Tuple[str, int]]:
    """(name, line) for every module-level public def in a subject module."""
    tree = _parse(path)
    if tree is None:
        return []
    return [
        (node.name, node.lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def _verdict(name: str, replaced: Set[str], elsewhere: Set[str], live: Set[str]) -> str:
    """Which shape this uncalled public function is, or "" when it is acquitted."""
    if name in replaced and name not in elsewhere:
        return REPLACED
    if name in replaced or name in live or name in elsewhere:
        return ""
    return UNREACHED


def scan(branch_root: Path) -> Tuple[List[Tuple[Path, int, str, str]], int]:
    """(findings, how many uncalled functions the product still reaches)."""
    tests_dir = branch_root / "tests"
    if not tests_dir.is_dir() or not (branch_root / "apps").is_dir():
        return [], 0

    called, replaced, elsewhere, subjects = _read_tests(tests_dir, branch_root)
    if not subjects:
        return [], 0

    live = reachable(product_graph(branch_root), called)
    findings: List[Tuple[Path, int, str, str]] = []
    acquitted = 0
    for subject in dict.fromkeys(subjects):
        for name, line in _publics(subject):
            if name in called:
                continue
            shape = _verdict(name, replaced, elsewhere, live)
            if shape:
                findings.append((subject, line, name, shape))
            else:
                acquitted += 1
    return sorted(findings), acquitted


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Uncalled public function", "passed": passed, "message": message}]


def _clean_message(acquitted: int) -> str:
    """The passing message, carrying the acquitted count without a verdict.

    The device ``weak_oracle`` uses for its soft oracles: a number the owner
    asked for rides along, and nobody is charged for it. Here it is the size of
    the reachability guard, which is the rule's biggest judgement.
    """
    if not acquitted:
        return "Every public function of every declared subject is called by a test"
    return (
        f"Every public function of every declared subject is called by a test "
        f"({acquitted} are reached only through the product, which the rule allows)"
    )


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for public functions of a declared subject nothing calls.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo).
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    branch_root = Path(branch_path)
    findings, acquitted = scan(branch_root)
    if not findings:
        return _result(True, _one_check(True, _clean_message(acquitted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per function would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.relative_to(branch_root)}:{line} {name} - {shape} - {CURE}" for path, line, name, shape in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
