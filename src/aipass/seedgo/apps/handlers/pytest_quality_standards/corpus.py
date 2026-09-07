# =================== AIPass ====================
# Name: corpus.py
# Description: static test corpus reader for the pytest_quality pack
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Static AST reader over a project's test files.

DELIBERATELY STDLIB-ONLY. This pack is generic - the whole point of splitting
it out of `aipass_standards` is that it lifts onto any Python project without
carrying AIPass with it. The moment this module imports a framework package,
that claim stops being true, so it imports `ast`, `pathlib`, `dataclasses` and
`typing` and nothing else, forever.

THIS IS A SECOND CORPUS READER AND THAT IS ON THE RECORD. `tests_pytest_standards/
corpus.py` already parses test files the same way, and copying it is exactly the
species this campaign exists to kill. The reason it is still the right call: that
one serves an EXECUTION pack that runs suites inside a copied tree, and it imports
the framework logger to do it. Binding a portable pack to an internal execution
lane would cost the portability that justifies the pack existing. Consolidating
the two readers is a real candidate once v5 is proven - it is logged as such
rather than left for someone to discover as duplication.

NO EXECUTION HAPPENS HERE. Nothing is imported, nothing is run: a file that
would crash on import is still readable as text, and a static reader must never
be the thing that runs a stranger's test suite.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple, TypeGuard, Union

# =============================================================================
# CONSTANTS
# =============================================================================

#: Filename shapes pytest itself collects. Kept as the pytest defaults rather
#: than a house convention, because a generic pack has no house.
TEST_FILE_GLOBS: tuple = ("test_*.py", "*_test.py")

#: Directories that never hold a project's own tests. Walking them wastes time
#: and, worse, scores a project on its dependencies' test suites.
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

#: Callables that are oracles even though they are not `assert` statements.
#: Generous ON PURPOSE - see the module docstring of no_oracle_check.
ORACLE_CALL_NAMES: frozenset = frozenset({"raises", "warns", "fail", "approx", "xfail"})


# =============================================================================
# DATA
# =============================================================================


@dataclass
class TestUnit:
    """One test function, with the coordinates a reader needs to find it."""

    name: str
    # pytest collects both spellings, so every reader here has to accept both.
    # Spelled inline rather than as a module-level alias: the naming standard
    # reads a CapWords module-level assignment as a mis-cased constant, and a
    # one-file readability win is not worth touching a checker that gates
    # eighteen branches at 100. The gap is logged, not worked around silently.
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
    #: relpath -> why it could not be parsed. Populated alongside `unparseable`
    #: so a report can say WHAT was wrong, not merely that something was.
    unparseable_reasons: Dict[str, str] = field(default_factory=dict)
    #: relpath -> parsed module, for every NON-test .py file under the root.
    #: Rules that compare tests against the code they cover read this; it is
    #: populated only when `build(..., with_production=True)` asks for it,
    #: because most rules never look at production and parsing it is the
    #: expensive half of the walk.
    production_trees: Dict[str, ast.Module] = field(default_factory=dict)
    #: Production files that would not parse. A rule reading production must be
    #: able to say its answer is INCOMPLETE rather than quietly report a hole
    #: that is really an unreadable file - see `production_limits`.
    production_unparseable: List[str] = field(default_factory=list)

    def production_limits(self) -> str:
        """What this corpus could NOT read, as a sentence, or "" when whole.

        A rule that reports "production declares X but no test mentions it"
        is only honest if it can also say "and N files were unreadable". A
        hole and an unread file look identical from the outside.
        """
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

    PRUNING IS RELATIVE TO THE WALK ROOT, NOT ABSOLUTE. Testing `path.parts`
    against SKIP_DIRS reads the whole absolute path, so a project that merely
    LIVES under a directory called `build`, `dist`, `venv` or `node_modules`
    had every one of its test files skipped - and the result was not an error
    but the silent, plausible "no test files found". A checkout's parent
    directories are the user's business, not the walker's; only what is inside
    the project can be vendored. Measured before the fix: a project checked out
    beneath a directory named `build`, holding tests/test_a.py, collected 0 units.
    """
    found: List[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
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

    A TypeGuard rather than a plain bool so the narrowing survives the call:
    without it every caller has to re-assert the isinstance a second time to
    read `.name`, and the second assertion is the one that drifts.
    """
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")


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

    THE REASON IS CARRIED OUT, NOT DROPPED. Returning a bare None would make an
    unreadable file indistinguishable from an empty one at the call site, and
    the caller could only report a count. This pack has no framework logger to
    fall back on - it is stdlib-only by design - so the failure travels in the
    return value instead of being logged and forgotten. That is what keeps a
    broken file from reading as a clean one.
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
    """Parse every test file under `root` into a Corpus.

    `test_dirs` narrows the walk when a project keeps tests in a known place.
    Passing None walks the whole tree, which is what an unknown project needs.

    `with_production` additionally parses every non-test `.py` file. Off by
    default: most rules never read production, and parsing it roughly doubles
    the walk. Rules that DO read it must also report `production_limits()`.
    """
    root = Path(root)
    corpus = Corpus(root=root)

    # FILTER BY EXISTENCE, THEN FALL BACK. The obvious spelling -
    # `[root / n for n in (test_dirs or [])] or [root]` - can never reach the
    # fallback: a non-empty `test_dirs` always yields a non-empty list, whether
    # or not any of those directories exist. The walk then finds nothing and the
    # project reads as having no tests. Most of the pytest ecosystem does not
    # keep tests in a top-level `tests/`, so the pack's portability claim died
    # on this line. Measured before the fix: a project with src/tests/ plus a
    # root-level test file reported "no test files found" while a whole-tree
    # walk found both units.
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

    "NON-TEST" MEANS TEST-SHAPED ANYWHERE, NOT MERELY COLLECTED. Excluding only
    the paths the test walk happened to reach lets a `test_*.py` living outside
    `test_dirs` fall through into production - and then BOTH halves are wrong at
    once: pytest really would collect that file, so a genuine test goes
    unmeasured, and a test-only constant gets reported as an unexercised
    production entry point. Measured before the fix: a project with tests/test_a.py
    plus src/test_stray.py scored one unit while entry_point_diff read the stray
    file's COMMANDS tuple as a real production declaration.
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


# =============================================================================
# ORACLE READING
# =============================================================================


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
    """Oracle-shaped calls the unit makes, by dotted name.

    Counts `pytest.raises`/`warns`/`fail`/`approx`/`xfail` and any method whose
    name starts with `assert_` (the unittest and mock spellings).

    `with pytest.raises(...)` - the commonest oracle in any corpus - needs no
    special case: `ast.walk` descends into a `withitem`'s `context_expr`, so the
    plain Call arm already sees it. An earlier version carried an explicit
    With/AsyncWith branch; deleting it left every behavioural pin green, which
    is the definition of code that is not running the show. It is gone rather
    than pinned, so nobody later "fixes" a bug by editing a dead branch.
    """
    names: List[str] = []
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name and _is_oracle_name(name):
                names.append(name)
    return sorted(set(names))


def string_constants(node: ast.AST) -> List[str]:
    """Every string literal under a node. Docstrings included by design.

    A rule asking "does anything mention this verb" wants the docstring to
    count: a verb named only in prose is still a verb the file knows about,
    and excluding docstrings would manufacture holes that are not there.
    """
    return [c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)]


def _is_oracle_name(name: str) -> bool:
    """True when a dotted call name reads as an oracle."""
    tail = name.rsplit(".", 1)[-1]
    return tail in ORACLE_CALL_NAMES or tail.startswith("assert_")
