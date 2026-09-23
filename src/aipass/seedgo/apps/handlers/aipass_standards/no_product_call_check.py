# =================== AIPass ====================
# Name: no_product_call_check.py
# Description: No Product Call Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
No Product Call Standards Checker Handler

Crack class A from the 2026-09-22 eyes-on review of @backup's tests: a
``def test_*`` that never reaches the product. It runs, it asserts, it is
green -- and no edit anywhere in ``aipass/`` can make it red. The reviewers
called these LIBRARY tests, because what they usually pin is a third party's
behaviour: ``pathspec`` matching a glob, ``StringIO`` returning what was
written to it, ``capsys`` capturing a ``print``.

Ten template checkers passed every one of the 107 tests that carry a finding.
Those checkers measure SHAPE. This one measures whether the test is pointed at
anything.

THE RULE, and it is a REACHABILITY rule, not a call-site rule. A test is
convicted when NOTHING in its reachable text names the product. Reachable
means the test's own body, its decorators, every same-file helper it calls,
and every fixture it requests. Naming the product means any of:

  * a name bound by an ``aipass.*`` import;
  * a module-level constant whose value reaches one of those (fixed point) --
    ``SIMPLE_MODULES = [snapshot, versioned]`` is how a parametrized test
    reaches ``mod.handle_command``, and the import is three screens up;
  * a dotted string starting ``aipass.`` -- ``importlib.import_module`` and
    ``mock.patch`` both take the product by name, not by binding;
  * a multi-line string mentioning ``aipass`` -- a probe source a subprocess
    runs is product code, written down;
  * a path computed from ``__file__`` -- it points into the repo tree, and a
    test that reads the guard file's text is testing the guard.

TWO ACQUITTALS THAT ARE NOT ABOUT THE PRODUCT AT ALL:

  * A CALL INTO THE FILE'S OWN APPARATUS -- a function defined in this file,
    or a fixture defined in the branch conftest. A negative control that feeds
    a synthetic source to the file's own detector is a meta-test, not a
    library test, and @backup has nine of them. The class the review found is
    "this test is pointed at nothing"; a control for the file's own apparatus
    IS pointed at something.
  * A METHOD OF A CLASS WHOSE OWN BODY REACHES THE PRODUCT. A
    ``unittest.TestCase`` method reaches it through ``self.conn``, which
    ``setUp`` built and the test body never mentions.

CHECK FIRST, measured 2026-09-22 over the fleet's 559 test files:

  * 23 files convicted, 82 hits, 7.9s. Top three: @prax 5 files, @commons 3,
    @memory 3. The worst single file is @commons' ``test_commons.py`` at 29 --
    29 methods that execute raw SQL against a sqlite connection and read the
    row back, with no commons code anywhere on the path.
  * AGAINST THE REVIEWERS' GROUND TRUTH IN @backup -- the nine reports name
    12 LIBRARY rows, and this checker convicts all 12 and misses none:
    ``test_ignore_pathspec.py`` 46, 53, 59, 70, 77, 88, 99, 106, 117, 124 and
    ``test_cli_routing.py`` 581, 587.
  * It convicts two more there, ``test_ignore_pathspec.py`` 135 and 142, which
    the reviewers marked DUPLICATE. They are library tests as well --
    ``pathspec.PathSpec.from_lines`` with no backup symbol on the path -- so
    this is a second true reading of the same two rows, not a false one.
  * NO OTHER FILE IN @backup IS TOUCHED. Eight of the nine reviewed files pass
    clean.

FOUR CUTS, AND THE NUMBER MOVED BY 70x. A call-site rule convicted 295 files
and 5,807 hits, and nearly all of it was false. Parametrize argvalues, a probe
source handed to a subprocess, a dotted module path built in an f-string, and
a ``setUp`` that builds the world are four different ways to reach the product
without a call site the checker can see. Every acquittal above is one of them,
found by reading what an earlier cut convicted -- not by tuning to a number.
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

STANDARD = "NO_PRODUCT_CALL"
STANDARD_KEY = "no_product_call"

#: The product's import root. Everything under it is the thing under test.
PRODUCT = "aipass"

#: The one filename that carries a branch's shared apparatus.
CONFTEST = "conftest.py"

#: Prefix that makes a function a test, which is the only unit this rule judges.
TEST_PREFIX = "test_"

CURE = "call the product, or delete the test and let the library test itself"

