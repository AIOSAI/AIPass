# =================== AIPass ====================
# Name: conftest_fixtures_check.py
# Description: Conftest Fixtures Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Conftest Fixtures Standards Checker Handler

Test template v1, item 20: a branch's ``tests/conftest.py`` pins the console
width once, session scope, on every console the product exports, and resets the
command state after every test.

THE UNIT IS THE BRANCH'S CONFTEST, NOT THE TEST FILE. Every other file under
``tests/`` passes silently -- these two fixtures belong in exactly one place
(item 16, never copied per file), so a rule that read them anywhere else would
convict 563 files for not being the conftest.

TWO SUB-RULES, BOTH ON ONE CHECK so the count cannot hide one behind the other:

  C1  A SESSION-SCOPE AUTOUSE FIXTURE PINS ``.width``, on the consoles the
      PRODUCT exports. Rich sizes an unpinned console on every print: 80 on
      POSIX and 79 on Windows under pytest's capture, the terminal's width
      under ``-s``, ``COLUMNS`` when exported. The template measured 4 of the
      trial's 31 tests flipping at width 40, none with the pin.
  C2  AN AUTOUSE FIXTURE CALLS ``display.reset_command_state()`` AFTER the
      test -- ``yield`` then reset. ``error()`` marks the process failed, and a
      test must not hand that flag to the next one. This is item 18 wearing a
      conftest's clothes.

THE PIN HAS TO LAND ON THE PRODUCT'S CONSOLES. A ``Console(width=200)`` the
fixture builds itself is a console the product never prints to, so it pins
nothing: C1 is not satisfied. The name the pin is written through has to come
from an ``aipass.cli`` import -- ``display.CONSOLE``, ``display.err_console``,
or the ``console`` / ``err_console`` those modules export -- or be the loop
variable of a ``for`` over them, which is the template's own spelling.

CHECK FIRST, measured 2026-09-22 over all 18 branch conftests:

  * ALL 18 BRANCHES HAVE A tests/conftest.py. The checker never convicts a
    branch for a missing one -- it cannot see a file that is not there -- and
    today there is no branch it would have to.
  * ONE pins width: seedgo, through ``console.width = 200`` over
    ``(display.CONSOLE, display.err_console)``. TWO reset command state:
    seedgo and commons.
  * @cli's conftest carries ``Console(width=..., force_terminal=...)`` in its
    ``make_capture_console`` helper. That is a console the TEST prints to, not
    a pin on the product's, so C1 is not satisfied there and the checker says
    so -- the same install-site restriction ``mock_console`` took from ARM A.
  * EVERY BRANCH HAS A CONSOLE, and it is the same one. 292 import sites
    across the 18 branches pull ``console`` / ``err_console`` from
    ``aipass.cli.apps.modules``, where ``console is CONSOLE``. C1 works
    fleet-wide because it mutates the shared Console INSTANCE; a name is
    irrelevant to it.

THE ONE TEMPLATE QUESTION FOR THE OWNER, stated rather than softened. 48 other
``Console()`` builds exist in the fleet, and 47 of them are inside a
``try``/``except ImportError`` fallback that fires only when ``aipass.cli``
cannot be imported -- never in the suite. The 48th is real and it is SEEDGO'S
OWN: ``apps/handlers/diagnostics/diagnostics_check.py:33`` binds a module-level
``console = Console()`` that C1's two names do not reach. The template's C1
cannot pin it. That is a question about the template (should C1 name every
module-level console a branch builds?) and not a conviction to soften, so the
checker still asks only for the two names the page names.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "CONFTEST_FIXTURES"
STANDARD_KEY = "conftest_fixtures"

#: The only filename this rule has anything to say about.
CONFTEST = "conftest.py"

#: Names that, imported from aipass.cli, mean a console the product prints to.
_CONSOLE_NAMES: frozenset[str] = frozenset({"console", "CONSOLE", "err_console", "display"})

#: The call that clears error()'s process flag.
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


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _base_name(node: ast.expr) -> str:
    """The leftmost name of a dotted expression -- ``display`` for ``display.CONSOLE``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _product_consoles(tree: ast.Module) -> Set[str]:
    """Names this file binds to a console the PRODUCT exports.

    An ``aipass.cli`` import and nothing else. A ``Console()`` the conftest
    builds is a console the product never prints to, and pinning it pins
    nothing -- the same install-site restriction ``mock_console`` took from
    ARM A, where only a thing HANDED to the product counts as in use.
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

    ``for console in (display.CONSOLE, display.err_console):`` is the template's
    own spelling, so the name being pinned is the loop variable and not the
    import. Every element of the iterable has to be a product console -- a loop
    over a list holding one of each would otherwise launder a locally built one.
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
    resets = [n.lineno for n in ast.walk(function) if isinstance(n, ast.Call) and _tail_name(n.func) == _RESET]
    return any(reset > min(yields) for reset in resets)


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[conftest_fixtures] Unparseable, nothing scanned: %s", exc)
        return None


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


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[conftest_fixtures] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Conftest fixtures", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch's tests/conftest.py for item 20's two fixtures.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not is_the_unit(module_path):
        # Every other file in tests/ is not this rule's business. Item 16 puts
        # these fixtures in one place; asking 563 files for them would be noise.
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

    # Both sub-rules on ONE check: checklist._format_failure prints the first
    # failed check and appends "(+N more)", so two checks would show C1 and
    # hide C2 behind a count.
    detail = "\n".join(f"{path.name}: {rule} - {cure}" for rule, cure in missing)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "missing": len(missing)},
    )
    return _result(False, _one_check(False, detail), 0)
