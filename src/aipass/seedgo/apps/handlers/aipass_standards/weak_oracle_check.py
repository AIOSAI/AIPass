# =================== AIPass ====================
# Name: weak_oracle_check.py
# Description: Weak Oracle Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Weak Oracle Standards Checker Handler

Crack class D from the 2026-09-22 eyes-on review of @backup's tests, and the
largest verdict class the reviewers found: 51 WEAK rows out of 285 tests. A
test whose ENTIRE oracle cannot exclude the failure its name claims to
exclude.

SCORED ONLY WHEN IT IS THE WHOLE ORACLE. A test that asserts the effect and
also checks ``isinstance`` is a good test with a redundant line; charging it
would be charging the thoroughness. Every form below is judged against the
test's complete set of assertions -- ``assert`` statements plus ``mock.assert_*``
calls -- and one real assertion anywhere in the test acquits all of them.

THE SIX SCORED FORMS, each one a thing a test cannot satisfy by accident:

  D1 ``assert <constant>``           -- ``assert True`` cannot fail.
  D2 ``assert <name>`` alone         -- a bare local's truthiness. NOT
                                        ``assert is_ignored(p, spec)``: a
                                        predicate CALL's truthiness is the
                                        claim, and scoring it cost 1,356
                                        false hits in the first cut.
  D3 ``is not None`` alone           -- every object is not None.
  D4 ``isinstance(...)`` alone       -- the type, never the value.
  D5 ``assert_called`` / ``assert_called_once`` with NO arguments and no
     other assertion -- proves the call happened, pins nothing it was given.
  D6 ``assert f(...) is None`` where ``f`` is annotated ``-> None`` -- a
     tautology. The function CANNOT return anything else.

REPORTED WITH A COUNT, NEVER SCORED, because each of these can legitimately
be the right oracle and a rule cannot tell which:

  ``is None`` alone (not a ``-> None`` function) · ``len`` and ``count``
  compares · ``>=`` / ``<=`` / ``>`` / ``<`` bounds · ``in`` and ``not in``
  (substring of output, key of a dict) · ``== {}`` on a loader.

A ``pytest.raises`` anywhere in the test acquits it outright. "It raised the
right exception" is a real oracle, and it is often the only one a refusal
test needs.

NOT CHARGED TWICE: ``router_assert`` already owns
``assert handle_command(...) is True``. That form is a ``Compare`` against a
constant, which this rule reads as strong, so the two never meet.

CHECK FIRST, measured 2026-09-22 over the fleet's 561 test files:

  * SCORED: 177 files, 468 hits, 8.3s. Top three: @memory 20 files,
    @trigger 18, @ai_mail 17. By form -- D5 162, D3 143, D2 113, D4 48,
    D6 2, D1 0. There is not one ``assert True`` in the fleet.
  * REPORTED, not scored: 430 files, 4,667 soft oracles in the tests whose
    WHOLE oracle is soft. ``in`` / ``not in`` 3,346 · plain ``is None`` 632 ·
    ``len``/``count`` 428 · ``== {}`` 132 · bound compares 129.
  * THE FIRST CUT SAID 369 files and 2,000 hits, and 1,356 of those were
    ``assert <call>`` read as bare truthiness. ``assert spec.match_file(p)``
    is the claim, not a weak stand-in for one. Curing that also took the
    model file from red to 100: its second assertion is
    ``assert hasattr(generator, "update_readme_auto_sections")``.

A SOFT COMPANION DOES NOT ACQUIT; only a STRONG one does. This is the one
place the rule bites harder than it reads, so it is named here. A test whose
oracle is ``assert breach is not None`` plus two ``"text" in output`` checks
is scored D3, because nothing in it pins a value the product computed --
``test_ceiling_guard.py`` 153 and 162 are exactly that shape. The dispatch
asked for it directly with ``test_module_isolation.py:48``, whose companion
is a ``not in sys.modules``.

