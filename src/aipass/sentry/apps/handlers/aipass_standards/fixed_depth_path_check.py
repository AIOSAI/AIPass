# =================== AIPass ====================
# Name: fixed_depth_path_check.py
# Description: Fixed Depth Path Standards Checker - a path climbed a fixed depth off __file__ that a wheel answers wrong
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Fixed Depth Path Standards Checker

Reference: fixed_depth_path.md. A climb is ``.parents[n]``, ``.parent`` or ``os.path.dirname`` off
``__file__``, ``<aipass module>.__file__`` or ``find_spec("aipass...").origin``, followed through names
bound to one. Two sites, each at its line and enclosing function:

- the climb leaves ``src/aipass``: on a wheel it lands in site-packages or the interpreter's lib directory;
- a climb joined to a folder the wheel does not ship (a dot name, ``logs``, ``system_logs``, ``*_json``):
  on a wheel that state is written inside the installed package.

A climb that stays inside the package and names shipped files is the package's own data and passes.
"""

import ast
from collections import Counter
from fnmatch import fnmatch
from functools import lru_cache, partial
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.sentry.apps.handlers.aipass_standards.check_support import (
    find_enclosing_function,
    parse,
    read_text,
    result,
    tail_name,
)
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE, is_bypassed
from aipass.sentry.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "FIXED_DEPTH_PATH"
STANDARD_KEY = "fixed_depth_path"

#: src/aipass, to tell a package origin (``x/__init__.py``) from a module origin (``x.py``).
_PACKAGES = Path(__file__).resolve().parents[4]
#: Wraps that keep the path they are given: ``Path(p)``, ``os.path.abspath(p)``, ``p.resolve()``.
_KEEPS = frozenset({"Path", "PurePath", "abspath", "realpath", "normpath", "resolve", "absolute"})
#: Joins that put a segment under a path.
_JOINS = frozenset({"join", "joinpath"})
#: Folders git ignores (the repo .gitignore: logs/, system_logs/, **/*_json/), so the wheel never ships them.
_IGNORED = frozenset({"logs", "system_logs"})

_parse = partial(parse, tag=STANDARD_KEY)
_read = partial(read_text, tag=STANDARD_KEY)
_result = partial(result, standard=STANDARD)


@lru_cache(maxsize=4)
def _ignore_patterns(gitignore: str, stamp: int) -> Tuple[str, ...]:
    """The repo .gitignore's patterns; ``stamp`` (mtime) keys the cache so an edited file is read again."""
    text = Path(gitignore).read_text(encoding="utf-8")
    # shortcut: negations (!) are skipped; today they only re-include spawn's templates
    lines = (line.strip() for line in text.splitlines())
    return tuple(line.strip("/") for line in lines if line and not line.startswith(("#", "!")))


def _git_ignored(rel: str, segment: str, repo: Path) -> bool:
    """Whether the repo .gitignore names ``rel`` (repo-relative) or the bare ``segment``: the wheel skips it."""
    gitignore = repo / ".gitignore"
    if not gitignore.is_file():
        return False
    for pattern in _ignore_patterns(str(gitignore), gitignore.stat().st_mtime_ns):
        if fnmatch(rel, pattern) if "/" in pattern else fnmatch(segment, pattern):
            return True
    return False


def unshipped(segment: str, landing: Optional[Path] = None) -> bool:
    """A name the wheel does not ship: a dot name (builds skip dot paths), logs, *_json, or one git ignores there."""
    dot_name = segment.startswith(".") and segment.strip(".") != ""
    if dot_name or segment in _IGNORED or segment.endswith("_json"):
        return True
    if landing is None:
        return False
    parts = landing.parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index : index + 2] == ("src", "aipass"):
            repo = Path(*parts[:index])
            return _git_ignored((landing / segment).relative_to(repo).as_posix(), segment, repo)
    return False


def _depth_below_packages(parts: Tuple[str, ...]) -> Optional[int]:
    """Levels from a file up to src/aipass, from its path parts; None when it is not under src/aipass."""
    for index in range(len(parts) - 2, -1, -1):
        if parts[index : index + 2] == ("src", "aipass"):
            return len(parts) - index - 2
    return None


def _module_depth(dotted: str) -> Optional[int]:
    """Levels from an aipass module's origin file up to src/aipass."""
    parts = dotted.split(".")
    if parts[0] != "aipass":
        return None
    is_package = len(parts) == 1 or (_PACKAGES.joinpath(*parts[1:])).is_dir()
    return len(parts) if is_package else len(parts) - 1


