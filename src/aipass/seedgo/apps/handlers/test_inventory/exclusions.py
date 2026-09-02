# =================== AIPass ====================
# Name: exclusions.py
# Description: which collected-looking test files pytest actually refuses to run
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
TESTS THAT EXIST AND NEVER RUN, which is an inventory finding, not a rounding
error.

A file-glob walk finds 19,413 test functions on this fleet; pytest collects
19,004 of them. The 409-function gap is not noise and it is not a bug in
either count - it is two deliberate exclusion mechanisms, and a governance
report that silently dropped those rows would be hiding the single cheapest
finding it has: 409 test functions that somebody still maintains and nobody
ever runs.

TWO MECHANISMS, both readable statically:

  CONFTEST_IGNORE     a `conftest.py` on the path declares `collect_ignore_glob`
                      or `collect_ignore`. pytest resolves each pattern against
                      the CONFTEST'S OWN directory and fnmatches the absolute
                      path, so the resolution is reproduced here rather than
                      approximated by a basename match.

  MODULE_LEVEL_SKIP   the module body calls `pytest.skip(...)` at statement
                      level. The file is collected and then abandoned; every
                      function in it is a row that costs maintenance and proves
                      nothing.

  CONDITIONAL_SKIP    the module body calls `pytest.importorskip(...)`. Whether
                      these run is a property of the HOST, not of the file, and
                      no static reading can settle it - so they get their own
                      status instead of being folded into either answer. Split
                      out after a measured miss: this fleet's
                      `api/tests/test_bluesky_driver.py` importorskips `atproto`,
                      which IS installed here, so calling it skipped would have
                      under-counted 12 running tests on the box doing the count.

WHAT THIS CANNOT SEE, and says so rather than guessing: a `collect_ignore_glob`
built by a loop or a function call, a `pytest_collection_modifyitems` hook, a
`skipif` whose condition is true on the running host, and any `-k`/`-m`
selection. Every one of those makes the inventory count MORE tests as running
than really do, so the bias is stated: this module UNDER-reports exclusion.
"""

import ast
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from aipass.prax import logger

#: Why a file that matched the collection globs is not collected anyway.
STATUS_COLLECTED = "COLLECTED"
STATUS_CONFTEST_IGNORE = "IGNORED_BY_CONFTEST"
STATUS_MODULE_SKIP = "MODULE_LEVEL_SKIP"
STATUS_CONDITIONAL_SKIP = "CONDITIONAL_SKIP"

#: Statuses under which a test function does run on a host that has the
#: optional dependencies. CONDITIONAL_SKIP is in here because the alternative
#: is asserting an absence this module cannot see.
RUNNING_STATUSES: frozenset = frozenset({STATUS_COLLECTED, STATUS_CONDITIONAL_SKIP})

#: Module-level calls that abandon a whole file, mapped to what that means.
SKIP_CALLS: dict = {"skip": STATUS_MODULE_SKIP, "importorskip": STATUS_CONDITIONAL_SKIP}

#: The conftest globals pytest reads to exclude paths.
IGNORE_GLOBALS: tuple = ("collect_ignore_glob", "collect_ignore")


def classify(root: Path, relpaths: Sequence[str], norecursedirs: Sequence[str]) -> Dict[str, str]:
    """The collection status of every test file, keyed by relative path."""
    ignores = _conftest_ignores(root, norecursedirs)
    statuses: Dict[str, str] = {}

    for relpath in relpaths:
        path = root / relpath
        if _ignored_by_conftest(path, ignores):
            statuses[relpath] = STATUS_CONFTEST_IGNORE
        else:
            statuses[relpath] = _skipped_at_module_level(path) or STATUS_COLLECTED

    return statuses


# =============================================================================
# CONFTEST IGNORES
# =============================================================================


def _conftest_ignores(root: Path, norecursedirs: Sequence[str]) -> List[Tuple[Path, str]]:
    """Every (conftest directory, absolute glob) pair declared in the tree."""
    pairs: List[Tuple[Path, str]] = []

    for conftest in sorted(root.rglob("conftest.py")):
        if _pruned(conftest, root, norecursedirs):
            continue
        for pattern in _patterns_in(conftest):
            pairs.append((conftest.parent, str(conftest.parent / pattern)))

    return pairs


def _patterns_in(conftest: Path) -> List[str]:
    """The literal ignore patterns a conftest declares.

    Only literals are resolved - a pattern list built by a loop or a call is
    invisible here. That miss is one-directional: an unresolved pattern means
    the file it would have excluded is counted as RUNNING, so the inventory
    over-states how much of the suite executes and never under-states it.
    """
    tree = _parse(conftest)
    if tree is None:
        return []

    found: List[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id in IGNORE_GLOBALS for t in node.targets):
            continue
        found.extend(_literal_strings(node.value, conftest))

    return found


def _literal_strings(node: ast.expr, conftest: Path) -> List[str]:
    """Every string a list literal yields, `os.path.join(...)` included."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []

    found: List[str] = []
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            found.append(element.value)
        elif (joined := _joined_literal(element)) is not None:
            found.append(joined)
        else:
            logger.warning(
                f"[INVENTORY] {conftest} declares a non-literal ignore pattern; "
                f"the files it excludes are counted as running"
            )

    return found


