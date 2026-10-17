# =================== AIPass ====================
# Name: corpus.py
# Description: the parsed test corpus every static nominator reads
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""The test corpus, parsed ONCE and handed to every nominator.

Every rule is AST, never grep: a text match matches the prose describing the rule.
An unparseable file is reported, never skipped: "could not check" must never read
as "checked and clean". Nothing here scores or emits a delete-family verdict (S7b).
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set

from aipass.prax import logger

SKIP_DIRS: frozenset = frozenset(
    {"__pycache__", ".git", ".venv", "node_modules", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".chroma"}
)

TEST_FILE_GLOBS: tuple = ("test_*.py", "*_test.py")

#: Names that make a call an oracle even without an `assert` statement.
ORACLE_CALL_NAMES: frozenset = frozenset({"raises", "fail", "warns", "deprecated_call", "approx", "xfail"})

#: Mock assertion methods. A test asserting an interaction has a real oracle.
MOCK_ASSERT_PREFIX = "assert_"

#: A subset of the core's ALLOWED_VERDICTS, so a nominator cannot reach for a refused word.
VERDICT_SUSPECT = "suspect"
VERDICT_IMPROVE = "improve"

#: Law M11: the deletion-safety probe is not built; an absent field must not look like a pass.
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

    `unparseable` is a field, not a log line: every group publishes that count.
    """

    root: Path
    files: List[TestFile] = field(default_factory=list)
    unparseable: List[str] = field(default_factory=list)
    production: List[Path] = field(default_factory=list)

    production_trees: Dict[Path, ast.Module] = field(default_factory=dict)

    #: Published: an unreadable production file biases production rules toward clean.
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


def _walk(root: Path, patterns: Sequence[str]) -> List[Path]:
    """Every file under `root` matching any pattern, skipping SKIP_DIRS."""
    found: List[Path] = []
    for path in sorted(root.rglob("*.py")):
        # Relative to the walk root: a target living under `.venv/` or `node_modules/`
        # must not lose every file. Dot-directories are pruned as pytest's own
        # `norecursedirs` does, so no rule reads a file pytest never loads.
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts[:-1]):
            continue
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if any(path.match(pattern) for pattern in patterns):
            found.append(path)
    return found


def _relpath(path: Path, root: Path) -> str:
    """Posix path relative to the corpus root, or the absolute path."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
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

    `test_dirs` None walks the whole tree, which an unknown external target needs.
    """
    root = Path(root)
    corpus = Corpus(root=root)

    # Filter by existence first, or a non-empty `test_dirs` of missing dirs never falls back.
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

    An unparseable file is counted, not skipped: production rules then lean toward clean.
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

    Never raises: one bad file must not take a fleet sweep down.
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

    Deliberately generous: a bare trailing call can be a working exception oracle.
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
