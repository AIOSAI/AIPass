# =================== AIPass ====================
# Name: weak_oracle_check.py
# Description: Weak Oracle Standards Checker Handler
# Version: 1.0.3
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""
Weak Oracle Standards Checker Handler

Reference: weak_oracle.md
"""

from functools import partial
import ast
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple, Union

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result, tail_name

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

    D6 leaves the file: the ``-> None`` annotation lives on the product's ``def``.
    """
    source = _module_file(dotted)
    if source is None:
        return frozenset()
    try:
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError, ValueError) as exc:
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

    Both spellings matter: ``from x import f`` and ``from x import mod`` then ``mod.f(...)``.
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
    if isinstance(left, ast.Call) and tail_name(left.func) in ("len", "count"):
        return _SOFT, SOFT_LEN
    if isinstance(operator, (ast.GtE, ast.LtE, ast.Gt, ast.Lt)):
        return _SOFT, SOFT_BOUND
    if isinstance(operator, (ast.In, ast.NotIn)):
        return _SOFT, SOFT_IN
    if isinstance(right, ast.Dict) and not right.keys:
        return _SOFT, SOFT_EMPTY
    return _STRONG, ""


_CONTAINERS = (ast.List, ast.ListComp, ast.Set, ast.SetComp, ast.Dict, ast.DictComp)


def _built(function_nodes: List[ast.AST]) -> Set[str]:
    """Names the test bound only to a container it built itself, a display or a comprehension.

    Such a name cannot be None, so ``assert not offenders`` is ``assert offenders == []``.
    """
    built: Set[str] = set()
    other: Set[str] = set()
    plain: Set[int] = set()
    for node in function_nodes:
        target, value = _binding(node)
        if isinstance(target, ast.Name):
            plain.add(id(target))
            (built if isinstance(value, _CONTAINERS) else other).add(target.id)
    for node in function_nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and id(node) not in plain:
            other.add(node.id)
        elif isinstance(node, ast.arg):
            other.add(node.arg)
    return built - other


def _binding(node: ast.AST) -> Tuple[ast.AST | None, ast.AST | None]:
    """(target, value) of a plain one-target assignment, or (None, None) for anything else."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        return node.targets[0], node.value
    if isinstance(node, ast.AnnAssign):
        return node.target, node.value
    return None, None


def _verdict(node: ast.AST, bare: Set[str], modules: Dict[str, str], built: Set[str] | None = None) -> Tuple[str, str]:
    """(strength, form) for one oracle: an assert statement or a mock assertion."""
    if isinstance(node, ast.Call):
        blind = tail_name(node.func) in _BLIND_CALLS and not node.args and not node.keywords
        return (_SCORED, D5) if blind else (_STRONG, "")

    test = node.test if isinstance(node, ast.Assert) else node
    if isinstance(test, ast.Constant):
        return _SCORED, D1
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
        # Only `not` is the emptiness claim: `assert found` on a built list stays D2.
        return (_STRONG, "") if test.operand.id in (built or set()) else (_SCORED, D2)
    if isinstance(test, ast.Name):
        return _SCORED, D2
    if isinstance(test, ast.Call):
        # A call's truthiness is the claim; isinstance alone answers only the type.
        return (_SCORED, D4) if tail_name(test.func) == "isinstance" else (_STRONG, "")
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return _compare_verdict(test, bare, modules)
    return _STRONG, ""


def _tests(tree: ast.Module) -> List[Tuple[Union[ast.FunctionDef, ast.AsyncFunctionDef], List[ast.AST]]]:
    """Each test and its own nodes, in ONE descent."""
    nodes: Dict[int, List[ast.AST]] = {}
    owners: Dict[int, Union[ast.FunctionDef, ast.AsyncFunctionDef]] = {}
    stack: List[Tuple[ast.AST, Union[ast.FunctionDef, ast.AsyncFunctionDef, None]]] = [(tree, None)]
    while stack:
        node, enclosing = stack.pop()
        # isinstance inline, not an `is_test` flag: pyright narrows only a type test.
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
        name = tail_name(node.func)
        if name.startswith("assert_"):
            found.append(node)
        raises = raises or name == "raises"
    # Source order: _tests descends a stack (children reversed); the report names the first weak oracle.
    return sorted(found, key=lambda node: (node.lineno, node.col_offset)), raises


_parse = partial(parse, tag="weak_oracle")


def scan(source: str) -> Tuple[List[Tuple[int, str, str]], List[str]]:
    """(scored findings, soft forms counted)."""
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
        built = _built(nodes)
        verdicts = [_verdict(node, bare, modules, built) for node in found]
        if any(strength == _STRONG for strength, _form in verdicts):
            continue
        forms = [form for strength, form in verdicts if strength == _SCORED]
        if forms:
            scored.append((function.lineno, function.name, forms[0]))
        else:
            counted.extend(form for _strength, form in verdicts)
    return sorted(scored), counted


_read = partial(read_text, tag="weak_oracle", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Weak oracle", "passed": passed, "message": message}]


def _clean_message(counted: List[str]) -> str:
    """The passing message, carrying the soft count without making it a verdict."""
    if not counted:
        return "Every test here asserts something that can fail"
    kinds = len(set(counted))
    shape = "form" if kinds == 1 else "forms"
    return (
        f"Every test here asserts something that can fail "
        f"({len(counted)} soft oracles in {kinds} {shape} are counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for tests whose whole oracle cannot fail."""
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

    # One check: checklist._format_failure shows only the first failed check plus "(+N more)".
    detail = "\n".join(f"{path.name}:{line} {name} — {form} - {CURE}" for line, name, form in scored)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(scored)},
    )
    return _result(False, _one_check(False, detail), 0)
