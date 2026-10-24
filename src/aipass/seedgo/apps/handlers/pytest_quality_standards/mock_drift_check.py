# =================== AIPass ====================
# Name: mock_drift_check.py
# Description: v5 - does a patch's replacement match its target (whole module; function over a class)
# Version: 1.1.1
# Created: 2026-09-01
# Modified: 2026-10-24
# =============================================

"""Does this patch replace a function, or a whole module?

Reference: mock_drift.md
"""

import ast
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "mock_drift"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Keyword arguments that make a mock refuse unknown attributes; any one acquits.
ACQUITTING_KEYWORDS: frozenset = frozenset({"spec", "spec_set", "autospec", "new_callable"})

#: `patch.object` is deliberately absent: its first argument is an object, never a readable target.
PATCH_NAMES: frozenset = frozenset({"patch", "mock.patch", "unittest.mock.patch"})

MAX_REPORTED: int = 12


def _module_paths(scanned: corpus.Corpus) -> Set[str]:
    """Every dotted module path the corpus read, plus every suffix of each.

    From the corpus, not a second disk walk, so it describes the same files as the import-binding map.
    """
    found: Set[str] = set()
    relpaths = list(scanned.production_trees) + [parsed.relpath for parsed in scanned.files]

    for relpath in relpaths:
        pure = PurePosixPath(relpath)
        parts = list(pure.parts[:-1]) + [pure.stem]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        for start in range(len(parts)):
            found.add(".".join(parts[start:]))

    return found


def _module_constants(parsed: corpus.TestFile) -> Dict[str, str]:
    """Module-level `NAME = "string"` bindings, for resolving f-string targets."""
    constants: Dict[str, str] = {}
    for node in parsed.tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _patch_target(node: ast.Call, constants: Dict[str, str]) -> Optional[str]:
    """The dotted string a patch call targets, or None when it cannot be read.

    Only interpolations of module-level string constants resolve. Anything
    computed returns None, and an unreadable target is never flagged.
    """
    if not node.args:
        return None

    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value

    if not isinstance(first, ast.JoinedStr):
        return None

    parts: List[str] = []
    for piece in first.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name):
            resolved = constants.get(piece.value.id)
            if resolved is None:
                return None
            parts.append(resolved)
        else:
            return None

    return "".join(parts)


def _acquitting_keyword(node: ast.Call) -> str:
    """The acquitting keyword this patch carries, or "" when it carries none."""
    for keyword in node.keywords:
        if keyword.arg and keyword.arg in ACQUITTING_KEYWORDS:
            return keyword.arg
    return ""


def _patch_calls(unit: corpus.TestUnit) -> List[ast.Call]:
    """Every `patch(...)` call reaching this unit, decorator or context manager.

    One walk: `ast.walk` already descends into `decorator_list`; a second pass double-counts.
    """
    return [
        node
        for node in ast.walk(unit.node)
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in PATCH_NAMES
    ]


def _imported_module_names(tree: ast.Module, modules: Set[str]) -> Set[str]:
    """The local names ONE module binds to another module by import."""
    names: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(_plain_import_names(node, modules))
        elif isinstance(node, ast.ImportFrom):
            prefix = f"{node.module}." if node.module else ""
            names.update(
                alias.asname or alias.name for alias in node.names if _names_a_module(prefix + alias.name, modules)
            )

    return names


def _names_a_module(dotted: str, modules: Set[str]) -> bool:
    """Whether a dotted import names a file here: two trailing segments must match, never a bare stem.

    `from aipass.prax import logger` is another package's logger, not this branch's logger.py.
    """
    parts = dotted.split(".")
    if len(parts) == 1:
        return dotted in modules
    return any(".".join(parts[start:]) in modules for start in range(len(parts) - 1))


def _plain_import_names(node: ast.Import, modules: Set[str]) -> Set[str]:
    """The local names a plain `import x.y` statement binds to a module."""
    names: Set[str] = set()
    for alias in node.names:
        if _names_a_module(alias.name, modules):
            names.add(alias.asname or alias.name.split(".")[0])
    return names


def _module_bound_names(scanned: corpus.Corpus, modules: Set[str]) -> Dict[str, Set[str]]:
    """Per production file stem, the names it binds to another MODULE by import.

    Unioned, not assigned: two files can share a stem, and overwriting drops bindings silently.
    """
    bound: Dict[str, Set[str]] = {}

    for relpath, tree in scanned.production_trees.items():
        stem = PurePosixPath(relpath).stem
        bound.setdefault(stem, set()).update(_imported_module_names(tree, modules))

    return bound


