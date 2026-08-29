# =================== AIPass ====================
# Name: astutil.py - shared AST helpers for the static nominators
# Description: module-level string folding and subject-module identification
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Shared AST machinery for the static tier.

Two jobs.  **String folding** resolves the module-level constants this fleet
builds its dotted paths out of -- daemon's contracts template writes
``_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"``
and every later rule needs the folded value to know what it is looking at.
Only literals and names already bound to literals are folded; anything computed
at runtime stays unresolved rather than guessed (Law T8).

**Subject identification** answers "does this name refer to the thing under
test?"  A module is the subject when its file lives inside the copied target,
which needs no layout assumption and no import.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .logsetup import logger

MACHINE_READS = (
    "sys.platform",
    "sys.version_info",
    "sys.maxsize",
    "sys.implementation",
    "os.name",
    "os.environ",
    "os.getenv",
    "os.geteuid",
    "os.getuid",
    "shutil.which",
    "platform.",
    "socket.gethostname",
)


def dotted_of(node: ast.expr) -> str | None:
    """``a.b.c`` for an attribute/name chain, else None."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def fold_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a statically knowable string."""
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = resolve_str(node.value, consts)
        if value is not None:
            consts[target.id] = value
    return consts


def resolve_str(node: ast.expr, consts: dict[str, str]) -> str | None:
    """Best-effort constant string value of an expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        return _resolve_fstring(node, consts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = resolve_str(node.left, consts)
        right = resolve_str(node.right, consts)
        return None if left is None or right is None else left + right
    return None


def _resolve_fstring(node: ast.JoinedStr, consts: dict[str, str]) -> str | None:
    """An f-string, only if every interpolation folds to a constant.

    One unresolvable piece makes the whole value unknown, and unknown is
    reported as unknown -- guessing the rest is how a nominator invents a target
    that never existed (Law T8).
    """
    pieces: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            pieces.append(part.value)
            continue
        if not isinstance(part, ast.FormattedValue):
            return None
        inner = resolve_str(part.value, consts)
        if inner is None:
            return None
        pieces.append(inner)
    return "".join(pieces)


class SubjectIndex:
    """Which dotted modules are the target's own code, and which local names alias them."""

    def __init__(self, modules: dict[str, Path], target_copy: Path) -> None:
        """Index the copied tree; a module is the subject iff its file lives inside it."""
        self.modules = modules
        self.target_copy = target_copy.resolve()
        self.subject_modules = {dotted for dotted, path in modules.items() if self._inside(path)}

    def _inside(self, path: Path) -> bool:
        """Is this file part of the copy? The only question that defines a subject."""
        try:
            path.resolve().relative_to(self.target_copy)
        except ValueError as exc:
            logger.debug("not under the copy: %s", path, exc_info=exc)
            return False
        return True

    def is_subject_module(self, dotted: str) -> bool:
        """True for a subject module or anything beneath it, by dotted prefix."""
        if dotted in self.subject_modules:
            return True
        return any(dotted.startswith(m + ".") for m in self.subject_modules)

    def local_names(self, tree: ast.Module, consts: dict[str, str]) -> set[str]:
        """Names in this file that refer to the target's own code.

        Covers ``from <subject> import X``, ``import <subject> as y``, relative
        imports (always the subject by construction), ``importlib.import_module``
        of a folded subject path, and plain aliases of any of those.
        """
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names |= self._imported_subject_names(node)
            elif isinstance(node, ast.Assign):
                names |= self._aliased_subject_name(node, consts, names)
        return names

    def _imported_subject_names(self, node: ast.Import | ast.ImportFrom) -> set[str]:
        """Names an import statement binds to the target's own code.

        A relative import is the subject by construction: it can only reach a
        module that ships in the same package as the file doing the importing.
        """
        if isinstance(node, ast.ImportFrom):
            if node.level or (node.module and self.is_subject_module(node.module)):
                return {a.asname or a.name for a in node.names}
            return set()
        return {alias.asname or alias.name.split(".")[0] for alias in node.names if self.is_subject_module(alias.name)}

    def _aliased_subject_name(self, node: ast.Assign, consts: dict[str, str], known: set[str]) -> set[str]:
        """A name bound to an already-known subject name, or to an import call."""
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return set()
        target = node.targets[0]
        if self._is_subject_import_call(node.value, consts):
            return {target.id}
        if isinstance(node.value, ast.Name) and node.value.id in known:
            return {target.id}
        return set()

    def _is_subject_import_call(self, node: ast.expr, consts: dict[str, str]) -> bool:
        """An ``importlib.import_module`` whose argument folds to a subject path."""
        if not isinstance(node, ast.Call):
            return False
        func = dotted_of(node.func) or ""
        if func not in ("importlib.import_module", "import_module"):
            return False
        if not node.args:
            return False
        dotted = resolve_str(node.args[0], consts)
        return bool(dotted) and self.is_subject_module(dotted)


def reads_machine(node: ast.expr) -> bool:
    """True when an expression consults the host rather than the subject (T7)."""
    for child in ast.walk(node):
        if isinstance(child, (ast.Attribute, ast.Name)):
            dotted = dotted_of(child)
            if dotted and any(dotted.startswith(m) for m in MACHINE_READS):
                return True
    return False
