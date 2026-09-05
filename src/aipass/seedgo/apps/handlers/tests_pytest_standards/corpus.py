# =================== AIPass ====================
# Name: corpus.py
# Description: the parsed test corpus every static nominator reads
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The test corpus, parsed ONCE and handed to every nominator.

WHY THIS EXISTS AS A SEPARATE FILE. Nine nominators over an eighteen-branch
fleet would otherwise parse every test file nine times. The research budget
for the whole static tier is under four seconds fleet-wide; nine redundant
parses is the difference between that number and a number nobody schedules.

WHY EVERY RULE IS AST AND NOT GREP. This campaign has already made the
token-grep mistake twice and measured itself wrong both times: a docstring
naming `aipass` is not an import, and a fixture's SOURCE STRING is not a
subprocess spawn. A rule that matches text matches the prose describing the
rule, which is how a checker ends up flagging its own documentation.

AN UNPARSEABLE FILE IS REPORTED, NEVER SKIPPED. A test file that will not
parse is one no nominator could clear, and "could not check" must never read
the same as "checked and clean" — the same rule the payload isolation proof
already follows.

WHAT A NOMINATION IS. Law M1: static NOMINATES, execution CONVICTS. Nothing
here returns a score, and nothing here may emit a delete-family verdict
(Law S7b) — a nomination says a test is suspect, never that it is worthless.
Law M11 is why every row carries a `deletion_safety` field: deletion safety is
a row-level probe, not a group, and the corpus records that the probe has not
run rather than leaving a reader to assume it did.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set

from aipass.prax import logger

#: Directories never walked when collecting the corpus.
SKIP_DIRS: frozenset = frozenset(
    {"__pycache__", ".git", ".venv", "node_modules", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".chroma"}
)

#: Filename shapes pytest itself collects.
TEST_FILE_GLOBS: tuple = ("test_*.py", "*_test.py")

#: Names that make a call an oracle even without an `assert` statement.
ORACLE_CALL_NAMES: frozenset = frozenset({"raises", "fail", "warns", "deprecated_call", "approx", "xfail"})

#: Mock assertion methods. A test asserting an interaction has a real oracle.
MOCK_ASSERT_PREFIX = "assert_"

#: Verdicts a nominator may emit. A subset of the core's ALLOWED_VERDICTS,
#: kept here so a nominator cannot reach for a word the core would refuse.
VERDICT_SUSPECT = "suspect"
VERDICT_IMPROVE = "improve"

#: Stamped on every nomination row (Law M11). The probe that would settle
#: whether a flagged test is safe to delete is NOT built in this release, and
#: the row says so rather than staying silent — an absent field and a passing
#: probe must never look the same.
DELETION_SAFETY_UNPROBED = {
    "probed": False,
    "reason": (
        "the M11 deletion-safety probe is not built in this release; a nomination is not "
        "a licence to delete, and the corpus proves why - daemon's HANDLED_COMMANDS pins "
        "read as tautologies and are the last thing standing between a rename and the "
        "fleet's scheduler being turned off"
    ),
}


@dataclass
class TestUnit:
    """One test function, with everything the rules ask about it."""

    name: str
    node: ast.FunctionDef
    lineno: int
    docstring: str
    params: List[str]
    decorators: List[ast.expr]
    class_name: str
    relpath: str

    @property
    def nodeid(self) -> str:
        """The pytest nodeid this unit would run under."""
        if self.class_name:
            return f"{self.relpath}::{self.class_name}::{self.name}"
        return f"{self.relpath}::{self.name}"


@dataclass
class TestFile:
    """One parsed test module."""

    path: Path
    relpath: str
    source: str
    tree: ast.Module
    units: List[TestUnit] = field(default_factory=list)