def _drift_reason(target: str, modules: Set[str], bound: Dict[str, Set[str]]) -> str:
    """Why this patch target is a module patch, or "" when it is not one."""
    if target in modules:
        return (
            f"patches '{target}', which resolves to a module file in this project - the module "
            f"becomes a MagicMock that answers every attribute, so deleting the production "
            f"function this test is about would not fail it"
        )

    if "." not in target:
        return ""

    parent, attribute = target.rsplit(".", 1)
    owner = parent.rsplit(".", 1)[-1]
    if attribute in bound.get(owner, set()):
        return (
            f"patches '{target}', where '{owner}' binds '{attribute}' to a MODULE by import - "
            f"the patch replaces that module with a MagicMock that answers every attribute, so "
            f"deleting the production function this test is about would not fail it"
        )

    return ""


def unit_flags(
    unit: corpus.TestUnit,
    constants: Dict[str, str],
    modules: Set[str],
    bound: Dict[str, Set[str]],
) -> List[Dict]:
    """Every module-patch finding in one unit, with the evidence for each."""
    rows: List[Dict] = []
    seen: Set[tuple] = set()

    for call in _patch_calls(unit):
        target = _patch_target(call, constants)
        if not target or _acquitting_keyword(call):
            continue

        reason = _drift_reason(target, modules, bound)
        if not reason:
            continue

        key = (target, call.lineno)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "nodeid": unit.nodeid,
                "line": call.lineno,
                "species": "MOCK-DRIFT",
                "target": target,
                "reason": reason,
            }
        )

    return rows


def find_module_patches(scanned: corpus.Corpus) -> List[Dict]:
    """Every unspecced patch whose target names a MODULE, not an attribute."""
    modules = _module_paths(scanned)
    bound = _module_bound_names(scanned, modules)
    rows: List[Dict] = []

    for parsed in scanned.files:
        constants = _module_constants(parsed)
        for unit in parsed.units:
            rows.extend(unit_flags(unit, constants, modules, bound))

    return rows


def _module_files(scanned: corpus.Corpus) -> Dict[str, Set[str]]:
    """Dotted module path (every suffix) -> the production relpaths it can name."""
    files: Dict[str, Set[str]] = {}
    for relpath in scanned.production_trees:
        pure = PurePosixPath(relpath)
        parts = list(pure.parts[:-1]) + [pure.stem]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for start in range(len(parts)):
            files.setdefault(".".join(parts[start:]), set()).add(relpath)
    return files


def _resolve_module(dotted: str, files: Dict[str, Set[str]]) -> str:
    """The ONE production file a dotted import names, or "" when none or ambiguous.

    Keeps at least two segments, so `from thirdparty import worker` never lands on a stem match.
    """
    parts = dotted.split(".")
    shortest = min(2, len(parts))
    for start in range(len(parts) - shortest + 1):
        found = files.get(".".join(parts[start:]), set())
        if found:
            return next(iter(found)) if len(found) == 1 else ""
    return ""


def _imported_modules(tree: ast.Module) -> Dict[str, str]:
    """Local name -> dotted path, for every name a test file binds by import."""
    names: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _file_functions(tree: ast.Module) -> Set[str]:
    """Names the test file binds ONLY to a def - a plain function, never a class."""
    defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    return defs - classes


def _is_function_standin(value: ast.expr, functions: Set[str]) -> bool:
    """A lambda, a plain function from this file, or a functools.partial - none has a class surface."""
    if isinstance(value, ast.Lambda):
        return True
    if isinstance(value, ast.Name):
        return value.id in functions
    return isinstance(value, ast.Call) and corpus.dotted_name(value.func) in ("partial", "functools.partial")


def _class_names_in(node: ast.expr) -> List[ast.Name]:
    """The bare names in an isinstance/issubclass second argument, tuple or single."""
    items = node.elts if isinstance(node, ast.Tuple) else [node]
    return [item for item in items if isinstance(item, ast.Name)]


def _class_use(node: ast.AST, name: str) -> str:
    """`line:how` when this one node uses `name` as a class, else ""."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == name:
        return f"{node.lineno}:{name}.{node.attr}"
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in ("isinstance", "issubclass"):
        if len(node.args) == 2 and any(item.id == name for item in _class_names_in(node.args[1])):
            return f"{node.lineno}:{corpus.dotted_name(node.func)} second argument"
    if isinstance(node, ast.ClassDef) and any(isinstance(base, ast.Name) and base.id == name for base in node.bases):
        return f"{node.lineno}:used as a base of {node.name}"
    return ""


def _class_uses(tree: ast.Module, name: str) -> List[str]:
    """Where a module's own source uses `name` AS A CLASS: `line:how`, in line order.

    A bare call `Name(...)` is not a class use: a function answers it.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any((a.asname or a.name.split(".")[0]) == name for a in node.names):
            return []

    uses = {use for use in (_class_use(node, name) for node in ast.walk(tree)) if use}
    return sorted(uses, key=lambda use: int(use.split(":", 1)[0]))


