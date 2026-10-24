# =================== AIPass ====================
# Name: conftest_fixtures_check.py
# Description: Conftest Fixtures Standards Checker Handler
# Version: 1.0.1
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""Conftest Fixtures Standards Checker Handler

Reference: conftest_fixtures.md
"""

from functools import partial
import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result, tail_name

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "CONFTEST_FIXTURES"
STANDARD_KEY = "conftest_fixtures"

CONFTEST = "conftest.py"

#: Names that, imported from aipass.cli, mean a console the product prints to.
_CONSOLE_NAMES: frozenset[str] = frozenset({"console", "CONSOLE", "err_console", "display"})

_RESET = "reset_command_state"

C1 = "C1 no session-scope autouse fixture pins .width on the product's consoles"
C2 = "C2 no autouse fixture calls display.reset_command_state() after the test"

CURES: Dict[str, str] = {
    C1: (
        '@pytest.fixture(autouse=True, scope="session") that sets console.width '
        "on display.CONSOLE and display.err_console"
    ),
    C2: "@pytest.fixture(autouse=True) that yields, then calls display.reset_command_state()",
}


def _base_name(node: ast.expr) -> str:
    """The leftmost name of a dotted expression -- ``display`` for ``display.CONSOLE``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _product_consoles(tree: ast.Module) -> Set[str]:
    """Names this file binds to a console the PRODUCT exports.

    An ``aipass.cli`` import and nothing else: a ``Console()`` the conftest builds is a
    console the product never prints to, and pinning it pins nothing.
    """
    names: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("aipass.cli"):
            continue
        for alias in node.names:
            if alias.name in _CONSOLE_NAMES:
                names.add(alias.asname or alias.name)
    return names


def _fixture_decorators(function: ast.AST) -> List[str]:
    """The unparsed decorators of a function, or [] when it is not one."""
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    return [ast.unparse(d) for d in function.decorator_list]


def _is_autouse_fixture(decorators: List[str]) -> bool:
    """An autouse pytest fixture, by the only spelling the template uses."""
    return any("fixture" in d and "autouse=True" in d for d in decorators)


def _is_session_scoped(decorators: List[str]) -> bool:
    """Session scope, in either quote style."""
    return any('scope="session"' in d or "scope='session'" in d for d in decorators)


def _loop_aliases(function: ast.AST, product: Set[str]) -> Set[str]:
    """Loop variables bound to the product's consoles.

    The template's spelling pins through a loop variable; every element of the iterable
    has to be a product console, or a mixed list would launder a locally built one.
    """
    aliases: Set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        elements = node.iter.elts if isinstance(node.iter, (ast.Tuple, ast.List)) else [node.iter]
        if elements and all(_base_name(e) in product for e in elements):
            aliases.add(node.target.id)
    return aliases


def _pins_product_width(function: ast.AST, product: Set[str]) -> bool:
    """Whether this fixture assigns ``.width`` on a console the product exports."""
    reachable = product | _loop_aliases(function, product)
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == "width":
                if _base_name(target) in reachable:
                    return True
    return False


def _resets_after_the_test(function: ast.AST) -> bool:
    """Whether this fixture calls reset_command_state AFTER its yield.

    Order is the whole point: a reset before the yield clears the flag the
    PREVIOUS test set and then hands this test's flag straight on.
    """
    yields = [n.lineno for n in ast.walk(function) if isinstance(n, (ast.Yield, ast.YieldFrom))]
    if not yields:
        return False
    resets = [n.lineno for n in ast.walk(function) if isinstance(n, ast.Call) and tail_name(n.func) == _RESET]
    return any(reset > min(yields) for reset in resets)


_parse = partial(parse, tag="conftest_fixtures")


def scan(source: str) -> List[Tuple[str, str]]:
    """(sub-rule, cure) for each of item 20's two fixtures this conftest lacks."""
    tree = _parse(source)
    if tree is None:
        return []

    product = _product_consoles(tree)
    pinned = False
    resets = False
    for function in ast.walk(tree):
        decorators = _fixture_decorators(function)
        if not _is_autouse_fixture(decorators):
            continue
        if _is_session_scoped(decorators) and _pins_product_width(function, product):
            pinned = True
        if _resets_after_the_test(function):
            resets = True

    missing: List[Tuple[str, str]] = []
    if not pinned:
        missing.append((C1, CURES[C1]))
    if not resets:
        missing.append((C2, CURES[C2]))
    return missing


def is_the_unit(module_path: str) -> bool:
    """Whether this file is the branch conftest, which is all this rule judges."""
    return Path(module_path).name == CONFTEST


_read = partial(read_text, tag="conftest_fixtures", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Conftest fixtures", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch's tests/conftest.py for item 20's two fixtures."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not is_the_unit(module_path):
        # Item 16 puts these fixtures in one place: no other file in tests/ is asked.
        return _result(True, _one_check(True, "Not the branch conftest — item 20 is not this file's business"), 100)

    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    missing = scan(source)
    if not missing:
        clean = "Width is pinned once and the command state is reset after every test"
        return _result(True, _one_check(True, clean), 100)

    # Both sub-rules on ONE check: _format_failure's "(+N more)" would hide C2 behind a count.
    detail = "\n".join(f"{path.name}: {rule} - {cure}" for rule, cure in missing)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "missing": len(missing)},
    )
    return _result(False, _one_check(False, detail), 0)