@dataclass
class Corpus:
    """Everything the static tier reads, parsed once.

    `unparseable` is a first-class field rather than a log line: a file the
    parser could not read is a file no nominator cleared, and every group
    publishes that count beside its own findings.
    """

    root: Path
    files: List[TestFile] = field(default_factory=list)
    unparseable: List[str] = field(default_factory=list)
    production: List[Path] = field(default_factory=list)

    #: Production modules, parsed once for every rule that reads them.
    production_trees: Dict[Path, ast.Module] = field(default_factory=dict)

    #: Production files the parser could not read. A rule whose subject is what
    #: production DECLARES sees less than the tree contains when one of these
    #: exists, and that bias runs toward FEWER nominations - toward clean. It
    #: is published for the same reason the test-side count is.
    production_unparseable: List[str] = field(default_factory=list)

    @property
    def production_limits(self) -> List[str]:
        """What the production-side rules could not read, as a limits line."""
        if not self.production_unparseable:
            return []
        return [
            f"{len(self.production_unparseable)} production file(s) would not parse and declare "
            f"nothing this rule can read, which biases it toward FEWER nominations: "
            f"{', '.join(self.production_unparseable[:5])}"
        ]

    @property
    def unit_count(self) -> int:
        """How many test functions were parsed across the whole corpus."""
        return sum(len(f.units) for f in self.files)

    def units(self) -> Iterator[TestUnit]:
        """Every test unit in the corpus, file order then source order."""
        for parsed in self.files:
            yield from parsed.units


# =============================================================================
# COLLECTION
# =============================================================================


def _walk(root: Path, patterns: Sequence[str]) -> List[Path]:
    """Every file under `root` matching any pattern, skipping SKIP_DIRS."""
    found: List[Path] = []
    for path in sorted(root.rglob("*.py")):
        # PRUNE RELATIVE TO THE WALK ROOT, NOT ABSOLUTELY. Reading `path.parts`
        # tests the whole absolute path, so a target that merely LIVES under a
        # directory named `.venv`, `node_modules`, `.git` etc. had every test
        # file skipped - and the result was a silent, plausible empty corpus
        # rather than an error. This lane copies targets into temporary trees,
        # so the parent directories are not the target's own business.
        # Measured before the fix: a project under node_modules/ collected 0 units.
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if any(path.match(pattern) for pattern in patterns):
            found.append(path)
    return found


def _relpath(path: Path, root: Path) -> str:
    """Posix path relative to the corpus root, or the absolute path."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # An absolute nodeid still identifies the test, but it will not match
        # anything an operator pastes into pytest from the target's own root,
        # so the fallback is recorded rather than taken quietly.
        logger.warning(f"[AUDIT-TESTS] {path} is outside the corpus root {root}, using its absolute path")
        return path.as_posix()


def _decorator_list(node: ast.FunctionDef) -> List[ast.expr]:
    """The decorators on a function, as expression nodes."""
    return list(node.decorator_list)


def _is_test_function(node: ast.AST) -> bool:
    """A `test_*` function or coroutine, at any level."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")


def _units_in(tree: ast.Module, relpath: str) -> List[TestUnit]:
    """Every `test_*` function in a module, including methods on test classes."""
    units: List[TestUnit] = []

    for node in tree.body:
        if _is_test_function(node):
            units.append(_build_unit(node, "", relpath))
        elif isinstance(node, ast.ClassDef):
            units.extend(_build_unit(child, node.name, relpath) for child in node.body if _is_test_function(child))

    return units


def _build_unit(node, class_name: str, relpath: str) -> TestUnit:
    """One TestUnit from a function node."""
    return TestUnit(
        name=node.name,
        node=node,
        lineno=node.lineno,
        docstring=ast.get_docstring(node) or "",
        params=[arg.arg for arg in node.args.args if arg.arg != "self"],
        decorators=_decorator_list(node),
        class_name=class_name,
        relpath=relpath,
    )


def build(root: Path, test_dirs: Optional[Sequence[str]] = None) -> Corpus:
    """Parse every test file under `root` into a Corpus.

    `test_dirs` narrows the walk when a project keeps its tests in a known
    place; passing None walks the whole tree, which is what an unknown
    external target needs.
    """
    root = Path(root)
    corpus = Corpus(root=root)

    # FILTER BY EXISTENCE, THEN FALL BACK. The obvious spelling can never reach
    # the fallback: a non-empty `test_dirs` yields a non-empty list whether or
    # not any of those directories EXIST, so the walk finds nothing and the
    # target reads as having no tests at all. Measured before the fix: a project
    # keeping tests at src/tests/ collected 0 files, 0 units.
    roots = [root / name for name in (test_dirs or []) if (root / name).is_dir()] or [root]
    seen: Set[Path] = set()
    for search_root in roots:
        if not search_root.is_dir():
            continue
        for path in _walk(search_root, TEST_FILE_GLOBS):
            if path in seen:
                continue
            seen.add(path)
            parsed = _parse(path, root)
            if parsed is None:
                corpus.unparseable.append(_relpath(path, root))
            else:
                corpus.files.append(parsed)

    corpus.production = [p for p in _walk(root, ("*.py",)) if p not in seen]
    _parse_production(corpus, root)
    return corpus