def _owned_defs(parsed: corpus.TestFile) -> List[tuple]:
    """(nodeid, def) for every module-level def and every method, helpers included."""
    owned: List[tuple] = []
    for node in parsed.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owned.append((f"{parsed.relpath}::{node.name}", node))
        elif isinstance(node, ast.ClassDef):
            owned.extend(
                (f"{parsed.relpath}::{node.name}::{sub.name}", sub)
                for sub in node.body
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return owned


def _standin_row(call: ast.Call, nodeid: str, context: Dict) -> Optional[Dict]:
    """One finding for a `.setattr(module, "Name", stand-in)` call, or None."""
    if len(call.args) != 3 or not isinstance(call.args[0], ast.Name):
        return None
    name_arg = call.args[1]
    if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
        return None
    if not _is_function_standin(call.args[2], context["functions"]):
        return None
    dotted = context["imports"].get(call.args[0].id, "")
    relpath = _resolve_module(dotted, context["files"]) if dotted else ""
    if not relpath:
        return None
    uses = _class_uses(context["trees"][relpath], name_arg.value)
    if not uses:
        return None
    first_line, first_how = uses[0].split(":", 1)
    more = f", +{len(uses) - 1} more" if len(uses) > 1 else ""
    return {
        "nodeid": nodeid,
        "line": call.lineno,
        "species": "CLASS-STANDIN",
        "target": f"{dotted}.{name_arg.value}",
        "reason": (
            f"replaces '{name_arg.value}' in {relpath} with a function, but that module uses it as a "
            f"class ({first_how} at {relpath}:{first_line}{more}) - the stand-in has no such surface, "
            f"so that path dies with 'function' object has no attribute, and only on a host that reaches it"
        ),
    }


def _setattr_calls(owner: ast.AST) -> List[ast.Call]:
    """Every `<anything>.setattr(...)` call under one def - monkeypatch's spelling."""
    return [
        node
        for node in ast.walk(owner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr"
    ]


def find_class_standins(scanned: corpus.Corpus) -> List[Dict]:
    """Every `.setattr(module, "Name", lambda/function)` where the module reads Name as a class."""
    files = _module_files(scanned)
    rows: List[Dict] = []

    for parsed in scanned.files:
        context = {
            "files": files,
            "trees": scanned.production_trees,
            "imports": _imported_modules(parsed.tree),
            "functions": _file_functions(parsed.tree),
        }
        for nodeid, owner in _owned_defs(parsed):
            rows.extend(row for row in (_standin_row(c, nodeid, context) for c in _setattr_calls(owner)) if row)

    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    The score is per unit: counting findings could push the score negative.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its patches replace functions or modules.

    bypass_rules is accepted for the scoring-API contract and unread: advisory gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # Built before the empty-path return: an unparseable file must never read as an absent one.
    unreadable: List[Dict] = _limit_checks(scanned)

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Patch target", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    module_rows = find_module_patches(scanned)
    standin_rows = find_class_standins(scanned)
    flagged = module_rows + standin_rows
    units = flagged_nodeids(module_rows)
    standins = flagged_nodeids(standin_rows)
    # A stand-in found in a helper names the helper, which is not a unit, so the
    # places to look can outnumber the units: floored at 0, never negative.
    score = max(0, int(((total - len(flagged_nodeids(flagged))) / total) * 100))
    checks: List[Dict] = [
        {
            "name": "Patch target",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units patch attributes rather than whole modules"
                if not units
                else (
                    f"{len(units)}/{total} test units patch a whole module: "
                    + ", ".join(units[:MAX_REPORTED])
                    + (f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else "")
                )
            ),
        },
        {
            "name": "Class stand-in",
            "passed": not standins,
            "message": (
                "no lambda or plain function is patched over a class its module reads as a class"
                if not standins
                else (
                    f"{len(standins)} place(s) patch a function over a class its module reads as a class: "
                    + ", ".join(standins[:MAX_REPORTED])
                    + (f" (+{len(standins) - MAX_REPORTED} more)" if len(standins) > MAX_REPORTED else "")
                )
            ),
        },
    ]

    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }


def _limit_checks(scanned: corpus.Corpus) -> List[Dict]:
    """The lines saying what could NOT be read, test side and production side.

    Published beside the score: an unread production file hides its findings.
    """
    checks: List[Dict] = []

    if scanned.unparseable:
        checks.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

    production_limit = scanned.production_limits()
    if production_limit:
        checks.append(
            {
                "name": "Production readable",
                "passed": True,
                "message": (
                    f"{production_limit} - a patch target inside one of them cannot be resolved, "
                    f"so this score is biased toward FEWER findings"
                ),
            }
        )

    return checks
