# =================== AIPass ====================
# Name: import_site_check.py
# Description: Import Site Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""
Import Site Standards Checker Handler

Test template v1, item 8: product imports at the top of the file, never
inside a test.

Not tidiness. An import that happens inside a test happens AFTER the test has
had a chance to replace what it is about to import, and that is the whole
mechanism by which a test can pass against a unit that is not the product. The
readme tests this branch retired on 2026-09-20 are the worked example: source
mutants survived them because the module under test was rebuilt from a stub
inside the test body, so deleting a real `return` changed nothing anyone asked
about.

Two shapes, both convicted:

  * A product import (``aipass...``) inside any function, method or class
    body. Module-level imports are never convicted -- including under a
    module-level ``try``/``except`` or ``if TYPE_CHECKING``, because nothing
    at module level can be preceded by a test's own patching.
  * A write to ``sys.modules`` naming an aipass module, or an
    ``importlib.reload`` / ``importlib.import_module`` of one inside a
    function body. This is the stub-and-reimport mechanism itself, and it
    convicts wherever it sits: a module-level ``sys.modules`` write poisons
    every test in the file rather than one.

Not convicted: a stdlib or third-party import inside a function. Those cannot
fake the unit under test, and asking for them at the top would be tidiness.

Two lanes, exactly as ``router_assert`` and ``oversize_test_file``:

  * ``check_module`` -- APPLIES_TO tests, so only the per-file checklist lane
    runs it, on the write that creates the shape.
  * ``check_branch_info`` -- the standing backlog, UNSCORED. Test files are
    not in the audit's corpus (``_collect_py_files`` walks ``apps/``), so no
    branch's number moves on the day this lands.

One known limit, stated rather than hidden: the aipass module has to be named
in the statement itself. ``key = "aipass.prax"`` followed by
``sys.modules[key] = stub`` is not convicted, because the checker reads one
statement and not the function's dataflow. Measured 2026-09-21, no fleet test
file does this; the shape would be caught the moment one does only by widening
to every sys.modules write, product or not, which would convict a test
stubbing a third-party module it has every right to stub.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "IMPORT_SITE"
STANDARD_KEY = "import_site"

# The product namespace. A single root, because every branch in the fleet
# imports through it -- `from aipass.<branch>.apps...` is the house rule, and
# a test that reaches the product any other way is already a different defect.
PRODUCT_ROOT = "aipass"

# Bodies whose contents run later than module import. ClassDef is in the list
# because a class body inside a test module is still executed at import time --
# but an import there is unreachable to the module's top-level namespace, which
# is the whole point of asking for the import at the top.
_SCOPES: Tuple[type, ...] = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# importlib entry points that re-run a module's code on demand.
_RELOADERS: frozenset[str] = frozenset({"reload", "import_module"})

FIX_IMPORT = "move the import to the top of the file"
FIX_STUB = "import the real module at the top and patch at the edge with monkeypatch"


def _root_of(dotted: str | None) -> str:
    """First segment of a dotted module name, or '' when there is none."""
    return (dotted or "").split(".")[0]


def _is_sys_modules(node: ast.AST) -> bool:
    """True for the expression ``sys.modules``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _names_product(node: ast.AST) -> bool:
    """True when this statement names an aipass module somewhere inside it.

    Reads string constants AND attribute chains, because the two mechanisms
    spell the same module differently: ``sys.modules["aipass.prax"]`` is a
    string, ``importlib.reload(aipass.prax.logger)`` is a chain of names.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if _root_of(child.value) == PRODUCT_ROOT:
                return True
        elif isinstance(child, ast.Name) and child.id == PRODUCT_ROOT:
            return True
    return False


def _deferred_imports(tree: ast.Module) -> List[Tuple[int, str]]:
    """Every product import sitting inside a function or class body, once each.

    Each node is judged once. An import inside a method has both a ClassDef
    and a FunctionDef ancestor, so walking every scope separately and
    collecting its imports counts that one line twice -- measured on the fleet
    the difference was 9,174 reported against 5,175 real.
    """
    found: List[Tuple[int, str]] = []

    def walk(node: ast.AST, inside: bool) -> None:
        """Descend, carrying whether a function or class body has been entered."""
        for child in ast.iter_child_nodes(node):
            if inside and isinstance(child, ast.Import):
                for alias in child.names:
                    if _root_of(alias.name) == PRODUCT_ROOT:
                        found.append((child.lineno, f"import {alias.name}"))
            elif inside and isinstance(child, ast.ImportFrom):
                if _root_of(child.module) == PRODUCT_ROOT:
                    found.append((child.lineno, f"from {child.module} import ..."))
            walk(child, inside or isinstance(child, _SCOPES))

    walk(tree, False)
    return found