def _parse_production(corpus: "Corpus", root: Path) -> None:
    """Parse every production module ONCE, for every rule that reads them.

    Two rules read production - `mock_drift` resolves patch targets against it
    and `entry_point_diff` reads what it declares - and each parsing the tree
    itself means two full walks of a branch's source inside a static tier whose
    whole budget is under four seconds fleet-wide. Parsed here, shared there.

    A file that will not parse is COUNTED, not skipped. Both rules that read
    production report FEWER findings when one exists, so the bias runs toward
    clean, and an unrecorded lean toward clean is the shape this lane exists
    to catch.
    """
    for path in corpus.production:
        try:
            corpus.production_trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, OSError, UnicodeDecodeError) as exc:
            corpus.production_unparseable.append(_relpath(path, root))
            logger.warning(
                f"[AUDIT-TESTS] production file will not parse, rules read less than the tree holds: {path} ({exc})"
            )


def _parse(path: Path, root: Path) -> Optional[TestFile]:
    """Parse one test file, or None when it will not parse or read.

    Never raises past its own edge. One unparseable file in a fleet sweep must
    not take the other seventeen branches down with it — it is counted and
    published, which is the difference between a measurement with a hole in it
    and a measurement that silently stopped.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError) as exc:
        logger.warning(f"[AUDIT-TESTS] test file will not parse, no nominator cleared it: {path} ({exc})")
        return None

    relpath = _relpath(path, root)
    parsed = TestFile(path=path, relpath=relpath, source=source, tree=tree)
    parsed.units = _units_in(tree, relpath)
    return parsed


# =============================================================================
# SHARED PREDICATES - what more than one rule asks of a unit
# =============================================================================


def asserts_in(unit: TestUnit) -> List[ast.Assert]:
    """Every `assert` statement inside a test unit."""
    return [node for node in ast.walk(unit.node) if isinstance(node, ast.Assert)]


def dotted_name(node: ast.AST) -> str:
    """`a.b.c` for an attribute/name chain, or "" for anything else."""
    parts: List[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _oracle_name(node: ast.AST) -> str:
    """The oracle a Call node names, or "" when it is not one."""
    if not isinstance(node, ast.Call):
        return ""
    name = dotted_name(node.func)
    tail = name.rsplit(".", 1)[-1]
    return name if (tail in ORACLE_CALL_NAMES or tail.startswith(MOCK_ASSERT_PREFIX)) else ""


def _with_oracle_names(node: ast.AST) -> List[str]:
    """Oracles opened by a `with` block, e.g. `with pytest.raises(...)`."""
    if not isinstance(node, ast.With):
        return []
    return [name for item in node.items if (name := _oracle_name(item.context_expr))]


def oracle_calls_in(unit: TestUnit) -> List[str]:
    """Non-assert oracles: `pytest.raises`, `pytest.fail`, `mock.assert_*`.

    A bare trailing call CAN be a working exception oracle (TAXONOMY rule 7's
    own caveat), so this list is what stops the no-oracle rule from convicting
    a test that really does check something. It is deliberately generous:
    static NOMINATES.
    """
    found: List[str] = []

    for node in ast.walk(unit.node):
        if name := _oracle_name(node):
            found.append(name)
        found.extend(_with_oracle_names(node))

    return found


def string_constants(node: ast.AST) -> List[str]:
    """Every string literal under a node. Docstrings included by design."""
    return [child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)]


def nomination(
    species: str,
    unit: TestUnit,
    why: str,
    *,
    verdict: str = VERDICT_SUSPECT,
    line: Optional[int] = None,
    evidence: Optional[Dict[str, object]] = None,
) -> dict:
    """One nomination row, in the shape Law S7b and Law M11 both require."""
    row = {
        "species": species,
        "file": unit.relpath,
        "line": line or unit.lineno,
        "nodeid": unit.nodeid,
        "test": unit.name,
        "verdict": verdict,
        "why": why,
        "deletion_safety": dict(DELETION_SAFETY_UNPROBED),
    }
    if evidence:
        row["evidence"] = dict(evidence)
    return row
