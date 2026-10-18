# =================== AIPass ====================
# Name: discarded_patch_check.py
# Description: Discarded Patch Standards Checker Handler
# Version: 1.1.0
# Created: 2026-09-22
# Modified: 2026-10-17
# =============================================

"""Discarded Patch Standards Checker Handler

Reference: discarded_patch.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "DISCARDED_PATCH"
STANDARD_KEY = "discarded_patch"

PRODUCT = "aipass"

#: A branch's test package: what is imported from it is test code, not the product.
TESTS = "tests"

TEST_PREFIX = "test_"

_PATCH_VERBS: frozenset[str] = frozenset({"patch", "object"})

#: Keywords that DRIVE the product or shape the mock: the replacement is in use.
_HANDED_OVER: frozenset[str] = frozenset(
    {"return_value", "side_effect", "new", "new_callable", "wraps", "autospec", "spec"}
)

#: The fixture name pytest injects. Any other spelling is not judged.
_MONKEYPATCH = "monkeypatch"

#: A mock class whose bare call builds a throwaway nothing can be asked.
_THROWAWAY: frozenset[str] = frozenset({"Mock", "MagicMock", "AsyncMock"})

CURE = "assert on the mock, or drop the patch and let the call stand"


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _base_name(node: ast.expr) -> str:
    """The leftmost name of a dotted expression -- ``mod`` for ``mod.a.b``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def branch_of(module_path: str) -> str:
    """The branch a test file lives in, read from its own path.

    The path is the only honest source: a test file imports a dozen branches and no import
    tells you which one it belongs to.
    """
    parts = Path(module_path).resolve().parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index - 1] == PRODUCT:
            return parts[index]
    return ""


def _own_names(tree: ast.Module, branch: str) -> Set[str]:
    """Names this file binds from its OWN branch's package, its tests/ excepted."""
    package = f"{PRODUCT}.{branch}"
    tests = f"{package}.{TESTS}"
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(package):
            if node.module == tests or (node.module or "").startswith(f"{tests}."):
                continue
            names |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {a.asname or a.name.split(".")[0] for a in node.names if a.name.startswith(package)}
    return names