WHICH OF THE DISPATCH'S EVIDENCE LINES IT CONVICTS:

  * ``test_cli_routing.py:328`` -- ``spy.assert_called()`` with 11 params
    unpinned. CONVICTED, D5.
  * ``test_error_resilience.py:372`` -- ``trail.log_operation(...) is None``
    where ``log_operation`` is ``-> None``. CONVICTED, D6, and it is one of
    only TWO in the fleet -- the rarest form that exists at all.
  * ``test_module_isolation.py:48`` -- ``twin is not None`` beside a
    ``not in sys.modules``. CONVICTED, D3: the second assertion is a
    containment check, which is reported-not-scored, so nothing in that test
    is a real oracle.
  * ``test_ceiling_guard.py:107`` -- ``is None`` alone. **DECLINED, reported
    only.** ``check_ceiling`` returns a breach OR None, so asserting None is
    a real claim about a real return. The reviewer's own break for it
    (``continue``->``break`` survives because the ghost is last) is a
    coverage gap, not a tautology. Its count rides in the passing message.
  * ``test_handlers_filesystem.py`` 119, 136, 192, 205, 212 -- ``isinstance``
    beside a real assert. **DECLINED, and the dispatch said so in advance.**
    Each of those tests has a live oracle next to the type check.
    ``test_build_snapshot_path`` at line 207 is NOT one of them and IS
    convicted D4: its companion is ``"snapshots" in str(result)``, a
    substring, where ``test_backup_root`` one test above asserts
    ``result.name == ".backup"`` and is acquitted. Two tests, four lines
    apart, and the rule separates them.

