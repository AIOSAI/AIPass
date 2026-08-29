# =================== AIPass ====================
# Name: modmap.py - import-free module resolution over a copied tree
# Description: dotted name -> file, and the top-level names each file defines
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Resolve dotted names against a tree by reading it, never by importing it.

Law T8 is *stop resolving the target by guessing*, and importing a branch to
find out what it defines runs that branch's import side effects -- which on this
fleet means writing to somebody's audit log.  So the map is built from the file
layout and each file's own AST.

Best-effort by construction, and the callers say so: a name assembled at runtime
(``setattr``, ``globals()[...]``, a re-export loop) is invisible here.  That is
why every finding this feeds is a nomination and never a verdict (Law M1).
"""

from __future__ import annotations

import ast
from pathlib import Path

from .logsetup import logger

_SKIP_DIRS = {"__pycache__", ".git", ".venv", ".pytest_cache", ".ruff_cache"}


def build_module_map(src_root: Path) -> dict[str, Path]:
    """Map every importable dotted module name under ``src_root`` to its file."""
    modules: dict[str, Path] = {}
    for path in sorted(src_root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_symlink():
            continue
        relative = path.relative_to(src_root)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
            if not parts:
                continue
        else:
            parts[-1] = parts[-1][: -len(".py")]
        modules[".".join(parts)] = path
    return modules


def top_level_names(path: Path) -> set[str]:
    """Names a module file binds at module scope, read from its AST."""
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError) as exc:
        # Unparseable is not empty: a file whose names could not be read must not
        # make a patch target look unresolvable, so callers see the empty set and
        # the nominator stays silent rather than guessing (Law T8).
        logger.debug("could not read module-level names of %s", path, exc_info=exc)
        return names
    for node in tree.body:
        names |= _bound_by(node)
        if isinstance(node, (ast.If, ast.Try)):
            # try/except ImportError and `if TYPE_CHECKING:` bind names too, and
            # a module that binds a name conditionally still binds it.
            for child in ast.walk(node):
                names |= _bound_by(child)
    return names


def _bound_by(node: ast.AST) -> set[str]:
    """The module-scope names a single statement binds."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return set().union(*(_assigned_names(t) for t in node.targets)) if node.targets else set()
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return _assigned_names(node.target)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return set()


def _assigned_names(target: ast.expr) -> set[str]:
    """Every name an assignment target binds, tuple and list unpacking included."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out: set[str] = set()
        for element in target.elts:
            out |= _assigned_names(element)
        return out
    return set()


def split_target(dotted: str, modules: dict[str, Path]) -> tuple[str | None, list[str]]:
    """Split ``a.b.c`` into the longest known module prefix and the rest."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in modules:
            return candidate, parts[cut:]
    return None, parts
