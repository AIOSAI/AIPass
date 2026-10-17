# =================== AIPass ====================
# Name: gateway_boundary_check.py
# Description: Gateway Boundary Standards Checker Handler
# Version: 1.0.2
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""Gateway Boundary Standards Checker Handler.

A branch writes its own storage, and another's only through that branch's door: a hand
write is a second implementation of one format, drifting with nobody watching.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"
APPLIES_TO = "production"
# A file that does not parse: judged by nobody here, and said so (ruff convicts a parse error).
NOT_JUDGED = "Not judged: the file does not parse (ruff convicts that)"

# Private storage roots and the only branches that may write them by hand; anyone else
# goes through the owner's door.
_STORAGE_OWNERS: Dict[str, Tuple[str, ...]] = {
    ".ai_mail.local": ("ai_mail",),
    ".seedgo": ("seedgo",),
    ".daemon": ("daemon",),
    ".spawn": ("spawn",),
    ".flow": ("flow",),
}
# Absent, measured as false positives: ".trinity/" (every branch writes its own), ".claude/",
# ".aipass/" (shared namespaces), ".backup/" (three writers by design); see _OWNED_FILENAMES.

# A literal re-declaring one of these mirrors a constant the owner already has.
# AIPASS_REGISTRY.json and passport.json are absent: every branch locates and reads them.
_OWNED_FILENAMES: Dict[str, str] = {
    "aipass-hooks-muted": "hooks",
    "settings.local.json": "aipass",
}

# Writes only. "replace" is absent: str.replace() would make every reader of a foreign
# file look like a writer; os.replace is caught on the module receiver instead.
_WRITE_METHODS = frozenset({"write_text", "write_bytes", "mkdir", "unlink", "touch", "rmdir", "rename", "chmod"})
# os / shutil / tempfile functions, matched only when the receiver is that module.
_WRITE_FUNCS = frozenset(
    {"mkstemp", "mkdtemp", "remove", "rmtree", "copy", "copy2", "copyfile", "move", "replace", "unlink"}
)
_WRITE_MODULES = frozenset({"os", "shutil", "tempfile"})

_DOOR_MARKERS = ("drone", "route_command", "subprocess")


def _marker_of(value: str, markers: frozenset) -> set:
    """Markers this single string literal names, if any."""
    return {m for m in markers if value == m or value.startswith(m + "/")}


def _markers_in(node: ast.AST, tainted: Dict[str, set], markers: frozenset, follow_calls: bool = False) -> set:
    """Which foreign storage markers this expression's path derives from."""
    hit: set = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            hit |= _marker_of(sub.value, markers)
        elif isinstance(sub, ast.Name) and sub.id in tainted:
            hit |= tainted[sub.id]
        elif follow_calls and isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            hit |= tainted.get(sub.func.id, set())
    return hit