THE JUDGEMENT CALL THE DISPATCH ASKED FOR: an assertion on a value the test
itself set up (class E's shape) does NOT count as a real oracle here either
-- but this checker does not detect it, because doing so is class E's whole
job and building half of E inside D would put the same finding in two places
under two names. D therefore reads a self-set assert as strong and lets E
convict it. If E never ships, that is a known hole and this is where it is
written down.
"""

import ast
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple, Union

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "WEAK_ORACLE"
STANDARD_KEY = "weak_oracle"

#: The product's import root, for resolving a -> None annotation.
PRODUCT = "aipass"

#: Prefix that makes a function a test, which is the only unit this rule judges.
TEST_PREFIX = "test_"

#: Mock assertions that prove a call happened and pin nothing it was given.
_BLIND_CALLS: frozenset[str] = frozenset({"assert_called", "assert_called_once"})

D1 = "D1 assert on a constant"
D2 = "D2 a bare name's truthiness"
D3 = "D3 is not None, alone"
D4 = "D4 isinstance, alone"
D5 = "D5 assert_called with no argument check"
D6 = "D6 is None on a function annotated -> None"

CURE = "assert the effect the test's name claims"

#: The soft forms: reported with a count, never scored.
SOFT_NONE = "is None alone"
SOFT_LEN = "a len or count compare"
SOFT_BOUND = "a bound compare"
SOFT_IN = "an in / not in check"
SOFT_EMPTY = "== {} on a loader"

_SCORED = "scored"
_SOFT = "soft"
_STRONG = "strong"


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _module_file(dotted: str) -> Path | None:
    """The source file for an ``aipass.a.b`` module, as a module or a package."""
    here = Path(__file__).resolve()
    for index, part in enumerate(here.parts):
        if part == PRODUCT and index + 1 < len(here.parts):
            root = Path(*here.parts[: index + 1])
            relative = Path(*dotted.split(".")[1:])
            for candidate in (root / relative.with_suffix(".py"), root / relative / "__init__.py"):
                if candidate.is_file():
                    return candidate
            return None
    return None


@lru_cache(maxsize=256)
def none_returning_functions(dotted: str) -> frozenset[str]:
    """Every ``-> None`` function in a product module, cached per module.

    D6 is the only form that needs to leave the file, and it needs to: the
    annotation that makes ``assert f(...) is None`` a tautology lives on the
    product's ``def``, not at the call site.
    """
    source = _module_file(dotted)
    if source is None:
        return frozenset()
    try:
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError) as exc:
        logger.info("[weak_oracle] Cannot read %s for a -> None annotation: %s", dotted, exc)
        return frozenset()
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and isinstance(node.returns, ast.Constant)
        and node.returns.value is None
    )


def _none_returning(tree: ast.Module) -> Tuple[Set[str], Dict[str, str]]:
    """(bare names that return None, module alias -> its dotted path).

    Both spellings reach the same annotation: ``from x import f`` then
    ``f(...)``, and ``from x import mod`` then ``mod.f(...)``. @backup's
    ``test_error_resilience.py:372`` is the second, and reading only the
    first found zero instances in the whole fleet.
    """
    bare: Set[str] = set()
    modules: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(f"{PRODUCT}."):
            for alias in node.names:
                local = alias.asname or alias.name
                modules[local] = f"{node.module}.{alias.name}"
                if alias.name in none_returning_functions(node.module):
                    bare.add(local)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node.returns, ast.Constant) and node.returns.value is None:
                bare.add(node.name)
    return bare, modules


def _is_tautological(func: ast.expr, bare: Set[str], modules: Dict[str, str]) -> bool:
    """Whether this callee can only ever return None."""
    if isinstance(func, ast.Name):
        return func.id in bare
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        dotted = modules.get(func.value.id)
        return bool(dotted) and func.attr in none_returning_functions(dotted)
    return False


def _compare_verdict(test: ast.Compare, bare: Set[str], modules: Dict[str, str]) -> Tuple[str, str]:
    """The verdict for a single-operator comparison, which is most of them."""
    operator, right, left = test.ops[0], test.comparators[0], test.left
    if isinstance(right, ast.Constant) and right.value is None:
        if isinstance(operator, ast.IsNot):
            return _SCORED, D3
        if isinstance(left, ast.Call) and _is_tautological(left.func, bare, modules):
            return _SCORED, D6
        return _SOFT, SOFT_NONE
    if isinstance(left, ast.Call) and _tail_name(left.func) in ("len", "count"):
        return _SOFT, SOFT_LEN
    if isinstance(operator, (ast.GtE, ast.LtE, ast.Gt, ast.Lt)):
        return _SOFT, SOFT_BOUND
    if isinstance(operator, (ast.In, ast.NotIn)):
        return _SOFT, SOFT_IN
    if isinstance(right, ast.Dict) and not right.keys:
        return _SOFT, SOFT_EMPTY
    return _STRONG, ""


def _verdict(node: ast.AST, bare: Set[str], modules: Dict[str, str]) -> Tuple[str, str]:
    """(strength, form) for one oracle: an assert statement or a mock assertion."""
    if isinstance(node, ast.Call):
        blind = _tail_name(node.func) in _BLIND_CALLS and not node.args and not node.keywords
        return (_SCORED, D5) if blind else (_STRONG, "")

    test = node.test if isinstance(node, ast.Assert) else node
    if isinstance(test, ast.Constant):
        return _SCORED, D1
    if isinstance(test, ast.Name):
        return _SCORED, D2
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
        return _SCORED, D2
    if isinstance(test, ast.Call):
        # A CALL's truthiness is the claim: `assert is_ignored(p, spec)` and
        # `assert hasattr(generator, "update_readme_auto_sections")` both ask
        # the product a specific question and assert its answer. Only a bare
        # local name's truthiness (D2) is weak. isinstance is the exception,
        # because it answers about the TYPE and never about the value.
        return (_SCORED, D4) if _tail_name(test.func) == "isinstance" else (_STRONG, "")
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return _compare_verdict(test, bare, modules)
    return _STRONG, ""


def _tests(tree: ast.Module) -> List[Tuple[Union[ast.FunctionDef, ast.AsyncFunctionDef], List[ast.AST]]]:
    """Each test and its own nodes, in ONE descent.

    Walking the tree to find the tests and then walking each test again to
    collect its oracles re-walks every node twice; one stack descent carrying
    the enclosing test down took the fleet from 9.0s with identical findings.
    """
    nodes: Dict[int, List[ast.AST]] = {}
    owners: Dict[int, Union[ast.FunctionDef, ast.AsyncFunctionDef]] = {}
    stack: List[Tuple[ast.AST, Union[ast.FunctionDef, ast.AsyncFunctionDef, None]]] = [(tree, None)]
    while stack:
        node, enclosing = stack.pop()
        # isinstance INLINE, not through an `is_test` flag: pyright narrows a
        # type test, never a bool that holds its answer, and `owners` needs the
        # narrowed type to give `.lineno` and `.name` to the finding.
        if (
            enclosing is None
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith(TEST_PREFIX)
        ):
            enclosing = node
            nodes[id(node)], owners[id(node)] = [], node
        if enclosing is not None:
            nodes[id(enclosing)].append(node)
        for child in ast.iter_child_nodes(node):
            stack.append((child, enclosing))
    return [(owners[key], nodes[key]) for key in nodes]


def _oracles(function_nodes: List[ast.AST]) -> Tuple[List[Union[ast.Assert, ast.Call]], bool]:
    """Every oracle in a test, and whether a ``pytest.raises`` guards it."""
    found: List[Union[ast.Assert, ast.Call]] = []
    raises = False
    for node in function_nodes:
        if isinstance(node, ast.Assert):
            found.append(node)
            continue
        if not isinstance(node, ast.Call):
            continue
        name = _tail_name(node.func)
        if name.startswith("assert_"):
            found.append(node)
        raises = raises or name == "raises"
    # SOURCE order, not traversal order: the reported form is the first weak
    # oracle a reader meets, and _tests descends a stack (children reversed).
    return sorted(found, key=lambda node: (node.lineno, node.col_offset)), raises


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[weak_oracle] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str) -> Tuple[List[Tuple[int, str, str]], List[str]]:
    """(scored findings, soft forms counted).

    Returns the tests whose WHOLE oracle is one of the six scored forms, and
    separately the soft forms of every test whose whole oracle is soft -- a
    count for the owner, riding in the passing message, never a verdict.
    """
    tree = _parse(source)
    if tree is None:
        return [], []

    bare, modules = _none_returning(tree)
    scored: List[Tuple[int, str, str]] = []
    counted: List[str] = []
    for function, nodes in _tests(tree):
        found, raises = _oracles(nodes)
        if not found or raises:
            continue
        verdicts = [_verdict(node, bare, modules) for node in found]
        if any(strength == _STRONG for strength, _form in verdicts):
            continue
        forms = [form for strength, form in verdicts if strength == _SCORED]
        if forms:
            scored.append((function.lineno, function.name, forms[0]))
        else:
            counted.extend(form for _strength, form in verdicts)
    return sorted(scored), counted


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[weak_oracle] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Weak oracle", "passed": passed, "message": message}]


def _clean_message(counted: List[str]) -> str:
    """The passing message, carrying the soft count without making it a verdict.

    The device ``named_encoding`` uses for latin-1 and ``state_leak`` for the
    import-time write: a number the owner asked for rides along, and nobody
    is charged for it.
    """
    if not counted:
        return "Every test here asserts something that can fail"
    kinds = len(set(counted))
    shape = "form" if kinds == 1 else "forms"
    return (
        f"Every test here asserts something that can fail "
        f"({len(counted)} soft oracles in {kinds} {shape} are counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for tests whose whole oracle cannot fail.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    scored, counted = scan(source)
    if not scored:
        return _result(True, _one_check(True, _clean_message(counted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per test would show the first
    # and hide the rest behind a count.
    detail = "\n".join(f"{path.name}:{line} {name} — {form} - {CURE}" for line, name, form in scored)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(scored)},
    )
    return _result(False, _one_check(False, detail), 0)
