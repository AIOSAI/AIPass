# =================== AIPass ====================
# Name: mock_drift_check.py
# Description: nominator - patch-target resolution (MOCK-DRIFT)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""TAXONOMY rule 4 — a patch whose target is a MODULE answers anything.

Reference: mock_drift.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_mock_drift"

#: Keyword arguments that make a mock refuse unknown attributes. Any one of
#: them acquits the patch outright.
ACQUITTING_KEYWORDS: frozenset = frozenset({"spec", "spec_set", "autospec", "new_callable"})

PATCH_NAMES: frozenset = frozenset({"patch", "mock.patch", "patch.object", "unittest.mock.patch"})

#: Reads production, so an unparseable production file under-reports; `nominators`
#: merges the corpus's count into this group's limits when set.
READS_PRODUCTION = True

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 4 - patch-target resolution",
    "species": ["MOCK-DRIFT"],
    "flags": [
        "@patch('a.b.c') where c resolves to a MODULE file inside the target - the whole "
        "module becomes a MagicMock that answers every attribute, including deleted ones",
    ],
    "exempts": [
        "spec=, spec_set=, autospec=True or new_callable= - a specced mock raises on an "
        "attribute the real object does not have, which is the whole property at stake",
        "a patch target that resolves to no file in the target tree is NOT nominated - the "
        "rule reports what it can resolve and says so, rather than guessing",
    ],
    "fix": "patch the attribute, not the module - or add autospec=True. One line per decorator.",
    "limits": [
        "resolution is by FILESYSTEM, not by import: Law M10 forbids importing the subject, "
        "so a module created dynamically is invisible here",
        "an f-string target resolves only when every interpolation is a module-level string "
        "constant; anything computed is unreadable and is never nominated",
    ],
    "evidence": (
        "deleting auth.validate_credentials from @api left 46/46 tests green "
        "(TAXONOMY corpus row 23); 25 instances found in one half of one branch"
    ),
}


def _module_paths(root: Path) -> Set[str]:
    """Every dotted module path that exists as a FILE under the target.

    Every suffix is recorded: a test patches `aipass.daemon.apps.x`, not a branch-relative path.
    """
    found: Set[str] = set()

    for path in sorted(root.rglob("*.py")):
        if any(part in corpus.SKIP_DIRS for part in path.parts):
            continue
        relative = path.relative_to(root)
        parts = list(relative.parts)
        parts[-1] = relative.stem
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

    f-strings over module-level constants resolve: `f"{_MOD}.x"` is the dominant real spelling.
    """
    if not node.args:
        return None

    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value

    if not isinstance(first, ast.JoinedStr):
        return None

    parts = []
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


def _is_acquitted(node: ast.Call) -> str:
    """The acquitting keyword this patch carries, or "" when it carries none."""
    for keyword in node.keywords:
        if keyword.arg and keyword.arg in ACQUITTING_KEYWORDS:
            return keyword.arg
    return ""


def _patch_calls(unit: corpus.TestUnit) -> List[ast.Call]:
    """Every `patch(...)` call reaching this unit, decorator or context manager."""
    calls: List[ast.Call] = []

    for decorator in unit.decorators:
        if isinstance(decorator, ast.Call) and corpus.dotted_name(decorator.func) in PATCH_NAMES:
            calls.append(decorator)

    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in PATCH_NAMES:
            calls.append(node)

    return calls


def _imported_module_names(tree: ast.Module, modules: Set[str]) -> Set[str]:
    """The local names ONE module binds to another module by import."""
    names: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(_from_import_stmt(node, modules))
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name in modules)

    return names


def _from_import_stmt(node: ast.Import, modules: Set[str]) -> Set[str]:
    """The local names a plain `import x.y` statement binds to a module."""
    names: Set[str] = set()
    for alias in node.names:
        if alias.name in modules or alias.name.split(".")[-1] in modules:
            names.add(alias.asname or alias.name.split(".")[0])
    return names


def _module_bound_names(scanned: corpus.Corpus, modules: Set[str]) -> Dict[str, Set[str]]:
    """Per production module, the names it binds to another MODULE by import.

    Tells a module (`json_handler`) from an imported object (`console`) a last-segment match conflates.
    """
    bound: Dict[str, Set[str]] = {}

    for path, tree in scanned.production_trees.items():
        # Unioned, not assigned: two modules can share a stem, and overwriting drops bindings.
        bound.setdefault(path.stem, set()).update(_imported_module_names(tree, modules))

    return bound


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every unspecced patch whose target names a MODULE, not an attribute."""
    modules = _module_paths(scanned.root)
    bound = _module_bound_names(scanned, modules)
    rows: List[dict] = []
    seen: Set[tuple] = set()

    for parsed in scanned.files:
        constants = _module_constants(parsed)
        for unit in parsed.units:
            for call in _patch_calls(unit):
                target = _patch_target(call, constants)
                if not target or _is_acquitted(call):
                    continue

                why = _drift_reason(target, modules, bound)
                if not why:
                    continue

                key = (unit.nodeid, target, call.lineno)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    corpus.nomination(
                        "MOCK-DRIFT",
                        unit,
                        why,
                        verdict=corpus.VERDICT_IMPROVE,
                        line=call.lineno,
                        evidence={"target": target},
                    )
                )

    return rows


def _drift_reason(target: str, modules: Set[str], bound: Dict[str, Set[str]]) -> str:
    """Why this patch target is a module patch, or "" when it is not one."""
    if target in modules:
        return (
            f"patches '{target}', which resolves to a module file in this target - the module "
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
