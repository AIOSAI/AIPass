# =================== AIPass ====================
# Name: static_skip.py - the SELF-SKIP nominator
# Description: skip predicates that read the subject instead of the machine (T7)
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Nominate skips whose predicate reads the thing under test.

Law T7 in one line: **a skip predicate may read the machine, never the subject.**
A skip on ``sys.platform`` is a statement about where the test is running.  A
skip on ``hasattr(json_handler, "JSON_DIR")`` is a statement about the code under
test, and it disables the test at exactly the moment the code breaks -- the
scaffold's ``test_json_handler.py`` measured *control: 5 passed / mutated:
4 passed, 1 skipped, exit 0*, and renaming one daemon constant makes **75 tests
silently vanish**.

Taint, and why it is not optional here: the fleet's flagship specimen never puts
the subject read in the predicate.  ``_JSON_DIR_ATTR`` is assigned *inside* an
``if hasattr(_mod, candidate):`` and the skip then tests ``_JSON_DIR_ATTR is
None``.  So a name assigned under a subject-reading condition carries the taint
forward, and the predicate that reads it is nominated.

Everything here NOMINATES.  Law M1: a static hit is a suspect, never a verdict.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .logsetup import logger
from .astutil import SubjectIndex, dotted_of, fold_strings, reads_machine, resolve_str


@dataclass
class Nomination:
    """One suspect, with enough detail for a human to overturn it."""

    file: str
    line: int
    species: str
    detail: str
    predicate: str


def _root_name(node: ast.expr) -> str | None:
    """The leftmost name of an attribute chain: ``a.b.c`` is rooted at ``a``."""
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


