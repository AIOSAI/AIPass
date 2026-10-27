# =================== AIPass ====================
# Name: collection.py
# Description: the corpus definition - which test functions the inventory counts
# Version: 1.0.3
# Created: 2026-09-01
# Modified: 2026-10-27
# =============================================

"""
THE CORPUS DEFINITION, stated in code rather than assumed.

Counts test FUNCTIONS (not pytest items: `@parametrize` expands one into many)
under pytest's own rules: methods only in `Test*` classes, production never
walked. The audit-tests lane's `corpus.py` is deliberately generous for
nomination, so the two definitions stay separate. `testpaths` and
`norecursedirs` come from the repo-root `pyproject.toml`; without `tomllib`
the defaults are used and recorded."""

import ast
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger

#: pytest's own defaults, used when the config file cannot be read.
DEFAULT_TESTPATHS: tuple = ("tests", "src")
DEFAULT_NORECURSEDIRS: tuple = ("*.egg-info", ".*", "__pycache__", "build", "dist", "node_modules", "venv")
DEFAULT_PYTHON_FILES: tuple = ("test_*.py", "*_test.py")
DEFAULT_PYTHON_CLASSES: tuple = ("Test*",)
DEFAULT_PYTHON_FUNCTIONS: tuple = ("test*",)


@dataclass
class CorpusRules:
    """The collection rules actually in force, and where they came from."""

    testpaths: Tuple[str, ...]
    norecursedirs: Tuple[str, ...]
    python_files: Tuple[str, ...]
    python_classes: Tuple[str, ...]
    python_functions: Tuple[str, ...]
    config_source: str
    config_note: str = ""

    def as_dict(self) -> dict:
        """The rules as a publishable block."""
        return {
            "testpaths": list(self.testpaths),
            "norecursedirs": list(self.norecursedirs),
            "python_files": list(self.python_files),
            "python_classes": list(self.python_classes),
            "python_functions": list(self.python_functions),
            "config_source": self.config_source,
            "config_note": self.config_note,
            "unit": "test function (not pytest item - @parametrize expands one function into many items)",
        }


@dataclass
class TestFunction:
    """One collected test function and the source facts about it."""

    relpath: str
    class_path: Tuple[str, ...]
    name: str
    lineno: int
    end_lineno: int
    blame_from: int
    node: ast.AST = field(repr=False)

    @property
    def nodeid(self) -> str:
        """The pytest nodeid this function's items run under."""
        return "::".join((self.relpath, *self.class_path, self.name))

    @property
    def class_name(self) -> str:
        """The dotted class path, or "" for a module-level function."""
        return ".".join(self.class_path)


@dataclass
class Collection:
    """Every test function found, plus what could not be read."""

    root: Path
    rules: CorpusRules
    functions: List[TestFunction] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    unparseable: List[str] = field(default_factory=list)

    @property
    def per_file(self) -> Dict[str, int]:
        """How many test functions each file holds."""
        counts: Dict[str, int] = {}
        for func in self.functions:
            counts[func.relpath] = counts.get(func.relpath, 0) + 1
        return counts

    @property
    def per_class(self) -> Dict[Tuple[str, str], int]:
        """How many test functions each (file, class) holds."""
        counts: Dict[Tuple[str, str], int] = {}
        for func in self.functions:
            key = (func.relpath, func.class_name)
            counts[key] = counts.get(key, 0) + 1
        return counts


def read_rules(root: Path) -> CorpusRules:
    """The collection rules from the repo-root pyproject.toml, or the defaults.

    A missing key falls back to pytest's default for that key alone: a project that
    overrides one setting keeps the defaults it never overrode."""
    config = root / "pyproject.toml"
    table, source, note = _load_pytest_table(config)

    return CorpusRules(
        testpaths=_ini_list(table.get("testpaths", DEFAULT_TESTPATHS)),
        norecursedirs=_ini_list(table.get("norecursedirs", DEFAULT_NORECURSEDIRS)),
        python_files=_ini_list(table.get("python_files", DEFAULT_PYTHON_FILES)),
        python_classes=_ini_list(table.get("python_classes", DEFAULT_PYTHON_CLASSES)),
        python_functions=_ini_list(table.get("python_functions", DEFAULT_PYTHON_FUNCTIONS)),
        config_source=source,
        config_note=note,
    )


def _ini_list(value) -> Tuple[str, ...]:
    """A pytest list setting; a plain string is whitespace-separated, as pytest's ini `args` type reads it."""
    return tuple(value.split()) if isinstance(value, str) else tuple(value)