_FUNCTIONS: Tuple[type, ...] = (ast.FunctionDef, ast.AsyncFunctionDef)


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _base_name(node: ast.expr) -> str:
    """The leftmost name of a dotted expression -- ``mod`` for ``mod.a.b``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _product_imports(tree: ast.Module) -> Set[str]:
    """Names this file binds from an ``aipass.*`` import."""
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == PRODUCT:
                    names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == PRODUCT:
            names |= {alias.asname or alias.name for alias in node.names}
    return names


def _names_the_product(text: str) -> bool:
    """Whether a string literal addresses the product by name.

    ``importlib.import_module`` and ``mock.patch`` both take it dotted; a
    multi-line literal is a probe source, which is product code written down.
    """
    if text == PRODUCT or text.startswith(PRODUCT + "."):
        return True
    return "\n" in text and PRODUCT in text


def _names_node(node: ast.AST, bound: Set[str]) -> bool:
    """Whether ONE node names the product. The per-node half of the rule."""
    if isinstance(node, ast.Name):
        return node.id in bound or node.id == "__file__"
    if isinstance(node, ast.Attribute):
        return _base_name(node) in bound
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _names_the_product(node.value)
    return False


def _names_product(node: ast.AST, bound: Set[str]) -> bool:
    """Whether an expression names the product anywhere inside it."""
    return any(_names_node(child, bound) for child in ast.walk(node))


def _product_bound(tree: ast.Module) -> Set[str]:
    """Module-level names that reach the product, to a fixed point.

    ``SIMPLE_MODULES = [snapshot, versioned]`` at the top of a file is what a
    ``@pytest.mark.parametrize("mod", SIMPLE_MODULES)`` test calls through.
    One pass would credit that; two levels of indirection need the loop.
    """
    bound = _product_imports(tree)
    assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]
    changed = True
    while changed:
        changed = False
        for node in assignments:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names or node.value is None or all(n in bound for n in names):
                continue
            if _names_product(node.value, bound):
                bound.update(names)
                changed = True
    return bound


def _functions(tree: ast.Module) -> Dict[str, Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    """Every function defined anywhere in the file, by name."""
    return {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _requested(function: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Set[str]:
    """The fixture names a test asks for in its signature."""
    return {arg.arg for arg in list(function.args.args) + list(function.args.kwonlyargs)}


def _reaches(
    function: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    bound: Set[str],
    local: Dict[str, Union[ast.FunctionDef, ast.AsyncFunctionDef]],
    shared: Set[str],
    seen: Set[int],
) -> bool:
    """Whether anything reachable from this function names the product.

    ``seen`` closes the recursion over mutually recursive helpers; without it
    a helper pair in @hooks' conftest recurses until the interpreter stops.
    """
    if id(function) in seen:
        return False
    seen.add(id(function))

    if any(_names_product(d, bound) for d in function.decorator_list):
        return True
    if any(_names_product(stmt, bound) for stmt in function.body):
        return True

    for node in ast.walk(function):
        # A call into the file's own apparatus, or the branch's: a control for
        # an in-file detector is a meta-test, not a test pointed at nothing.
        if isinstance(node, ast.Call) and _tail_name(node.func) in local:
            return True
    for name in _requested(function):
        if name in local:
            return True
        if name in shared:
            return True
    return False


def _acquitted_by_class(tree: ast.Module, bound: Set[str]) -> Set[int]:
    """Node ids of methods defined in a class whose own body reaches the product.

    A ``unittest.TestCase`` method reaches the product through ``self.conn``,
    which ``setUp`` built and the test body never mentions. The class is the
    apparatus there, exactly as the module is for a pytest fixture, so a
    method of a reaching class is acquitted through its siblings. @commons'
    ``test_commons.py`` was 67 hits before the class was consulted and is 29
    after -- and those 29 are real, raw SQL against a sqlite connection with
    no commons code on the path at all.

    ONE DESCENT, carrying the enclosing class down. A walk per class re-walks
    every node once for each class above it, which cost 3.6s over the fleet.
    """
    nodes: Dict[int, List[ast.AST]] = {}
    methods: Dict[int, Set[int]] = {}
    classes: Dict[int, ast.ClassDef] = {}
    stack: List[Tuple[ast.AST, ast.ClassDef | None]] = [(tree, None)]
    while stack:
        node, enclosing = stack.pop()
        if enclosing is None and isinstance(node, ast.ClassDef):
            enclosing = node
            nodes[id(node)] = []
            methods[id(node)] = set()
            classes[id(node)] = node
        if enclosing is not None:
            nodes[id(enclosing)].append(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[id(enclosing)].add(id(node))
        for child in ast.iter_child_nodes(node):
            stack.append((child, enclosing))

    acquitted: Set[int] = set()
    for key, owned in nodes.items():
        if any(_names_node(node, bound) for node in owned):
            acquitted |= methods[key]
    return acquitted


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[no_product_call] Unparseable, nothing scanned: %s", exc)
        return None


@lru_cache(maxsize=64)
def shared_fixtures(conftest_path: str) -> frozenset[str]:
    """Every name the branch conftest defines, cached per directory.

    Read rather than inferred: a test that requests ``tmp_repo`` reaches
    whatever that fixture reaches, and one parse per test directory is the
    whole cost of not guessing.
    """
    path = Path(conftest_path)
    if not path.is_file():
        return frozenset()
    source = _read(path)
    if source is None:
        return frozenset()
    tree = _parse(source)
    return frozenset(_functions(tree)) if tree is not None else frozenset()


def scan(source: str, shared: frozenset[str] = frozenset()) -> List[Tuple[int, str]]:
    """(line, test name) for each test in this file that reaches no product code."""
    tree = _parse(source)
    if tree is None:
        return []

    bound = _product_bound(tree)
    local = _functions(tree)
    by_class = _acquitted_by_class(tree, bound)
    findings: List[Tuple[int, str]] = []
    for name, node in local.items():
        if not name.startswith(TEST_PREFIX) or id(node) in by_class:
            continue
        if not _reaches(node, bound, local, set(shared), set()):
            findings.append((node.lineno, name))
    return sorted(findings)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[no_product_call] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "No product call", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for tests that never reach the product.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if path.name == CONFTEST:
        # The conftest holds no tests. Judging it would be judging the
        # apparatus the tests are acquitted through.
        return _result(True, _one_check(True, "Not a test file — the conftest carries no tests"), 100)

    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    findings = scan(source, shared_fixtures(str(path.parent / CONFTEST)))
    if not findings:
        return _result(True, _one_check(True, "Every test here reaches the product"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per test would show the first
    # and hide the rest behind a count.
    detail = "\n".join(f"{path.name}:{line} {name} reaches no aipass code - {CURE}" for line, name in findings)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
