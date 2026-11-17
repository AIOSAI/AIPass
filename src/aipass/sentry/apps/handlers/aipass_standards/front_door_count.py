# =================== AIPass ====================
# Name: front_door_count.py
# Description: Front-door detection: every cross-branch import that reaches under another branch's apps/
# Version: 1.3.0
# Created: 2026-11-16
# Modified: 2026-11-17
# =============================================

"""Front-door detection, shared by the ``front_door`` standard and the ``front-door`` verb.

The rule: an import crossing into another branch goes through its front door,
``from aipass.<branch> import <name>``. One whose path reaches under ``apps`` is a finding.
This file only reads; ``front_door_check.py`` scores and waives, the verb counts the fleet.
"""

import ast
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards.applicability import is_retired_path, is_test_path
from aipass.sentry.apps.handlers.aipass_standards.check_support import read_text
from aipass.sentry.apps.handlers.aipass_standards.string_imports import iter_string_imports
from aipass.sentry.apps.handlers.context_standards.name_ratchet import tracked_files
from aipass.sentry.apps.handlers.json import json_handler

TAG = "front_door"
#: Finding kinds: the segment after ``apps``. ``door`` and ``elsewhere`` are cross-branch and clean.
APPS_KINDS = ("modules", "handlers", "other")
VIAS = ("statement", "type_only", "string")
_PACKAGE_TAILS = frozenset({"apps", "modules", "handlers"})
OUTSIDE = "(no branch)"


class Reading(NamedTuple):
    """One cross-branch import site in a file."""

    line: int
    target: str
    branch: str
    kind: str
    via: str
    names: Tuple[str, ...] = ()


class Site(NamedTuple):
    """A reading with the file it sits in."""

    rel: str
    owner: str
    test: bool
    reading: Reading


def target_branch(dotted: str) -> str:
    """The branch a dotted target belongs to: the segment after ``aipass.``, however deep it nests."""
    parts = dotted.split(".")
    return parts[1] if parts[0] == "aipass" and len(parts) > 1 else ""


def kind_of(dotted: str) -> str:
    """``modules``/``handlers``/``other`` under apps, ``door`` for ``aipass.<b>``, else ``elsewhere``."""
    parts = dotted.split(".")
    if len(parts) == 2:
        return "door"
    if "apps" not in parts[2:]:
        return "elsewhere"
    after = parts[parts.index("apps", 2) + 1 :]
    return after[0] if after and after[0] in ("modules", "handlers") else "other"


def _is_type_checking(test: ast.expr) -> bool:
    """``if TYPE_CHECKING:`` or ``if typing.TYPE_CHECKING:``."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _type_only_nodes(tree: ast.AST) -> Set[int]:
    """Ids of every node inside a TYPE_CHECKING block's body (its else runs, so it is not type-only)."""
    found: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            found.update(id(inner) for stmt in node.body for inner in ast.walk(stmt))
    return found


def _statement_targets(node: ast.stmt) -> List[Tuple[str, Tuple[str, ...]]]:
    """(dotted target, names) per import a statement makes; relative imports are always own-branch."""
    if isinstance(node, ast.Import):
        return [(alias.name, ()) for alias in node.names]
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        names = tuple(alias.name for alias in node.names)
        if node.module == "aipass":
            return [(f"aipass.{name}", ()) for name in names]
        return [(node.module, names)]
    return []


def scan_source(source: str, file_branch: str) -> List[Reading]:
    """Every cross-branch ``aipass.`` import site in a source; an unparseable one raises SyntaxError.

    Statements are read from the parse tree, top level, in functions and in TYPE_CHECKING
    blocks; strings only as the first argument of an import or patch call
    (``iter_string_imports``). A docstring, comment or message is never read.
    """
    tree = ast.parse(source)
    type_only = _type_only_nodes(tree)
    found: List[Reading] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        via = "type_only" if id(node) in type_only else "statement"
        for dotted, names in _statement_targets(node):
            branch = target_branch(dotted)
            if branch and branch != file_branch:
                found.append(Reading(node.lineno, dotted, branch, kind_of(dotted), via, names))
    for line, dotted in iter_string_imports(source, marker=".apps"):
        branch, kind = target_branch(dotted), kind_of(dotted)
        if branch and branch != file_branch and kind in APPS_KINDS:
            found.append(Reading(line, dotted, branch, kind, "string"))
    return sorted(found)


def owner_of(rel: str) -> str:
    """The branch a repo-relative path sits in: the directory after ``src/aipass/``, else empty."""
    parts = rel.split("/")
    return parts[2] if parts[:2] == ["src", "aipass"] and len(parts) > 3 else ""


def owner_of_path(file_path: str) -> str:
    """The branch an absolute path sits in, read from its last ``src/aipass/`` pair, else empty."""
    parts = Path(file_path).resolve().parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index - 1] == "src" and parts[index] == "aipass":
            return owner_of("/".join(parts[index - 1 :]))
    return ""