def _load_pytest_table(config: Path) -> Tuple[dict, str, str]:
    """The `[tool.pytest.ini_options]` table, its source, and any caveat."""
    try:
        import tomllib  # type: ignore[import-not-found]  # stdlib 3.11+, absent on 3.10
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            note = (
                f"neither tomllib nor tomli is available on this interpreter, so {config.name} was NOT read "
                f"and pytest's own defaults are in force; the corpus may differ from what CI collects"
            )
            logger.warning(f"[INVENTORY] {note}")
            return {}, "pytest defaults", note

    if not config.is_file():
        return {}, "pytest defaults", f"{config} does not exist, so pytest's own defaults are in force"

    try:
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning(f"[INVENTORY] {config} would not parse, falling back to pytest defaults: {exc}")
        return {}, "pytest defaults", f"{config.name} would not parse ({type(exc).__name__}), defaults are in force"

    table = parsed.get("tool", {}).get("pytest", {}).get("ini_options", {})
    if not table:
        return {}, "pytest defaults", f"{config.name} declares no [tool.pytest.ini_options] table"

    return table, str(config.name), ""


def collect(root: Path, rules: Optional[CorpusRules] = None) -> Collection:
    """Every test function pytest would collect from `root`, statically."""
    root = Path(root).resolve()
    rules = rules or read_rules(root)
    found = Collection(root=root, rules=rules)

    for path in _test_files(root, rules):
        relpath = path.relative_to(root).as_posix()
        tree = _parse(path)
        if tree is None:
            found.unparseable.append(relpath)
            continue
        found.files.append(relpath)
        found.functions.extend(_functions_in(tree, relpath, rules))

    return found


def _test_files(root: Path, rules: CorpusRules) -> List[Path]:
    """Every file matching `python_files` under the configured testpaths."""
    found: List[Path] = []
    seen: set = set()

    for start in _search_roots(root, rules):
        for path in sorted(start.rglob("*.py")):
            if path in seen or _pruned(path, root, rules.norecursedirs):
                continue
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in rules.python_files):
                seen.add(path)
                found.append(path)

    return sorted(found)


def _search_roots(root: Path, rules: CorpusRules) -> List[Path]:
    """The directories the walk starts from. An absent testpath is skipped."""
    roots = [root / name for name in rules.testpaths] or [root]
    return [start for start in roots if start.is_dir()]


def _pruned(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    """True when any directory on the way to `path` matches norecursedirs.

    Matched against directory BASENAMES as pytest does, so `.*` prunes `.archive`
    without pruning a checkout that sits under a dot path."""
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        # Outside the tree is an anomaly: prune against the absolute parts, and say so.
        logger.warning(f"[INVENTORY] {path} sits outside {root}; pruned against its absolute path instead")
        parts = path.parts[:-1]
    return any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in patterns)


def _parse(path: Path) -> Optional[ast.Module]:
    """The parsed module, or None when it will not parse or read.

    "Could not read" must never render as "read and found nothing"."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError) as exc:
        logger.warning(f"[INVENTORY] test file will not parse, its tests are absent from the inventory: {path} ({exc})")
        return None


def _functions_in(tree: ast.Module, relpath: str, rules: CorpusRules) -> List[TestFunction]:
    """Every collectable test function in a module, classes included."""
    return _walk_body(tree.body, relpath, (), rules)


def _walk_body(
    body: List[ast.stmt], relpath: str, class_path: Tuple[str, ...], rules: CorpusRules
) -> List[TestFunction]:
    """Test functions directly in a body, and inside its collectable classes."""
    found: List[TestFunction] = []

    for node in body:
        if _is_test_function(node, rules):
            found.append(_build(node, relpath, class_path))
        elif isinstance(node, ast.ClassDef) and _is_collectable_class(node, rules):
            found.extend(_walk_body(node.body, relpath, (*class_path, node.name), rules))

    return found


def _is_test_function(node: ast.AST, rules: CorpusRules) -> bool:
    """A function whose name matches `python_functions`."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(fnmatch.fnmatch(node.name, pattern) for pattern in rules.python_functions)


def _is_collectable_class(node: ast.ClassDef, rules: CorpusRules) -> bool:
    """A class pytest would collect: name matches, and it has no __init__.

    pytest skips a test class with a constructor and collects NOTHING from it."""
    if not any(fnmatch.fnmatch(node.name, pattern) for pattern in rules.python_classes):
        return False
    return not any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__" for child in node.body
    )


def _build(node, relpath: str, class_path: Tuple[str, ...]) -> TestFunction:
    """One TestFunction, with the line range blame will be attributed over.

    `blame_from` starts at the first decorator: a `@parametrize` table is part of the test."""
    decorator_lines = [dec.lineno for dec in node.decorator_list]
    return TestFunction(
        relpath=relpath,
        class_path=class_path,
        name=node.name,
        lineno=node.lineno,
        end_lineno=node.end_lineno or node.lineno,
        blame_from=min([node.lineno, *decorator_lines]),
        node=node,
    )
