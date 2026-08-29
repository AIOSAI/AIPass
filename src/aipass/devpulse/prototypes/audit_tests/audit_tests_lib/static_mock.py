# =================== AIPass ====================
# Name: static_mock.py - the MOCK-DRIFT nominator
# Description: patch targets that do not resolve, and patches of whole modules
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Nominate ``mock.patch`` targets that have drifted from the code they name.

Two arms, both from ``DESIGN_BRIEF`` §C.1 row 4:

* **unresolved** -- the dotted target names no attribute that exists in the
  copied tree.  A patch whose target is gone is a patch that protects nothing:
  in api half 1 a production function was deleted and **46 of 46 tests stayed
  green**.
* **whole module** -- ``patch("a.b.c")`` where ``c`` is itself a module.  The
  module object is replaced wholesale, so every name reached through it becomes
  a ``MagicMock`` and the test can no longer tell a rename from a rewrite.

``spec=`` and ``autospec=True`` acquit both arms and are counted separately, per
the same row.  Resolution is import-free and therefore best-effort: a target
whose module prefix is not in the copied tree at all (stdlib, third party) is out
of scope and counted, never nominated.  Law M1 -- these are suspects.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .logsetup import logger
from .astutil import dotted_of, fold_strings, resolve_str
from .modmap import split_target, top_level_names

_PATCH_FUNCS = {"patch", "mock.patch", "unittest.mock.patch", "mocker.patch"}
_PATCH_OBJECT_FUNCS = {"patch.object", "mock.patch.object", "unittest.mock.patch.object", "mocker.patch.object"}
_ACQUITTING_KWARGS = ("autospec", "spec", "spec_set")


@dataclass
class Nomination:
    """One suspect patch target."""

    file: str
    line: int
    species: str
    arm: str
    target: str
    detail: str


def _acquitted(node: ast.Call) -> bool:
    """``spec``/``autospec``/``spec_set`` make a patch self-checking: no nomination."""
    return any(k.arg in _ACQUITTING_KWARGS and k.value is not None for k in node.keywords)


class _Resolver:
    """Caches per-module top-level name sets across a whole suite."""

    def __init__(self, modules: dict[str, Path]) -> None:
        """Index the copied tree's modules; names are read lazily and cached."""
        self.modules = modules
        self._names: dict[str, set[str]] = {}

    def names(self, dotted: str) -> set[str]:
        """Module-level names of one module, read from its AST and cached."""
        if dotted not in self._names:
            self._names[dotted] = top_level_names(self.modules[dotted])
        return self._names[dotted]


def analyse_file(path: Path, resolver: _Resolver, display: str) -> tuple[list[Nomination], dict]:
    """Nominations for one test file plus the counters that frame them."""
    stats = {"patch_calls": 0, "acquitted_by_spec": 0, "out_of_tree": 0, "resolved_ok": 0}
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError) as exc:
        logger.debug("unparseable test file: %s", path, exc_info=exc)
        return [], {**stats, "parse_error": str(exc)[:200]}

    consts = fold_strings(tree)
    out: list[Nomination] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = dotted_of(node.func) or ""
        if func in _PATCH_OBJECT_FUNCS:
            stats["patch_calls"] += 1
            stats["out_of_tree"] += 1  # object identity is a runtime fact
            continue
        if func not in _PATCH_FUNCS or not node.args:
            continue
        stats["patch_calls"] += 1
        target = resolve_str(node.args[0], consts)
        if target is None:
            stats["out_of_tree"] += 1
            continue
        module, attrs = split_target(target, resolver.modules)
        if module is None:
            stats["out_of_tree"] += 1
            continue
        if not attrs:
            if _acquitted(node):
                stats["acquitted_by_spec"] += 1
                continue
            out.append(
                Nomination(
                    file=display,
                    line=node.lineno,
                    species="MOCK-DRIFT",
                    arm="whole_module",
                    target=target,
                    detail=f"{target!r} is a module, not an attribute; the whole module object is replaced",
                )
            )
            continue
        if attrs[0] in resolver.names(module):
            stats["resolved_ok"] += 1
            continue
        if _acquitted(node):
            stats["acquitted_by_spec"] += 1
            continue
        out.append(
            Nomination(
                file=display,
                line=node.lineno,
                species="MOCK-DRIFT",
                arm="unresolved",
                target=target,
                detail=f"{module}.py defines no top-level {attrs[0]!r} (static inspection of the copy)",
            )
        )

    return out, stats


def run(test_files: list[Path], modules: dict[str, Path], root: Path) -> dict:
    """Nominate across a whole suite."""
    resolver = _Resolver(modules)
    nominations: list[Nomination] = []
    totals = {"patch_calls": 0, "acquitted_by_spec": 0, "out_of_tree": 0, "resolved_ok": 0, "parse_errors": 0}
    for path in test_files:
        try:
            display = str(path.relative_to(root))
        except ValueError as exc:
            logger.debug("path is not under the root: %s", path, exc_info=exc)
            display = str(path)
        found, stats = analyse_file(path, resolver, display)
        nominations.extend(found)
        for key in ("patch_calls", "acquitted_by_spec", "out_of_tree", "resolved_ok"):
            totals[key] += stats.get(key, 0)
        if "parse_error" in stats:
            totals["parse_errors"] += 1
    return {
        "nominations": [n.__dict__ for n in nominations],
        "counters": totals,
        "rule": "T11 - the name you patch decides whether a rename is noticed",
    }
