# =================== AIPass ====================
# Name: pinning.py
# Description: the test files whose source names a repo-relative path, as a string or as Path parts
# Version: 1.1.0
# Created: 2026-11-01
# Modified: 2026-11-06
# =============================================

"""
TESTS PINNING A PATH: a non-Python file has no import graph, so its tests are found by the path they name.

Read as one string or as trailing literal parts (``root / ".claude" / "codex.md"``, ``Path(...)``);
a path built from a variable is invisible here. A fleet walk names no branch: a test that imports a module
spelling the branch-relative tail (``.aipass/aipass_local_prompt.md`` for ``src/aipass/devpulse/...``)
pins every branch's copy, so it is listed too.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List

from aipass.prax import logger

from aipass.sentry.apps.handlers.json import json_handler

#: Where pytest collects from: pyproject's testpaths.
TESTPATHS = ("tests", "src")

#: pyproject's norecursedirs, plus the dot-dir rule it restores with ".*".
SKIP_DIRS = frozenset({"templates", "__pycache__", "my-project", "docs.local", "dropbox", "node_modules"})

#: Calls whose literal arguments are path parts.
_PATH_CALLS = frozenset({"Path", "PurePath", "PurePosixPath", "joinpath"})


def test_files(root: Path) -> Iterator[Path]:
    """Every file pytest would collect as tests under the repo's testpaths."""
    for top in TESTPATHS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if not (path.name.startswith("test_") or path.name.endswith("_test.py")):
                continue
            if _skipped(path.relative_to(root).parts[:-1]):
                continue
            if "telegram" in path.as_posix():
                continue
            yield path


def _literal_pattern(rel: str) -> re.Pattern:
    """The path as one string, not as the tail of a longer path or name."""
    return re.compile(r"(?<![\w./-])" + re.escape(rel) + r"(?![\w.-])")


def _trailing_parts(parts: List[ast.expr]) -> str:
    """The trailing run of string literals, joined as a path."""
    tail: List[str] = []
    for part in reversed(parts):
        if not (isinstance(part, ast.Constant) and isinstance(part.value, str)):
            break
        tail.insert(0, part.value.strip("/"))
    return "/".join(tail)


def _joined_paths(tree: ast.AST) -> Iterator[str]:
    """Every path a ``/`` chain or a Path call spells in literal trailing parts."""
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            operands: List[ast.expr] = []
            current: ast.expr = node
            while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
                operands.insert(0, current.right)
                current = current.left
            yield _trailing_parts([current, *operands])
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _PATH_CALLS:
                yield _trailing_parts(list(node.args))


def _names(source: str, rel: str, pattern: re.Pattern, path: Path) -> bool:
    """Whether this test source names ``rel`` in either spelling."""
    if pattern.search(source):
        return True
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info(f"[PINNING] {path} does not parse, read as a string only: {exc}")
        return False
    return rel in set(_joined_paths(tree))


def branch_tail(rel: str) -> str:
    """The path below its branch directory (``src/<package>/<branch>/``), or "" for a path outside one."""
    parts = Path(rel).parts
    return "/".join(parts[3:]) if len(parts) > 3 and parts[0] == "src" else ""


def _skipped(parts: tuple) -> bool:
    """A directory pytest does not recurse into: a dot-dir, a norecursedir, an egg-info."""
    return any(part.startswith(".") or part in SKIP_DIRS or part.endswith(".egg-info") for part in parts)


def spelling_modules(root: Path, tail: str) -> Dict[Path, str]:
    """Every source file under ``src/`` that names ``tail``, mapped to the name a test imports it by."""
    found: Dict[Path, str] = {}
    pattern = _literal_pattern(tail)
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root / "src")
        if _skipped(rel.parts[:-1]):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"[PINNING] cannot read {path}, the tests importing it are not listed by it: {exc}")
            continue
        if Path(tail).name in source and _names(source, tail, pattern, path):
            found[path] = rel.parent.name if path.name == "__init__.py" else path.stem
    return found


def _imported_files(root: Path, tree: ast.AST) -> Iterator[Path]:
    """The source files under ``src/`` that this tree imports by absolute name, a module or a package."""
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names += [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        elif isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
    for name in dict.fromkeys(names):
        base = root / "src" / Path(*name.split("."))
        yield from (candidate for candidate in (base.with_suffix(".py"), base / "__init__.py") if candidate.is_file())


def _walks(root: Path, source: str, spellers: Dict[Path, str]) -> bool:
    """Whether a test imports a module that spells the tail: a walk that reads every branch's copy."""
    if not any(name in source for name in spellers.values()):
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info(f"[PINNING] a test does not parse, its imports are not followed: {exc}")
        tree = ast.Module(body=[], type_ignores=[])
    return any(module in spellers for module in _imported_files(root, tree))


def pinning(root: Path, rels: List[str]) -> Dict[str, List[str]]:
    """For each repo-relative path, the repo-relative test files that name it, sorted."""
    found: Dict[str, List[str]] = {rel: [] for rel in rels}
    patterns = {rel: _literal_pattern(rel) for rel in rels}
    spellers = {rel: spelling_modules(root, branch_tail(rel)) if branch_tail(rel) else {} for rel in rels}
    for path in test_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"[PINNING] cannot read {path}, it is not searched: {exc}")
            continue
        for rel in rels:
            named = Path(rel).name in source and _names(source, rel, patterns[rel], path)
            if named or (spellers[rel] and _walks(root, source, spellers[rel])):
                found[rel].append(path.relative_to(root).as_posix())
    json_handler.log_operation("tests_pinning", {"paths": len(rels), "tests": sum(map(len, found.values()))})
    return found