def _dotted(node: ast.AST) -> str:
    """``a.b.c`` for a Name/Attribute chain, else empty."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else ""
    return ""


def _spec_of(node: ast.AST) -> Optional[int]:
    """The origin depth of ``find_spec("aipass...")``, else None."""
    if isinstance(node, ast.Call) and tail_name(node.func) == "find_spec" and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return _module_depth(arg.value)
    return None


class _Reader:
    """Reads climbs in one file: names bound to a climb or a spec are followed."""

    def __init__(self, file_depth: int, imported: Optional[Dict[str, Tuple[int, str]]] = None):
        self.file_depth = file_depth
        self.names: Dict[str, int] = {}
        self.specs: Dict[str, int] = {}
        #: Where each followed name was counted, as ``apps/config.py:22``; set for names from another file.
        self.origins: Dict[str, str] = {}
        self.lines: Dict[str, int] = {}
        for name, (headroom, origin) in (imported or {}).items():
            self.names[name], self.origins[name] = headroom, origin

    def base(self, node: ast.AST) -> Optional[int]:
        """Levels above src/aipass of a path a climb may start from."""
        if isinstance(node, ast.Name):
            return self.file_depth if node.id == "__file__" else self.names.get(node.id)
        if isinstance(node, ast.Attribute) and node.attr == "__file__":
            return _module_depth(_dotted(node.value))
        if isinstance(node, ast.Attribute) and node.attr == "origin":
            depth = _spec_of(node.value)
            if depth is None and isinstance(node.value, ast.Name):
                depth = self.specs.get(node.value.id)
            return depth
        return None

    def climb(self, node: ast.AST) -> Optional[int]:
        """Levels left above src/aipass for a path built from a base by keeping wraps and fixed climbs."""
        found = self.base(node)
        if found is not None:
            return found
        if isinstance(node, ast.Call):
            name = tail_name(node.func)
            if name in _KEEPS:
                inner = node.args[0] if node.args else None
                if name in ("resolve", "absolute") and isinstance(node.func, ast.Attribute):
                    inner = node.func.value
                return self.climb(inner) if inner is not None else None
            if name == "dirname" and node.args:
                inner = self.climb(node.args[0])
                return None if inner is None else inner - 1
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            inner = self.climb(node.value)
            return None if inner is None else inner - 1
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, int):
                inner = self.climb(node.value.value)
                return None if inner is None else inner - index.value - 1
        return None

    def inner_of(self, node: ast.AST) -> Optional[ast.AST]:
        """The path a climbing step climbs from."""
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return node.value
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            return node.value.value
        if isinstance(node, ast.Call) and tail_name(node.func) == "dirname" and node.args:
            return node.args[0]
        return None

    def bind(self, tree: ast.Module) -> None:
        """Follow names bound exactly once in the file to a climb or a spec, in source order."""
        stores = Counter(n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
        for name in [n for n in self.origins if stores[n]]:
            del self.names[name], self.origins[name]
        assigns = sorted(
            (n for n in ast.walk(tree) if isinstance(n, ast.Assign) and len(n.targets) == 1),
            key=lambda n: n.lineno,
        )
        for node in assigns:
            target = node.targets[0]
            # a name bound twice (a walk up to a marker, a fallback) holds no one depth
            if not isinstance(target, ast.Name) or stores[target.id] != 1:
                continue
            spec = _spec_of(node.value)
            if spec is not None:
                self.specs[target.id] = spec
                continue
            climbed = self.climb(node.value)
            if climbed is not None:
                self.names[target.id], self.lines[target.id] = climbed, node.lineno

    def root_named(self, node: ast.AST) -> str:
        """`` (NAME counted at file:line)`` when the path starts at a name followed from another file, else ""."""
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in self.origins:
                return f" ({child.id} counted at {self.origins[child.id]})"
        return ""


def _source_root(path: Path) -> Optional[Path]:
    """src/aipass above ``path``, or None."""
    parts = path.parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index : index + 2] == ("src", "aipass"):
            return Path(*parts[: index + 2])
    return None


def _module_file(packages: Path, dotted: str) -> Optional[Path]:
    """The file of an aipass module under ``packages``: ``x/y.py`` or ``x/y/__init__.py``."""
    base = packages.joinpath(*dotted.split(".")[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imported_roots(tree: ast.Module, path: Path, seen: frozenset) -> Dict[str, Tuple[int, str]]:
    """Names this file imports from its OWN branch that are bound there to a climb: alias -> (headroom, origin)."""
    packages = _source_root(path)
    if packages is None or len(path.relative_to(packages).parts) < 2:
        return {}
    branch = path.relative_to(packages).parts[0]
    found: Dict[str, Tuple[int, str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith(f"aipass.{branch}.")):
            continue
        home = _module_file(packages, node.module or "")
        if home is None or home in seen:
            continue
        roots = _roots_of(home, seen | {home})
        found.update({a.asname or a.name: roots[a.name] for a in node.names if a.name in roots})
    return found


def _roots_of(path: Path, seen: frozenset) -> Dict[str, Tuple[int, str]]:
    """Every name ``path`` binds (or re-exports) to a climb: name -> (headroom, origin)."""
    source = _read(path)
    tree = _parse(source) if source is not None else None
    depth = _depth_below_packages(path.parts)
    if tree is None or depth is None:
        return {}
    reader = _Reader(depth, _imported_roots(tree, path, seen))
    reader.bind(tree)
    branch_rel = Path(*path.relative_to(_source_root(path) or path).parts[1:]).as_posix()
    roots = {name: (headroom, reader.origins.get(name, "")) for name, headroom in reader.names.items()}
    for name in reader.lines:
        roots[name] = (reader.names[name], f"{branch_rel}:{reader.lines[name]}")
    return roots


def _joined_segment(node: ast.AST) -> Optional[Tuple[ast.AST, str]]:
    """(the path joined to, its first literal segment) for ``p / "x"`` and ``join(p, "x")``."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = node.left, node.right
    elif isinstance(node, ast.Call) and tail_name(node.func) in _JOINS:
        args = list(node.args)
        if tail_name(node.func) == "joinpath" and isinstance(node.func, ast.Attribute):
            args = [node.func.value, *args]
        if len(args) < 2:
            return None
        left, right = args[0], args[1]
    else:
        return None
    if isinstance(right, ast.Constant) and isinstance(right.value, str) and right.value:
        return left, right.value.strip("/").split("/")[0]
    return None