class _Tainter(ast.NodeVisitor):
    """Names that carry a subject read forward, by value or by control flow.

    The ``visit_Assign`` / ``visit_If`` / ``visit_While`` spellings are not a
    naming choice: ``ast.NodeVisitor`` dispatches on ``"visit_" + type(node).__name__``,
    so these are the only names the stdlib will ever call.  Declared deviation
    from seedgo's ``naming`` standard.
    """

    def __init__(self, subject_names: set[str]) -> None:
        """Start tainted with the names that already refer to the subject."""
        self.subject_names = subject_names
        self.tainted: set[str] = set(subject_names)

    def reads_subject(self, node: ast.expr) -> bool:
        """Does this expression touch the subject, directly or through a tainted name?"""
        for child in ast.walk(node):
            if isinstance(child, (ast.Name, ast.Attribute)):
                root = _root_name(child)
                if root and root in self.tainted:
                    return True
        return False

    def _taint_targets(self, node: ast.AST) -> None:
        """Mark every name this statement binds as carrying the subject read."""
        for child in ast.walk(node):
            self.tainted |= _bound_names(child)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Value taint: ``flag = hasattr(subject, \"x\")`` taints ``flag``."""
        if self.reads_subject(node.value):
            self._taint_targets(node)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        """Control taint: what is assigned under a subject test carries the read.

        This is what catches the fleet's flagship SKIP-ON-DRIFT shape, where the
        module is probed in one place and the skip is decided several lines later.
        """
        if self.reads_subject(node.test):
            for stmt in node.body:
                self._taint_targets(stmt)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        """Control taint again, for a loop whose condition reads the subject."""
        if self.reads_subject(node.test):
            for stmt in node.body:
                self._taint_targets(stmt)
        self.generic_visit(node)


def _bound_names(node: ast.AST) -> set[str]:
    """Names one assignment binds, tuple unpacking included."""
    if isinstance(node, ast.Assign):
        return {n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def _predicate_source(node: ast.expr, source: str) -> str:
    """The predicate as the author wrote it -- a nomination has to be readable."""
    try:
        return ast.get_source_segment(source, node) or ast.dump(node)[:120]
    except Exception as exc:  # source segment is best effort
        logger.debug("no source segment for a skip predicate", exc_info=exc)
        return ast.dump(node)[:120]


def _enclosing_tests(tree: ast.Module) -> dict[int, list[ast.expr]]:
    """Map every node's id() to the ``if``/``while`` tests guarding it."""
    guards: dict[int, list[ast.expr]] = {id(tree): []}

    def walk(node: ast.AST, tests: list[ast.expr]) -> None:
        """Carry the enclosing tests down the tree, one branch at a time."""
        if isinstance(node, (ast.If, ast.While)):
            # The predicate itself is not guarded by itself, and the else branch
            # is guarded by its negation - neither belongs in the body's list.
            guards[id(node.test)] = tests
            walk(node.test, tests)
            for stmt in node.body:
                guards[id(stmt)] = [*tests, node.test]
                walk(stmt, [*tests, node.test])
            for stmt in node.orelse:
                guards[id(stmt)] = tests
                walk(stmt, tests)
            return
        for child in ast.iter_child_nodes(node):
            guards[id(child)] = tests
            walk(child, tests)

    walk(tree, [])
    return guards


def analyse_file(path: Path, index: SubjectIndex, display: str) -> tuple[list[Nomination], dict]:
    """Nominations for one test file, plus the counts that keep it honest."""
    stats = {"skip_sites": 0, "acquitted_machine": 0, "unclassified": 0}
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError) as exc:
        logger.debug("unparseable test file: %s", path, exc_info=exc)
        return [], {**stats, "parse_error": str(exc)[:200]}

    consts = fold_strings(tree)
    subject_names = index.local_names(tree, consts)
    tainter = _Tainter(subject_names)
    tainter.visit(tree)
    guards = _enclosing_tests(tree)
    out: list[Nomination] = []

    def judge(predicates: list[ast.expr], line: int, species: str, detail: str) -> None:
        """One skip site, judged on whichever of its predicates decides it."""
        stats["skip_sites"] += 1
        for predicate in predicates:
            if tainter.reads_subject(predicate):
                out.append(
                    Nomination(
                        file=display,
                        line=line,
                        species=species,
                        detail=detail,
                        predicate=_predicate_source(predicate, source),
                    )
                )
                return
        if any(reads_machine(p) for p in predicates):
            stats["acquitted_machine"] += 1
        else:
            stats["unclassified"] += 1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = dotted_of(node.func) or ""
        if func in ("pytest.importorskip", "importorskip"):
            stats["skip_sites"] += 1
            dotted = resolve_str(node.args[0], consts) if node.args else None
            if dotted and index.is_subject_module(dotted):
                out.append(
                    Nomination(
                        file=display,
                        line=node.lineno,
                        species="SELF-SKIP",
                        detail=f"importorskip on the subject module {dotted!r}",
                        predicate=f"pytest.importorskip({dotted!r})",
                    )
                )
            else:
                stats["acquitted_machine"] += 1
        elif func in ("pytest.skip", "skip"):
            judge(
                guards.get(id(node), []),
                node.lineno,
                "SKIP-ON-DRIFT",
                "pytest.skip() reached only when this predicate holds",
            )
        elif func in ("pytest.mark.skipif", "mark.skipif"):
            condition = node.args[0] if node.args else _keyword(node, "condition")
            judge([condition] if condition else [], node.lineno, "SELF-SKIP", "skipif predicate")

    return out, stats


def _keyword(node: ast.Call, name: str) -> ast.expr | None:
    """One keyword argument of a call, by name, or ``None``."""
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def run(test_files: list[Path], index: SubjectIndex, root: Path) -> dict:
    """Nominate across a whole suite."""
    nominations: list[Nomination] = []
    totals = {"skip_sites": 0, "acquitted_machine": 0, "unclassified": 0, "parse_errors": 0}
    for path in test_files:
        try:
            display = str(path.relative_to(root))
        except ValueError as exc:
            logger.debug("path is not under the root: %s", path, exc_info=exc)
            display = str(path)
        found, stats = analyse_file(path, index, display)
        nominations.extend(found)
        for key in ("skip_sites", "acquitted_machine", "unclassified"):
            totals[key] += stats.get(key, 0)
        if "parse_error" in stats:
            totals["parse_errors"] += 1
    return {
        "nominations": [n.__dict__ for n in nominations],
        "counters": totals,
        "rule": "T7 - a skip predicate may read the machine, never the subject",
    }