def _bind_targets(node: ast.AST) -> List[str]:
    """Names this statement binds, for the assignment forms that matter here."""
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _bound_value(node: ast.AST) -> ast.AST | None:
    """The expression an assignment binds, or None."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return node.value
    return None


def _returned_markers(func: ast.AST, tainted: Dict[str, set], markers: frozenset) -> set:
    """Markers a function hands back to its callers."""
    hit: set = set()
    for sub in ast.walk(func):
        if isinstance(sub, ast.Return) and sub.value is not None:
            hit |= _markers_in(sub.value, tainted, markers, follow_calls=True)
    return hit


def _taint_step(node: ast.AST, tainted: Dict[str, set], markers: frozenset) -> Tuple[set, List[str]]:
    """The markers this node contributes and the names they should bind to."""
    value = _bound_value(node)
    if value is not None:
        return _markers_in(value, tainted, markers, follow_calls=True), _bind_targets(node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _returned_markers(node, tainted, markers), [node.name]
    return set(), []


def _taint_size(tainted: Dict[str, set]) -> int:
    """Fixed-point measure: how much taint is currently known."""
    return len(tainted) + sum(len(v) for v in tainted.values())


def _tainted_names(tree: ast.AST, markers: frozenset) -> Dict[str, set]:
    """Names bound to another branch's storage, mapped to WHICH storage.

    Iterated to a fixed point: a constant defined below its use, or a helper's return, still taints.
    """
    tainted: Dict[str, set] = {}
    for _ in range(3):
        before = _taint_size(tainted)
        for node in ast.walk(tree):
            found, names = _taint_step(node, tainted, markers)
            for name in names if found else []:
                tainted.setdefault(name, set()).update(found)
        if _taint_size(tainted) == before:
            break
    return tainted


def _opens_for_writing(node: ast.Call) -> bool:
    """True if this open() call requests a truncating or appending mode."""
    candidates = list(node.args[1:]) + [kw.value for kw in node.keywords if kw.arg == "mode"]
    modes = [c.value for c in candidates if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    return any(m in mode for mode in modes for m in ("w", "a", "+"))


def _write_targets(node: ast.Call) -> List[ast.expr]:
    """Expressions this call would WRITE to, or [] if it is not a write."""
    func = node.func
    if isinstance(func, ast.Attribute):
        on_module = isinstance(func.value, ast.Name) and func.value.id in _WRITE_MODULES
        if on_module:
            if func.attr not in _WRITE_FUNCS:
                return []
            return list(node.args) + [kw.value for kw in node.keywords]
        return [func.value] if func.attr in _WRITE_METHODS else []
    if isinstance(func, ast.Name) and func.id == "open" and node.args:
        return [node.args[0]] if _opens_for_writing(node) else []
    return []


def _writes_to(tree: ast.AST, tainted: Dict[str, set], markers: frozenset) -> List[Tuple[int, set]]:
    """(line, markers) for every write call whose TARGET is another branch's storage.

    Precision lives here: the write and the foreign path must be the SAME path.
    """
    found: List[Tuple[int, set]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        hit: set = set()
        for target in _write_targets(node):
            hit |= _markers_in(target, tainted, markers)
        if hit:
            found.append((node.lineno, hit))
    return found


def _has_door(source: str) -> bool:
    """True if the file shows any sign of routing through an owner."""
    return any(marker in source for marker in _DOOR_MARKERS)


def _branch_of(module_path: str) -> str:
    """The branch a file belongs to, from its path."""
    parts = Path(module_path).as_posix().split("/")
    if "aipass" in parts:
        idx = parts.index("aipass")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _scan(source: str, branch: str) -> Optional[List[Tuple[int, str, str]]]:
    """Find writes into another branch's storage.

    Returns [(line, description, matched_text)], or None when the source does not parse.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        logger.info("[gateway_boundary] unparseable source: %s", e)
        return None

    foreign_dirs = {m for m, allowed in _STORAGE_OWNERS.items() if branch not in allowed}
    foreign_files = {f for f, owner in _OWNED_FILENAMES.items() if owner != branch}
    markers = frozenset(foreign_dirs | foreign_files)
    if not markers:
        return []

    tainted = _tainted_names(tree, markers)
    writes = _writes_to(tree, tainted, markers)
    if not writes:
        return []

    has_door = _has_door(source)
    violations: List[Tuple[int, str, str]] = []
    seen: set = set()

    for lineno, hit in sorted(writes):
        for marker in sorted(hit):
            if marker in seen:
                continue
            owner = _OWNED_FILENAMES.get(marker)
            if owner:
                seen.add(marker)
                violations.append(
                    (
                        lineno,
                        f"writes @{owner}'s own file '{marker}' by hand instead of through their door",
                        marker,
                    )
                )
                continue
            if has_door:
                continue
            seen.add(marker)
            owners = ", ".join(f"@{a}" for a in _STORAGE_OWNERS[marker])
            violations.append((lineno, f"writes '{marker}/' storage owned by {owners} with no door", marker))
    return violations


def _result(passed: bool, name: str, message: str, score: int) -> Dict:
    return {
        "passed": passed,
        "checks": [{"name": name, "passed": passed, "message": message}],
        "score": score,
        "standard": "GATEWAY_BOUNDARY",
    }


def _declined(result: Dict) -> Dict:
    """Mark a single-check result as a file this standard does not judge (out of the row's average)."""
    result["checks"][0]["declined"] = True
    return result


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for hand-written writes into another branch's storage."""
    path = Path(module_path)
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "gateway_boundary", bypass_rules=bypass_rules):
        return _result(True, "Bypassed", "Standard bypassed via .seedgo/bypass.json", 100)

    if path.suffix != ".py" or path.name == "__init__.py":
        return _declined(_result(True, "Gateway boundary", "File skipped (non-target)", 100))

    if not path.exists():
        return _result(False, "File exists", f"File not found: {module_path}", 0)

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.info("[gateway_boundary] cannot read %s: %s", path, e)
        return _result(False, "File readable", f"Error reading file: {e}", 0)

    branch = _branch_of(module_path)
    all_violations = _scan(source, branch)
    if all_violations is None:
        return _result(True, "Gateway boundary", NOT_JUDGED, 100)

    non_bypassed = [
        (ln, desc, txt)
        for ln, desc, txt in all_violations
        if not is_bypassed(module_path, "gateway_boundary", line=ln, bypass_rules=bypass_rules)
    ]

    if not non_bypassed:
        return _result(True, "Gateway boundary", "No cross-branch storage writes", 100)

    messages = [f"line {ln}: {desc}" for ln, desc, _ in non_bypassed]
    json_handler.log_operation("gateway_boundary_violation", {"file": module_path, "count": len(non_bypassed)})
    score = max(0, 100 - (len(non_bypassed) * 25))
    return {
        "passed": False,
        "checks": [{"name": "Gateway boundary", "passed": False, "message": msg} for msg in messages],
        "score": score,
        "standard": "GATEWAY_BOUNDARY",
    }