def _joined_literal(node: ast.expr) -> Optional[str]:
    """`os.path.join("a", "b")` over string literals, as one posix pattern."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "join":
        return None
    parts = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
    if len(parts) != len(node.args):
        return None
    return str(Path(*parts)) if parts else None


def _ignored_by_conftest(path: Path, ignores: Sequence[Tuple[Path, str]]) -> bool:
    """True when a conftest ON THIS PATH declares a glob matching the file.

    Scoping to ancestors is pytest's rule and it matters: a `parked/` conftest
    saying `["*"]` must silence its own directory and nothing else, and a
    basename match would have silenced every `parked/` in the fleet from one
    branch's file.
    """
    return any(_under(directory, path) and fnmatch.fnmatch(str(path), glob) for directory, glob in ignores)


def _under(directory: Path, path: Path) -> bool:
    """True when `path` sits inside `directory`."""
    return directory == path.parent or directory in path.parents


# =============================================================================
# MODULE-LEVEL SKIPS
# =============================================================================


def _skipped_at_module_level(path: Path) -> Optional[str]:
    """The skip status a module-level call imposes, or None when there is none.

    An unconditional `skip` outranks a conditional `importorskip` when a file
    carries both: the file is abandoned either way, and reporting the weaker
    of the two would let a parked file appear as one that merely lacks an
    optional package.
    """
    tree = _parse(path)
    if tree is None:
        return None

    aliases = _pytest_aliases(tree)
    found = {status for node in tree.body if (status := _skip_call_status(node, aliases))}
    if STATUS_MODULE_SKIP in found:
        return STATUS_MODULE_SKIP
    return STATUS_CONDITIONAL_SKIP if found else None


def _pytest_aliases(tree: ast.Module) -> Set[str]:
    """Every name `pytest` is bound to in this module, aliases included."""
    aliases: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "pytest")
    return aliases


def _skip_call_status(node: ast.stmt, aliases: Set[str]) -> Optional[str]:
    """The status a bare `<pytest>.skip(...)`/`.importorskip(...)` imposes.

    Bound to the module's own aliases rather than the literal word `pytest`,
    because the file that started this - memory's parked symbolic tier - writes
    `import pytest as _parked` and a name-matched check reads it as clean.
    """
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    func = node.value.func
    if not isinstance(func, ast.Attribute) or func.attr not in SKIP_CALLS:
        return None
    if not isinstance(func.value, ast.Name) or func.value.id not in aliases:
        return None
    return SKIP_CALLS[func.attr]


# =============================================================================
# SHARED
# =============================================================================


def _pruned(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    """True when any directory on the way to `path` matches norecursedirs."""
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        logger.warning(f"[INVENTORY] {path} sits outside {root}; pruned against its absolute path instead")
        parts = path.parts[:-1]
    return any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in patterns)


def _parse(path: Path) -> Optional[ast.Module]:
    """The parsed module, or None when it will not parse or read."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError) as exc:
        logger.warning(f"[INVENTORY] {path} will not parse, its exclusions are unread: {exc}")
        return None
