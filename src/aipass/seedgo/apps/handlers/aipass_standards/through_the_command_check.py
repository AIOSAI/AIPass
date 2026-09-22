# =================== AIPass ====================
# Name: through_the_command_check.py
# Description: Through The Command Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""
Through The Command Standards Checker Handler

Test template v1, item 10: a test reaches behaviour the way a user does --
through the module's commands and its public functions. An underscore helper
is never called directly by a test.

A private helper is not a contract. It is the shape the author happened to cut
the work into this week, and a test bolted to it pins that shape rather than
the behaviour: rename the helper and a green suite goes red without a single
user-visible change; reroute the command past the helper and the suite stays
green while the product breaks. Reaching through the command tests what is
promised. If a helper's logic cannot be reached through any command at all,
that is a question about the product -- an unreachable branch -- and not a
licence to test it directly.

Two shapes, both convicted:

  * An import of an underscore name from a product module, at any scope:
    ``from aipass.x.y import _helper``.
  * A call or attribute READ of an underscore name on a base this file bound
    from a product import: ``m._helper(...)`` or ``m._TABLE`` where ``m`` came
    from ``import aipass.a.b as m`` or ``from aipass.a import b``.

The base is resolved from the file's own import bindings and nothing deeper.
A name this file never imported from the product is not the product.

Never convicted, each for its own reason:

  * Dunder names (``__init__``, ``__version__``, ``__all__``). Language
    surface, not a private helper.
  * Underscore helpers the test file or its conftest defines itself. They are
    the test's own scaffolding, not the product -- which is also why a product
    module under ``tests/`` (``aipass.x.tests.conftest``) is not treated as a
    product module here.
  * An attribute read on a value RETURNED by a product call
    (``result._x``). That is dataflow, and this checker does not follow it: it
    resolves a base to an import binding or it declines.
  * A WRITE to a private name -- ``m._cache = {}``, ``monkeypatch.setattr(m,
    "_cache", ...)``, or a ``patch("aipass.x._helper")`` target string. Those
    are item 15, mock only at the edge, and they are a different cure. 152
    direct writes and 2,113 patch-target strings were measured on the fleet
    2026-09-21 and deliberately left to that rule.

One known limit, measured rather than assumed: ``import aipass.x._private as
m`` -- the plain-import form of shape (a) -- is not convicted, because item 10
names the ``from`` form. No fleet test file uses it today (0 of 591 checked
2026-09-21); the day one does, this is where it goes.

Two lanes, exactly as ``router_assert``, ``oversize_test_file`` and
``import_site``:

  * ``check_module`` -- APPLIES_TO tests, so only the per-file checklist lane
    runs it, on the write that creates the shape.
  * ``check_branch_info`` -- the standing backlog, UNSCORED. Test files are
    not in the audit's corpus (``_collect_py_files`` walks ``apps/``), so no
    branch's number moves on the day this lands.
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

STANDARD = "THROUGH_THE_COMMAND"
STANDARD_KEY = "through_the_command"

# The product namespace. A single root, because every branch in the fleet
# imports through it -- `from aipass.<branch>.apps...` is the house rule.
PRODUCT_ROOT = "aipass"

# Path segments that mark a module as test scaffolding rather than product.
# A test importing a helper from another test file is sharing its own fixtures,
# which item 10 says nothing about.
_TEST_SEGMENTS: frozenset[str] = frozenset({"tests", "conftest"})

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
    """Names this file bound to a product module, mapped to what they point at.

    Both import forms bind a name that later carries attribute access:
    ``import aipass.a.b as m`` binds ``m``; ``from aipass.a import b`` binds
    ``b``; a bare ``import aipass.a.b`` binds only ``aipass``, so the chain
    ``aipass.a.b._x`` is rooted there.
    """
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

    A private name imported here is shape (a), reported by ``_private_imports``
    and never bound as a base -- otherwise ``_helper.__doc__`` would be counted
    a second time as a reach.
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
    """Walk an attribute chain back to its root Name, returning (root, path).

    ``a.b.c`` yields ``("a", ["b", "c"])``. Anything not rooted in a plain
    name -- a subscript, a call result, a literal -- yields None, which is the
    dataflow this checker declines to follow.
    """
    path: List[str] = []
    while isinstance(node, ast.Attribute):
        path.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return node.id, list(reversed(path))


def _private_reads(tree: ast.Module, bases: Dict[str, str]) -> List[Tuple[int, str]]:
    """Every read of a private attribute on a name bound from a product import.

    Only ``Load`` context counts. A store or a delete is a test writing into
    the product's private state, which is item 15's shape and item 15's cure.
    """
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
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


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, name, fix) for every hit in one test file's source, in line order.

    A file that does not parse yields nothing: ruff already convicts the
    syntax error, and guessing at the call sites of a file Python cannot read
    would put a line number on a statement that may not exist.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
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


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Through the command", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for private product helpers reached directly.

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
        return _result(True, _one_check(True, "Every product reach goes through a public name"), 100)

    # One line per hit, all inside ONE check rather than one check each --
    # checklist._format_failure prints the FIRST failed check and appends
    # "(+N more)", so N checks would show one hit and hide the rest.
    detail = "\n".join(f"{path.name}:{line} {name} - {fix}" for line, name, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)


def check_branch_info(branch_path: str) -> List[str]:
    """The standing backlog, reported with no score attached.

    The audit's corpus is ``apps/``, so nothing under ``tests/`` can move a
    branch's number through the scoring lane. The two shapes are counted
    separately because they are cured differently: one is an import to delete
    once the call sites move, the other is a rewrite of how the test reaches
    its unit.
    """
    tests_dir = Path(branch_path) / "tests"
    if not tests_dir.is_dir():
        return []
    imports, reaches, files = 0, 0, 0
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
        imports += sum(1 for _ln, name, _fix in hits if name.startswith("imports"))
        reaches += sum(1 for _ln, name, _fix in hits if name.startswith("reaches"))
    if not (imports or reaches):
        return []
    return [
        f"through_the_command backlog: {imports} private import(s) and {reaches} private helper reach(es) "
        f"across {files} test file(s) (unscored - convicted on the next write of the file)"
    ]
