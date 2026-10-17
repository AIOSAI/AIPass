# =================== AIPass ====================
# Name: corpus.py
# Description: static test corpus reader for the pytest_quality pack
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Static AST reader over a project's test files.

Stdlib-only so the pack lifts onto any Python project; nothing is imported or run.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple, TypeGuard, Union


TEST_FILE_GLOBS: tuple = ("test_*.py", "*_test.py")

#: The one copy every rule reads; `build` falls back to the whole tree when none exists.
TEST_DIRS: tuple = ("tests", "test")

SKIP_DIRS: frozenset = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".nox",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        "site-packages",
    }
)

#: Generous on purpose - see no_oracle.
ORACLE_CALL_NAMES: frozenset = frozenset({"raises", "warns", "fail", "approx", "xfail"})


@dataclass
class TestUnit:
    """One test function, with the coordinates a reader needs to find it."""

    name: str
    # Inline, not a module alias: the naming standard reads a CapWords assignment as a mis-cased constant.
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    relpath: str
    class_name: str = ""
    line: int = 0

    @property
    def nodeid(self) -> str:
        """The pytest-style identifier for this unit."""
        parts = [self.relpath]
        if self.class_name:
            parts.append(self.class_name)
        parts.append(self.name)
        return "::".join(parts)


@dataclass
class TestFile:
    """One parsed test file and the units inside it."""

    relpath: str
    tree: ast.Module
    units: List[TestUnit] = field(default_factory=list)


@dataclass
class Corpus:
    """Every test file under a root, parsed once."""

    root: Path
    files: List[TestFile] = field(default_factory=list)
    unparseable: List[str] = field(default_factory=list)
    unparseable_reasons: Dict[str, str] = field(default_factory=dict)
    #: Populated only by `build(..., with_production=True)`: parsing production is the expensive half.
    production_trees: Dict[str, ast.Module] = field(default_factory=dict)
    production_unparseable: List[str] = field(default_factory=list)

    def production_limits(self) -> str:
        """What this corpus could NOT read, or "" when whole; every with_production rule reports it."""
        if not self.production_unparseable:
            return ""
        return (
            f"{len(self.production_unparseable)} production file(s) could not be parsed and were "
            f"NOT read: {', '.join(sorted(self.production_unparseable)[:12])}"
        )

    def units(self) -> Iterator[TestUnit]:
        """Every test unit in the corpus, file order preserved."""
        for parsed in self.files:
            for unit in parsed.units:
                yield unit

    def unit_count(self) -> int:
        """How many test units were parsed."""
        return sum(len(f.units) for f in self.files)


# =============================================================================
# WALK + PARSE
# =============================================================================


