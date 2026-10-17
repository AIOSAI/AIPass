# =================== AIPass ====================
# Name: exclusions.py
# Description: which collected-looking test files pytest actually refuses to run
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""
TESTS THAT EXIST AND NEVER RUN, which is an inventory finding, not a rounding
error.

Three statuses, read statically: IGNORED_BY_CONFTEST (`collect_ignore[_glob]`,
resolved against the conftest's own directory as pytest does), MODULE_LEVEL_SKIP
(a statement-level `pytest.skip`), CONDITIONAL_SKIP (`importorskip`: whether it
runs is a property of the host). Loop-built ignore lists, collection hooks,
`skipif` and `-k`/`-m` are invisible, so this module UNDER-reports exclusion."""

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

#: CONDITIONAL_SKIP counts as running: the alternative asserts an absence this module cannot see.
RUNNING_STATUSES: frozenset = frozenset({STATUS_COLLECTED, STATUS_CONDITIONAL_SKIP})

SKIP_CALLS: dict = {"skip": STATUS_MODULE_SKIP, "importorskip": STATUS_CONDITIONAL_SKIP}

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

    Only literals: a computed pattern list leaves its files counted as RUNNING."""
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

    Ancestors only, as pytest scopes it: a `parked/` conftest's `["*"]` silences its own directory."""
    return any(_under(directory, path) and fnmatch.fnmatch(str(path), glob) for directory, glob in ignores)


def _under(directory: Path, path: Path) -> bool:
    """True when `path` sits inside `directory`."""
    return directory == path.parent or directory in path.parents


def _skipped_at_module_level(path: Path) -> Optional[str]:
    """The skip status a module-level call imposes, or None when there is none.

    An unconditional `skip` outranks `importorskip`: a parked file must not read as a missing package."""
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

    Bound to the module's own aliases: `import pytest as _parked` must not read as clean."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    func = node.value.func
    if not isinstance(func, ast.Attribute) or func.attr not in SKIP_CALLS:
        return None
    if not isinstance(func.value, ast.Name) or func.value.id not in aliases:
        return None
    return SKIP_CALLS[func.attr]


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