def _stub_mechanism(node: ast.AST, inside_function: bool) -> str | None:
    """Name the stub-and-reimport mechanism this node is, or None.

    ``sys.modules`` writes count wherever they sit; an importlib reload only
    counts inside a function body, because at module level it runs before any
    test could have staged a replacement for it to pick up.
    """
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Subscript) and _is_sys_modules(t.value) for t in node.targets
    ):
        return "sys.modules[...] = ..."
    if isinstance(node, ast.Delete) and any(
        isinstance(t, ast.Subscript) and _is_sys_modules(t.value) for t in node.targets
    ):
        return "del sys.modules[...]"
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    attr = node.func.attr
    if attr == "pop" and _is_sys_modules(node.func.value):
        return "sys.modules.pop(...)"
    if attr == "dict" and node.args and _is_sys_modules(node.args[0]):
        return "patch.dict(sys.modules, ...)"
    if attr in ("setitem", "delitem") and node.args and _is_sys_modules(node.args[0]):
        return f"monkeypatch.{attr}(sys.modules, ...)"
    if attr in _RELOADERS and inside_function:
        return f"importlib.{attr}(...)"
    return None


def _stubs(tree: ast.Module) -> List[Tuple[int, str]]:
    """Every sys.modules write or in-function reload that names a product module."""
    found: List[Tuple[int, str]] = []

    def walk(node: ast.AST, inside: bool) -> None:
        """Descend, carrying whether a function body has been entered."""
        for child in ast.iter_child_nodes(node):
            mechanism = _stub_mechanism(child, inside)
            if mechanism is not None and _names_product(child):
                found.append((getattr(child, "lineno", 0), mechanism))
            walk(child, inside or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))

    walk(tree, False)
    return found


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, shape, fix) for every hit in one test file's source, in line order.

    A file that does not parse yields nothing: ruff already convicts the
    syntax error, and guessing at the import sites of a file Python cannot
    read would put a line number on a statement that may not exist.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[import_site] Unparseable, nothing scanned: %s", exc)
        return []
    hits = [(ln, f"product import inside a function ({what})", FIX_IMPORT) for ln, what in _deferred_imports(tree)]
    hits += [(ln, f"sys.modules stub ({what})", FIX_STUB) for ln, what in _stubs(tree)]
    return sorted(hits)


def _scan_path(path: Path) -> List[Tuple[int, str, str]]:
    """scan() for a file on disk, or [] if it cannot be read."""
    try:
        return scan(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        logger.info("[import_site] Cannot read %s: %s", path, exc)
        return []


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Import site", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for product imports away from the top, and for stubs.

    Args:
        module_path: Path to the test file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    hits = [h for h in _scan_path(path) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, "Every product import is at the top of the file"), 100)

    # One line per hit, all inside ONE check rather than one check each. The
    # cure is per-line and an author told "17 violations" has to re-derive the
    # list this checker already holds -- but checklist._format_failure prints
    # the FIRST failed check and appends "(+N more)", so N checks would show
    # one hit and hide the rest. A single message carries them all through.
    detail = "\n".join(f"{path.name}:{line} {shape} - {fix}" for line, shape, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)


def check_branch_info(branch_path: str) -> List[str]:
    """The standing backlog, reported with no score attached.

    The audit's corpus is ``apps/``, so nothing under ``tests/`` can move a
    branch's number through the scoring lane. Both shapes are counted
    separately because they are cured differently: one is a line move, the
    other is a rewrite of how the test reaches its unit.
    """
    tests_dir = Path(branch_path) / "tests"
    if not tests_dir.is_dir():
        return []
    imports, stubs, files = 0, 0, 0
    for test_file in sorted(tests_dir.rglob("*.py")):
        if not (test_file.name.startswith("test_") or test_file.name == "conftest.py"):
            continue
        # Retired code is not lintable and the per-file lane already refuses
        # it through applies_to_file(); without the same guard the backlog
        # would count hits the lane can never convict.
        if applicability.is_retired_path(str(test_file)):
            continue
        hits = _scan_path(test_file)
        if not hits:
            continue
        files += 1
        imports += sum(1 for _ln, shape, _fix in hits if shape.startswith("product import"))
        stubs += sum(1 for _ln, shape, _fix in hits if shape.startswith("sys.modules"))
    if not (imports or stubs):
        return []
    return [
        f"import_site backlog: {imports} deferred product import(s) and {stubs} sys.modules stub(s) "
        f"across {files} test file(s) (unscored - convicted on the next write of the file)"
    ]
