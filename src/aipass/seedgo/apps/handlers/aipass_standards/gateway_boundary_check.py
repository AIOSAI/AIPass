# =================== AIPass ====================
# Name: gateway_boundary_check.py
# Description: Gateway Boundary Standards Checker Handler
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Gateway Boundary Standards Checker Handler.

A branch may write its OWN storage. It may ask another branch to write theirs,
through that branch's door. What it may not do is reach into another branch's
storage and write it by hand: two implementations of one format, drifting
apart with nobody watching, and the owner's own rules bypassed.

Patrick's directive (2026-08-17), which this standard encodes: "@api should be
only doing api calls. api is api thats it."
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"
APPLIES_TO = "production"

# Storage markers and who is ALLOWED to write them by hand. Anyone else must
# go through the owner's door. The list is deliberately short: a marker earns
# a place here only when a branch's own storage is named by a path literal
# that another branch could plausibly write.
# PRIVATE storage roots only - one owner, and no branch has any business
# writing another's by hand. Population today: 0. That is a guard, not a
# failure to find anything, and it is stated rather than hidden.
_STORAGE_OWNERS: Dict[str, Tuple[str, ...]] = {
    ".ai_mail.local": ("ai_mail",),
    ".seedgo": ("seedgo",),
    ".daemon": ("daemon",),
    ".spawn": ("spawn",),
    ".flow": ("flow",),
}
# DELIBERATELY ABSENT, each removed after measuring the false positives it
# produced rather than on taste:
#   ".trinity/" - EVERY branch writes its own; that is the memory protocol.
#       Flagged @aipass/profile.py:61 writing its own local.json. The
#       cross-branch writers (@memory, @spawn) are the legitimate ones, so the
#       directory cannot separate right from wrong. 1 hit, 1 false.
#   ".claude/" and ".aipass/" - SHARED project-config namespaces, not private
#       storage. @commons, @skills, @trigger, @hooks each create their own
#       file or subdir under them, correctly. 4 hits, 4 false.
#   ".backup/" - three legitimate writers by design (@backup, @memory rollover,
#       @flow archives), which is a shared lane wearing a dot-prefix.
# The FILES inside a shared namespace still have owners - that is what
# _OWNED_FILENAMES catches, and it is where this standard's precision lives.
# NOT a private storage root, measured: ".aipass/". Four branches (@commons,
# @skills, @trigger, @hooks) create their OWN subdir or file under it, which
# is the shared project-config namespace working as designed - the same shape
# as a branch writing its own key into .claude/. Listing it produced 4 hits,
# all legitimate. The namespace is shared; the FILES inside it have owners,
# which is what _OWNED_FILENAMES is for.

# Filenames a single branch owns outright. Re-declaring one of these as a
# literal is the loudest signal in this checker: the constant already exists
# in the owner's source, so a second copy is a mirror by construction.
# NOT in this map, deliberately, and measured: AIPASS_REGISTRY.json and
# passport.json. Every branch LOCATES and READS those by design - that is
# address resolution, not mirroring. Including them flagged 47 files across
# 13 branches, all of them reading. A standard that floods is worse than no
# standard.
_OWNED_FILENAMES: Dict[str, str] = {
    "aipass-hooks-muted": "hooks",
    "settings.local.json": "aipass",
}

# Call shapes that WRITE. Read-only access to another branch's storage is a
# different and much weaker concern - this standard is about writes.
# Methods on a PATH OBJECT. "replace" is deliberately absent: str.replace() is
# everywhere and Path.replace() is rare, so including it made every module that
# reads a foreign file and massages the text look like a writer (measured: it
# was the sole cause of 2 of 10 hits, @hooks' loader and @prax's detector, both
# pure readers). os.replace is caught below on the module receiver instead.
_WRITE_METHODS = frozenset({"write_text", "write_bytes", "mkdir", "unlink", "touch", "rmdir", "rename", "chmod"})
# Functions on the os / shutil / tempfile MODULE - matched only when the
# receiver is that module, never on an arbitrary object.
_WRITE_FUNCS = frozenset(
    {"mkstemp", "mkdtemp", "remove", "rmtree", "copy", "copy2", "copyfile", "move", "replace", "unlink"}
)
_WRITE_MODULES = frozenset({"os", "shutil", "tempfile"})

# Evidence that the file talks to owners properly rather than by hand.
_DOOR_MARKERS = ("drone", "route_command", "subprocess")


def _marker_of(value: str, markers: frozenset) -> set:
    """Markers this single string literal names, if any."""
    return {m for m in markers if value == m or value.startswith(m + "/")}


def _markers_in(node: ast.AST, tainted: Dict[str, set], markers: frozenset, follow_calls: bool = False) -> set:
    """Which foreign storage markers this expression's path derives from.

    Empty when the expression is not a foreign path at all. This is what keeps
    a violation attributed to the storage it really writes rather than to every
    foreign name the module happens to mention.
    """
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

    Iterated to a fixed point so a constant defined below its use still taints,
    and so a helper returning a tainted path taints its own call sites.
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
    """Expressions this call would WRITE to, or [] if it is not a write.

    A method on a path object writes its receiver; os/shutil/tempfile functions
    write whichever argument names the path; open() writes its first argument.
    """
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

    The whole precision of this standard is here: a module that merely reads a
    foreign file, or writes its own while mentioning theirs, is not a violation.
    The write and the foreign path must be the SAME path.
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


def _scan(source: str, branch: str) -> List[Tuple[int, str, str]]:
    """Find writes into another branch's storage.

    Returns list of (line_number, description, matched_text).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        logger.info("[gateway_boundary] unparseable source: %s", e)
        return []

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


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for hand-written writes into another branch's storage."""
    path = Path(module_path)
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "gateway_boundary", bypass_rules=bypass_rules):
        return _result(True, "Bypassed", "Standard bypassed via .seedgo/bypass.json", 100)

    if path.suffix != ".py" or path.name == "__init__.py":
        return _result(True, "Gateway boundary", "File skipped (non-target)", 100)

    if not path.exists():
        return _result(False, "File exists", f"File not found: {module_path}", 0)

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.info("[gateway_boundary] cannot read %s: %s", path, e)
        return _result(False, "File readable", f"Error reading file: {e}", 0)

    branch = _branch_of(module_path)
    all_violations = _scan(source, branch)

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