def scan(source: str, file_depth: int, path: Optional[Path] = None) -> Optional[List[Tuple[int, str, str]]]:
    """(line, finding, joined segment or "") for every site in one source; None when Python cannot parse it.

    With ``path``, a root bound in another file of the same branch and imported here is followed too.
    """
    tree = _parse(source)
    if tree is None:
        return None
    reader = _Reader(file_depth, _imported_roots(tree, path, frozenset({path})) if path else None)
    reader.bind(tree)
    packages = _source_root(path) if path else None
    found: List[Tuple[int, str, str]] = []
    for node in ast.walk(tree):
        inner = reader.inner_of(node)
        after = reader.climb(node) if inner is not None else None
        before = reader.climb(inner) if inner is not None else None
        line = getattr(node, "lineno", 0)
        if after is not None and before is not None and before >= 0 > after:
            found.append((line, "leaves the installed aipass package" + reader.root_named(node), ""))
            continue
        joined = _joined_segment(node)
        if joined is None:
            continue
        headroom = reader.climb(joined[0])
        # shortcut: the landing is read along THIS file's path; a root imported from a deeper file may land elsewhere
        landing = packages.joinpath(*path.relative_to(packages).parts[:headroom]) if packages and path else None
        if headroom is not None and headroom >= 0 and unshipped(joined[1], landing):
            note = reader.root_named(joined[0])
            found.append((line, f"joins a fixed-depth climb to {joined[1]!r}{note}", joined[1]))
    return sorted(set(found))


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Fixed depth path", "passed": passed, "message": message}]


def _message(file_name: str, line: int, finding: str, segment: str) -> str:
    """One site's finding with what a wheel does to it and the cure."""
    if not segment:
        return (
            f"{file_name}:{line} a fixed-depth climb off the file {finding}: on a wheel it lands in site-packages "
            "or the interpreter's lib directory - take the home from a resolver (env, registry walk), never a depth"
        )
    return (
        f"{file_name}:{line} {finding}: {segment!r} is not shipped in the wheel, so on a wheel this state is written "
        "inside the installed package - put it under the state root a resolver returns (aipass.prax branch_state_root)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Convict every unwaived fixed-depth climb that a wheel install answers wrong."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .sentry/bypass.json"), 100)
    path = Path(module_path)
    depth = _depth_below_packages(path.resolve().parts)
    if depth is None:
        return _result(True, _one_check(True, "File is outside src/aipass: not in the wheel, no climb to judge"), 100)
    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)
    found = scan(source, depth, path.resolve())
    if found is None:
        return _result(False, _one_check(False, "Cannot be read as Python, climbs unjudged"), 0)
    tree = ast.parse(source)
    checks = []
    for line, finding, segment in found:
        holder = find_enclosing_function(tree, line)
        function = holder.name if holder else FILE_SCOPE
        if is_bypassed(module_path, STANDARD_KEY, line, bypass_rules, function):
            continue
        message = _message(path.name, line, finding, segment)
        site = {"name": "Fixed depth path", "passed": False, "line": line, "function": function}
        checks.append({**site, "message": message})
    if not checks:
        return _result(True, _one_check(True, "No fixed-depth climb a wheel would answer wrong"), 100)
    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "sites": len(checks)}
    )
    return _result(False, checks, 0)