def _tests(tree: ast.Module) -> List[Tuple[ast.AST, List[ast.AST], Set[str]]]:
    """Each test, its own nodes, and every name read inside it -- ONE descent.

    One stack descent carrying the enclosing test down, not three walks. Names are
    ``ast.Name`` ids, not rendered source: a binding ``m`` matched the letter m in text.
    """
    nodes: Dict[int, List[ast.AST]] = {}
    names: Dict[int, Set[str]] = {}
    owners: Dict[int, ast.AST] = {}
    stack: List[Tuple[ast.AST, ast.AST | None]] = [(tree, None)]
    while stack:
        node, enclosing = stack.pop()
        is_test = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(TEST_PREFIX)
        if enclosing is None and is_test:
            enclosing = node
            nodes[id(node)], names[id(node)], owners[id(node)] = [], set(), node
        if enclosing is not None:
            nodes[id(enclosing)].append(node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names[id(enclosing)].add(node.id)
        for child in ast.iter_child_nodes(node):
            stack.append((child, enclosing))
    return [(owners[key], nodes[key], names[key]) for key in nodes]


def _is_patch(node: ast.AST) -> bool:
    """Whether this call is ``patch(...)`` or ``patch.object(...)``."""
    return isinstance(node, ast.Call) and _tail_name(node.func) in _PATCH_VERBS


def _targets_own_branch(call: ast.Call, branch: str, own: Set[str]) -> bool:
    """Whether the patched thing lives in the test's own branch."""
    if not call.args:
        return False
    target = call.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value.startswith(f"{PRODUCT}.{branch}.")
    return _base_name(target) in own


def _handed_over(call: ast.Call) -> bool:
    """Whether a replacement was handed to the patch rather than left as a bare mock."""
    if {keyword.arg for keyword in call.keywords} & _HANDED_OVER:
        return True
    slot = 2 if _tail_name(call.func) == "patch" else 3
    return len(call.args) >= slot


def _is_monkeypatch(node: ast.AST) -> bool:
    """Whether this call is ``monkeypatch.setattr(...)``."""
    if not isinstance(node, ast.Call) or _tail_name(node.func) != "setattr":
        return False
    return _base_name(node.func) == _MONKEYPATCH


def _anonymous_silence(call: ast.Call) -> bool:
    """Whether the replacement handed over is a throwaway nothing can observe."""
    replacement = call.args[-1]
    if isinstance(replacement, ast.Lambda):
        return isinstance(replacement.body, ast.Constant) and replacement.body.value is None
    if not isinstance(replacement, ast.Call):
        return False
    return _tail_name(replacement.func) in _THROWAWAY and not replacement.args and not replacement.keywords


def _discarded_monkeypatches(nodes: List[ast.AST], branch: str, own: Set[str]) -> List[Tuple[int, str]]:
    """Every ``monkeypatch.setattr`` of own code whose stand-in nothing can ask."""
    findings: List[Tuple[int, str]] = []
    for node in nodes:
        if not _is_monkeypatch(node) or not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        if _targets_own_branch(node, branch, own) and _anonymous_silence(node):
            findings.append((node.lineno, _target_of(node)))
    return findings


def _target_of(call: ast.Call) -> str:
    """The patched thing, as a reader would name it."""
    if not call.args:
        return "the patch"
    target = call.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        return f"{ast.unparse(target)}.{call.args[1].value}"
    return ast.unparse(target)


def _loaded(node: ast.AST) -> Set[str]:
    """Every name read anywhere under a node."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _seeds(node: ast.AST) -> Set[str]:
    """Names this one node puts in front of an oracle, or configures as an answer."""
    if isinstance(node, ast.Assert):
        return _loaded(node.test)
    if isinstance(node, ast.Call) and _tail_name(node.func).startswith("assert"):
        return _loaded(node)
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return _loaded(node.value)
    return set()


def _binding(node: ast.AST) -> Tuple[List[ast.AST], ast.AST | None]:
    """(targets, value) for an assignment or a ``for`` loop; ([], None) for anything else."""
    if isinstance(node, ast.Assign):
        return list(node.targets), node.value
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target], node.value
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [node.target], node.iter
    return [], None


def _witnessed(nodes: List[ast.AST]) -> Set[str]:
    """Names that reach an oracle, directly or through a name bound from them."""
    witnessed: Set[str] = set()
    sources: Dict[str, Set[str]] = {}
    for node in nodes:
        witnessed |= _seeds(node)
        targets, value = _binding(node)
        read = _loaded(value) if value is not None else set()
        for name in (n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)):
            sources.setdefault(name, set()).update(read)
    grown = True
    while grown:
        before = len(witnessed)
        for name in [n for n in sources if n in witnessed]:
            witnessed |= sources[name]
        grown = len(witnessed) > before
    return witnessed


def _discarded_in_with(nodes: List[ast.AST], branch: str, own: Set[str], body: Set[str]) -> List[Tuple[int, str]]:
    """Every ``with patch(...)`` in this test whose mock nothing ever touches."""
    findings: List[Tuple[int, str]] = []
    for node in nodes:
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if not _is_patch(call) or not isinstance(call, ast.Call):
                continue
            if not _targets_own_branch(call, branch, own) or _handed_over(call):
                continue
            bound = item.optional_vars
            if isinstance(bound, ast.Name) and bound.id in body:
                continue
            findings.append((call.lineno, _target_of(call)))
    return findings


def _discarded_in_decorators(function: ast.AST, branch: str, own: Set[str], body: Set[str]) -> List[Tuple[int, str]]:
    """Every ``@patch`` whose injected parameter the body never mentions.

    ``@patch`` decorators bind BOTTOM-UP: the decorator closest to the ``def``
    fills the first parameter. Reading them in source order fills the wrong
    slots and then reports the wrong line.
    """
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    parameters = [arg.arg for arg in function.args.args if arg.arg not in ("self", "cls")]
    decorators = [d for d in reversed(function.decorator_list) if _is_patch(d)]

    findings: List[Tuple[int, str]] = []
    for index, decorator in enumerate(decorators):
        if not isinstance(decorator, ast.Call) or index >= len(parameters):
            continue
        if not _targets_own_branch(decorator, branch, own) or _handed_over(decorator):
            continue
        if parameters[index] not in body:
            findings.append((decorator.lineno, _target_of(decorator)))
    return findings


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[discarded_patch] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str, branch: str) -> List[Tuple[int, str]]:
    """(line, target) for each patch of the test's own branch that nothing observes."""
    tree = _parse(source)
    if tree is None or not branch:
        return []

    own = _own_names(tree, branch)
    findings: List[Tuple[int, str]] = []
    for function, nodes, _names in _tests(tree):
        witnessed = _witnessed(nodes)
        findings.extend(_discarded_in_with(nodes, branch, own, witnessed))
        findings.extend(_discarded_in_decorators(function, branch, own, witnessed))
        findings.extend(_discarded_monkeypatches(nodes, branch, own))
    return sorted(findings)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[discarded_patch] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Discarded patch", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for patches of its own branch that nothing observes."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    branch = branch_of(module_path)
    if not branch:
        # Outside src/aipass/<branch>/ there is no "own branch" to compare a
        # target against, and every patch would read as an edge.
        return _result(True, _one_check(True, "Outside a branch — no own code to discard a patch of"), 100)

    findings = scan(source, branch)
    if not findings:
        return _result(True, _one_check(True, f"Every patch of @{branch}'s own code is observed"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per patch would hide the rest.
    detail = "\n".join(
        f"{path.name}:{line} {target} is patched and never observed - {CURE}" for line, target in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