def _walk(root: Path, patterns: Sequence[str]) -> List[Path]:
    """Every file under root matching any pattern, skipping vendor trees.

    Pruning is relative to the walk root: a checkout beneath `build/` must still be read.
    Dot directories are pruned because pytest's `norecursedirs` starts with `.*`.
    """
    found: List[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            parts = path.relative_to(root).parts[:-1]
            if any(part in SKIP_DIRS or part.startswith(".") for part in parts):
                continue
            if path.is_file():
                found.append(path)
    return sorted(set(found))


def _relpath(path: Path, root: Path) -> str:
    """Path relative to root as posix, falling back to the absolute string."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_test_function(node: ast.AST) -> TypeGuard[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    """True for a def or async def whose name pytest would collect.

    A fixture is never a unit, whatever its name: pytest does not collect it.
    """
    return (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
        and not any(_is_fixture_decorator(decorator) for decorator in node.decorator_list)
    )


def _is_fixture_decorator(decorator: ast.expr) -> bool:
    """True for ``@pytest.fixture``, ``@fixture`` and their called forms."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return dotted_name(target) in ("pytest.fixture", "fixture")


def _units_in_class(node: ast.ClassDef, relpath: str) -> List[TestUnit]:
    """Every test method directly inside one class body."""
    return [
        TestUnit(name=sub.name, node=sub, relpath=relpath, class_name=node.name, line=sub.lineno)
        for sub in node.body
        if _is_test_function(sub)
    ]


def _units_in(tree: ast.Module, relpath: str) -> List[TestUnit]:
    """Every test unit in a parsed module, module-level and in classes."""
    units: List[TestUnit] = []
    for node in tree.body:
        if _is_test_function(node):
            units.append(TestUnit(name=node.name, node=node, relpath=relpath, line=node.lineno))
        elif isinstance(node, ast.ClassDef):
            units.extend(_units_in_class(node, relpath))
    return units


def _parse(path: Path, root: Path) -> Tuple[Optional[TestFile], str]:
    """Parse one test file. Returns (file, "") or (None, reason).

    The reason travels in the return value: this pack has no logger, and a broken file must not read as empty.
    """
    relpath = _relpath(path, root)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return TestFile(relpath=relpath, tree=tree, units=_units_in(tree, relpath)), ""


def build(
    root: Path,
    test_dirs: Optional[Sequence[str]] = None,
    with_production: bool = False,
) -> Corpus:
    """Parse every test file under `root` into a Corpus."""
    root = Path(root)
    corpus = Corpus(root=root)

    # Filter by existence before `or [root]`: unfiltered, a non-empty test_dirs never reaches the fallback.
    roots = [root / name for name in (test_dirs or []) if (root / name).is_dir()] or [root]
    seen: Set[Path] = set()
    for search_root in roots:
        if not search_root.is_dir():
            continue
        for path in _walk(search_root, TEST_FILE_GLOBS):
            if path in seen:
                continue
            seen.add(path)
            parsed, reason = _parse(path, root)
            if parsed is None:
                corpus.unparseable.append(_relpath(path, root))
                corpus.unparseable_reasons[_relpath(path, root)] = reason
            else:
                corpus.files.append(parsed)

    if with_production:
        _parse_production(corpus, root, seen)
    return corpus


def _parse_production(corpus: Corpus, root: Path, test_paths: Set[Path]) -> None:
    """Parse every non-test `.py` file under root into `production_trees`.

    Test-shaped files anywhere are excluded, not just the ones the test walk reached.
    """
    test_shaped = {p for pattern in TEST_FILE_GLOBS for p in _walk(root, (pattern,))}
    for path in _walk(root, ("*.py",)):
        if path in test_paths or path in test_shaped:
            continue
        relpath = _relpath(path, root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            corpus.production_unparseable.append(relpath)
            continue
        corpus.production_trees[relpath] = tree


def dotted_name(node: ast.AST) -> str:
    """The dotted source spelling of a call target, or "" when unreadable."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def asserts_in(unit: TestUnit) -> List[ast.Assert]:
    """Every assert statement anywhere inside the unit."""
    return [n for n in ast.walk(unit.node) if isinstance(n, ast.Assert)]


def oracle_calls_in(unit: TestUnit) -> List[str]:
    """Oracle-shaped calls the unit makes, by dotted name."""
    names: List[str] = []
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name and _is_oracle_name(name):
                names.append(name)
    return sorted(set(names))


def string_constants(node: ast.AST) -> List[str]:
    """Every string literal under a node. Docstrings included by design."""
    return [c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)]


def _is_oracle_name(name: str) -> bool:
    """True when a dotted call name reads as an oracle."""
    tail = name.rsplit(".", 1)[-1]
    return tail in ORACLE_CALL_NAMES or tail.startswith("assert_")


def measure(branch_path: Union[str, Path]) -> int:
    """How many test files this pack reads in a project. The banner's number.

    The engine's `files_checked` counts apps/ files no rule here opens (`pack.json` corpus.measured_by).
    """
    scanned = build(Path(branch_path), test_dirs=TEST_DIRS)
    return len(scanned.files) + len(scanned.unparseable)
