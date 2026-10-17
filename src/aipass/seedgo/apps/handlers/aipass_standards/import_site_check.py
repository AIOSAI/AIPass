# =================== AIPass ====================
# Name: import_site_check.py
# Description: Import Site Standards Checker Handler
# Version: 1.3.0
# Created: 2026-09-21
# Modified: 2026-10-17
# =============================================

"""
Import Site Standards Checker Handler

Reference: import_site.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import module_constants
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "IMPORT_SITE"
STANDARD_KEY = "import_site"

# The product namespace: every branch imports through `aipass.<branch>...`; any other route is a different defect.
PRODUCT_ROOT = "aipass"

# ClassDef is listed: a class-body import runs at import time but never reaches the module's top-level namespace.
_SCOPES: Tuple[type, ...] = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

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

    Each node is judged once: an import inside a method has both a ClassDef and a FunctionDef ancestor.
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

    An importlib reload counts only inside a function: at module level no test has staged a replacement yet.
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


def _keyed_by_product_constant(node: ast.AST, constants: Dict[str, str]) -> bool:
    """True when a ``sys.modules[NAME]`` target's NAME is a module constant naming aipass.

    ``constants`` is ``module_constants.string_constants``. Only a subscript key is read, nothing wider.
    """
    targets = getattr(node, "targets", [])
    for target in targets:
        if isinstance(target, ast.Subscript) and _is_sys_modules(target.value) and isinstance(target.slice, ast.Name):
            if _root_of(constants.get(target.slice.id)) == PRODUCT_ROOT:
                return True
    return False


def _stubs(tree: ast.Module, path: Path | None) -> List[Tuple[int, str]]:
    """Every sys.modules write or in-function reload that names a product module.

    A key imported from the file's own support module resolves like a local constant.
    """
    found: List[Tuple[int, str]] = []
    constants = module_constants.file_constants(tree, path)

    def walk(node: ast.AST, inside: bool) -> None:
        """Descend, carrying whether a function body has been entered."""
        for child in ast.iter_child_nodes(node):
            mechanism = _stub_mechanism(child, inside)
            if mechanism is not None and (_names_product(child) or _keyed_by_product_constant(child, constants)):
                found.append((getattr(child, "lineno", 0), mechanism))
            walk(child, inside or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))

    walk(tree, False)
    return found


def scan(source: str, path: Path | None = None) -> List[Tuple[int, str, str]]:
    """(line, shape, fix) for every hit in one test file's source, in line order.

    A file that does not parse yields nothing: ruff already convicts the syntax error.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[import_site] Unparseable, nothing scanned: %s", exc)
        return []
    hits = [(ln, f"product import inside a function ({what})", FIX_IMPORT) for ln, what in _deferred_imports(tree)]
    hits += [(ln, f"sys.modules stub ({what})", FIX_STUB) for ln, what in _stubs(tree, path)]
    return sorted(hits)


def _scan_path(path: Path) -> List[Tuple[int, str, str]]:
    """scan() for a file on disk, or [] if it cannot be read."""
    try:
        return scan(path.read_text(encoding="utf-8", errors="ignore"), path)
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
    """Check one test file for product imports away from the top, and for stubs."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    hits = [h for h in _scan_path(path) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, "Every product import is at the top of the file"), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(f"{path.name}:{line} {shape} - {fix}" for line, shape, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