def _literal_names(value: ast.expr, lists: Dict[str, List[str]]) -> Optional[List[str]]:
    """The strings a list/tuple literal holds, a ``*NAME`` unpacking an earlier top-level list; else None.

    A dict literal holds its string keys, and ``list(NAME)`` the earlier list: a door's name-to-home table.
    """
    if isinstance(value, ast.Dict):
        return [k.value for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "list"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
    ):
        return lists.get(value.args[0].id)
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    names: List[str] = []
    for elt in value.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            names.append(elt.value)
        elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
            names += lists.get(elt.value.id, [])
    return names


def door_names(source: str) -> Tuple[str, ...]:
    """The names a package top file hands out: ``__all__`` when literal, else its public top-level bindings."""
    tree = ast.parse(source)
    bound: List[str] = []
    lists: Dict[str, List[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            held = _literal_names(node.value, lists)
            if held is not None and node.targets[0].id == "__all__":
                return tuple(sorted(held))
            if held is not None:
                lists[node.targets[0].id] = held
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound += [(a.asname or a.name).split(".")[0] for a in node.names]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.append(node.name)
        elif isinstance(node, ast.Assign):
            bound += [t.id for t in node.targets if isinstance(t, ast.Name)]
    return tuple(sorted({name for name in bound if not name.startswith("_")}))


def doors(root: Path, errors: List[str]) -> Dict[str, Tuple[str, ...]]:
    """Every branch's door names, empty for a top file that hands out nothing; an unreadable one joins ``errors``."""
    found: Dict[str, Tuple[str, ...]] = {}
    for top in sorted((root / "src" / "aipass").glob("*/__init__.py")):
        source = read_text(top, tag=TAG)
        if source is None:
            errors.append(f"{top.parent.name}/__init__.py: cannot be read")
            continue
        try:
            found[top.parent.name] = door_names(source)
        except (SyntaxError, ValueError) as exc:
            logger.warning("[%s] unparseable door %s: %s", TAG, top, exc)
            errors.append(f"{top.parent.name}/__init__.py: unparseable door ({exc})")
    return found


def scan_tracked(root: Path, files: Optional[Sequence[str]] = None) -> Dict:
    """Every tracked ``.py`` file's cross-branch sites. Never prints; a tree git cannot list is an error.

    A file in a retired folder (``tests/parked`` among them) is skipped as the audit skips it, and named.
    """
    errors: List[str] = []
    if files is None:
        files, reason = tracked_files(root)
        if reason:
            errors.append(reason)
    sites: List[Site] = []
    unparseable: List[str] = []
    skipped_retired: List[str] = []
    files_read = 0
    for rel in files:
        path = root / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        if is_retired_path(rel):
            skipped_retired.append(rel)
            continue
        source = read_text(path, tag=TAG)
        if source is None:
            errors.append(f"{rel}: cannot be read")
            continue
        files_read += 1
        owner = owner_of(rel)
        try:
            readings = scan_source(source, owner)
        except (SyntaxError, ValueError) as exc:
            logger.warning("[%s] unparseable %s: %s", TAG, rel, exc)
            unparseable.append(rel)
            continue
        sites.extend(Site(rel, owner or OUTSIDE, is_test_path(rel), r) for r in readings)
    json_handler.log_operation("front_door_scanned", {"files": files_read, "sites": len(sites), "errors": len(errors)})
    found = doors(root, errors)
    return {
        "sites": sites,
        "doors": found,
        "errors": errors,
        "unparseable": unparseable,
        "files_read": files_read,
        "skipped_retired": skipped_retired,
    }


def target_modules(reading: Reading) -> List[str]:
    """What a door would hand out for this site, below ``aipass.<branch>.``: a package import names each name."""
    tails = [reading.target]
    if reading.names and reading.target.rsplit(".", 1)[-1] in _PACKAGE_TAILS:
        tails = [f"{reading.target}.{name}" for name in reading.names]
    return [tail.split(".", 2)[-1] for tail in tails]


def tally(sites: Iterable[Site]) -> Dict[str, Dict]:
    """Per-branch counters (``out:``/``in:`` keys), per-target module counters, and fleet totals."""
    rows: Dict[str, Counter] = {}
    modules: Dict[str, Counter] = {}
    fleet: Counter = Counter()
    for site in sites:
        r, scope = site.reading, "tests" if site.test else "prod"
        target = rows.setdefault(r.branch, Counter())
        if r.kind not in APPS_KINDS:
            target[f"in:{r.kind}:{scope}"] += 1
            fleet[f"{r.kind}:{scope}"] += 1
            continue
        rows.setdefault(site.owner, Counter())[f"out:{scope}"] += 1
        target.update([f"in:{scope}", f"in:{r.kind}", f"in:{r.via}"])
        fleet.update([f"finding:{scope}", f"{r.kind}:{scope}", f"{r.via}:{scope}"])
        modules.setdefault(r.branch, Counter()).update(target_modules(r))
    return {"rows": rows, "modules": modules, "fleet": fleet}
