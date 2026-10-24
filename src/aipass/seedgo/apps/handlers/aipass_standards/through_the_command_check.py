# =================== AIPass ====================
# Name: through_the_command_check.py
# Description: Through The Command Standards Checker Handler
# Version: 1.1.2
# Created: 2026-09-21
# Modified: 2026-10-24
# =============================================

"""
Through The Command Standards Checker Handler

Reference: through_the_command.md
"""

from functools import partial
import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import result

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "THROUGH_THE_COMMAND"
STANDARD_KEY = "through_the_command"

PRODUCT_ROOT = "aipass"

# A helper imported from another test file is the test's own scaffolding, not product.
_TEST_SEGMENTS: frozenset[str] = frozenset({"tests", "conftest"})

GETATTR = "getattr"

FIX = (
    "reach it through the command or a public function; if no route exists, "
    "mail @devpulse with the helper - it is a product question"
)


def _is_private(name: str) -> bool:
    """One leading underscore, and not a dunder."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _is_product_module(dotted: str | None) -> bool:
    """True for an aipass module that is not itself test code."""
    if not dotted:
        return False
    parts = dotted.split(".")
    return parts[0] == PRODUCT_ROOT and not (_TEST_SEGMENTS & set(parts))


def _product_bases(tree: ast.Module) -> Dict[str, str]:
    """Names this file bound to a product module, mapped to what they point at."""
    bases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bases.update(_bases_from_import(node))
        elif isinstance(node, ast.ImportFrom):
            bases.update(_bases_from_import_from(node))
    return bases


def _bases_from_import(node: ast.Import) -> Dict[str, str]:
    """Product names bound by one ``import ...`` statement."""
    return {
        alias.asname or alias.name.split(".")[0]: alias.name for alias in node.names if _is_product_module(alias.name)
    }


def _bases_from_import_from(node: ast.ImportFrom) -> Dict[str, str]:
    """Product names bound by one ``from ... import ...`` statement.

    A private name here is shape (a), reported by ``_private_imports``; binding it
    as a base would count ``_helper.__doc__`` a second time as a reach.
    """
    if node.level or not _is_product_module(node.module):
        return {}
    return {
        alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names if not _is_private(alias.name)
    }


def _private_imports(tree: ast.Module) -> List[Tuple[int, str]]:
    """Every ``from aipass... import _name``, at any scope."""
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        if not _is_product_module(node.module):
            continue
        for alias in node.names:
            if _is_private(alias.name):
                found.append((node.lineno, f"{node.module}.{alias.name}"))
    return found


def _root_name(node: ast.AST) -> Tuple[str, List[str]] | None:
    """Walk an attribute chain back to its root Name, returning (root, path), or None."""
    path: List[str] = []
    while isinstance(node, ast.Attribute):
        path.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return node.id, list(reversed(path))


def _private_reads(tree: ast.Module, bases: Dict[str, str]) -> List[Tuple[int, str]]:
    """Every read of a private attribute on a name bound from a product import.

    Only ``Load`` counts: a store or delete into private state is item 15's shape.
    """
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        read = _getattr_read(node)
        if read is not None:
            node = read
        if not isinstance(node, ast.Attribute) or not _is_private(node.attr):
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        rooted = _root_name(node)
        if rooted is None:
            continue
        root, path = rooted
        if root not in bases:
            continue
        found.append((node.lineno, ".".join([root, *path])))
    return found


def _getattr_read(node: ast.AST) -> ast.Attribute | None:
    """``getattr(m, "_helper")`` as the attribute read it is, or None."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == GETATTR):
        return None
    if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, str):
        return None
    read = ast.Attribute(value=node.args[0], attr=node.args[1].value, ctx=ast.Load())
    return ast.copy_location(read, node)


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, name, fix) for every hit in one test file's source, in line order.

    A file that does not parse yields nothing: ruff already convicts the syntax error.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[through_the_command] Unparseable, nothing scanned: %s", exc)
        return []
    bases = _product_bases(tree)
    hits = [(ln, f"imports the private name {what}", FIX) for ln, what in _private_imports(tree)]
    hits += [(ln, f"reaches the private name {what}", FIX) for ln, what in _private_reads(tree, bases)]
    return sorted(hits)


def _scan_path(path: Path) -> List[Tuple[int, str, str]]:
    """scan() for a file on disk, or [] if it cannot be read."""
    try:
        return scan(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        logger.info("[through_the_command] Cannot read %s: %s", path, exc)
        return []


_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Through the command", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for private product helpers reached directly."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    hits = [h for h in _scan_path(path) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, "Every product reach goes through a public name"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per hit would hide the rest.
    detail = "\n".join(f"{path.name}:{line} {name} - {fix}" for line, name, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
