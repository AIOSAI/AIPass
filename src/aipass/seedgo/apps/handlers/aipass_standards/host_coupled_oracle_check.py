# =================== AIPass ====================
# Name: host_coupled_oracle_check.py
# Description: Host Coupled Oracle Standards Checker Handler
# Version: 1.0.0
# Created: 2026-10-26
# Modified: 2026-10-26
# =============================================

"""Host Coupled Oracle Standards Checker Handler.

Reference: host_coupled_oracle.md
"""

import ast
import re
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.seedgo.apps.handlers.aipass_standards import calendar_bound_check as calendar
from aipass.seedgo.apps.handlers.aipass_standards.check_support import references_platform, tail_name
from aipass.seedgo.apps.handlers.bypass.ignore_handler import load_ignore_entries
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

# APPLIES_TO: its corpus is tests/ already - the rule is about what a test's oracle depends on.
APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "HOST_COUPLED_ORACLE"
_BYPASS_KEY = "host_coupled_oracle"

#: tests/ is fingerprinted by the audit cache already; a skill's own tests/ under lib/ is not.
BRANCH_INPUTS = ("lib/*/tests/**/*.py",)

#: Below this the branch fails the standard, matching every other checker here.
PASS_THRESHOLD = 75

#: Calls from the unit to the platform branch. The PR #807 specimen needed three.
MAX_HOPS = 6

_OWN_PIDS = frozenset({"getpid", "getppid"})

#: A callee named for the command line it reads, matched on whole underscore-separated words.
_COMMAND_LINE = re.compile(r"(?:^|_)(?:args|argv|cmdline|command|title|proctitle)(?:_|$)")

_RUNNERS = frozenset({"run", "Popen", "check_output", "call", "check_call"})
_PLATFORM_CALLS = frozenset({"system", "machine", "mac_ver", "uname"})

_TITLE_FIX = (
    "pytest-xdist retitles every worker ('[pytest-xdist running] <test>'), so CI reads that title where a "
    "plain run reads python; start a child process and read the child's pid"
)
_COUNT_FIX = (
    "each host runs a different number of commands down that path; count only the call this test is about "
    "(filter call_args_list), or make the expected count follow sys.platform"
)


def _reads_platform(node: ast.AST, aliases: frozenset = frozenset()) -> bool:
    """sys.platform, os.name, platform.system() and friends, or a module-level name bound to one."""
    if references_platform(node):  # type: ignore[arg-type]
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in aliases:
            return True
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            if child.value.id == "platform" and child.attr in _PLATFORM_CALLS:
                return True
    return False


def _is_own_pid(node: ast.expr) -> bool:
    """``os.getpid()`` or ``os.getppid()``: this process, or the one that started it."""
    return isinstance(node, ast.Call) and tail_name(node.func) in _OWN_PIDS and not node.args


def _own_command_line_reads(unit: ast.AST) -> List[Tuple[int, str]]:
    """Arm 1: the unit hands its own pid to a reader named for the command line."""
    rows: List[Tuple[int, str]] = []
    for node in ast.walk(unit):
        if not isinstance(node, ast.Call):
            continue
        name = tail_name(node.func)
        if _COMMAND_LINE.search(name) and any(_is_own_pid(arg) for arg in node.args):
            rows.append((node.lineno, f"reads its own process's command line through {name}() - {_TITLE_FIX}"))
    return rows


def _patches_runner(expr: ast.expr) -> bool:
    """``patch("...subprocess.run")`` or ``patch.object(subprocess, "run")``: a process-wide runner mock."""
    if not isinstance(expr, ast.Call) or not expr.args:
        return False
    called = calendar._dotted(expr.func)
    first = expr.args[0]
    if called.endswith("patch.object"):
        second = expr.args[1] if len(expr.args) > 1 else None
        return tail_name(first) == "subprocess" and isinstance(second, ast.Constant) and second.value in _RUNNERS
    if called.endswith("patch") and isinstance(first, ast.Constant) and isinstance(first.value, str):
        parts = first.value.split(".")
        return len(parts) >= 2 and parts[-2] == "subprocess" and parts[-1] in _RUNNERS
    return False


def _runner_mocks(unit: ast.AST) -> Set[str]:
    """Names a ``with`` binds to a patched subprocess runner."""
    return {
        item.optional_vars.id
        for node in ast.walk(unit)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if isinstance(item.optional_vars, ast.Name) and _patches_runner(item.context_expr)
    }


def _exact_count_lines(unit: ast.AST, mocks: Set[str]) -> List[int]:
    """Lines asserting ``<mock>.call_count == N`` for a literal N above zero."""
    lines: List[int] = []
    for node in ast.walk(unit):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)):
            continue
        left, right = node.left, node.comparators[0]
        counted = isinstance(left, ast.Attribute) and left.attr == "call_count"
        if counted and isinstance(left.value, ast.Name) and left.value.id in mocks:  # type: ignore[union-attr]
            if isinstance(right, ast.Constant) and type(right.value) is int and right.value > 0:
                lines.append(node.lineno)
    return lines


_SHAPE_CACHE: Dict[str, Tuple[frozenset, frozenset]] = {}


def _module_shape(module: "calendar._Module") -> Tuple[frozenset, frozenset]:
    """(names bound to the platform at module level, names the module calls subprocess by)."""
    key = str(module.path)
    if key not in _SHAPE_CACHE:
        aliases = {
            target.id
            for node in module.tree.body
            if isinstance(node, ast.Assign) and _reads_platform(node.value)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        runners = {"subprocess"}
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                runners.update(alias.asname for alias in node.names if alias.name == "subprocess" and alias.asname)
        _SHAPE_CACHE[key] = (frozenset(aliases), frozenset(runners))
    return _SHAPE_CACHE[key]


def _branches(func: ast.AST, aliases: frozenset) -> bool:
    """Anything in the function chooses a path by the platform."""
    return any(
        _reads_platform(node.test, aliases)
        for node in ast.walk(func)
        if isinstance(node, (ast.If, ast.IfExp, ast.While))
    )


def _runs(func: ast.AST, runners: frozenset) -> bool:
    """The function starts a subprocess through the module it imported."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _RUNNERS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in runners
        for node in ast.walk(func)
    )


def _platform_branch_trail(test_module: "calendar._Module", unit: ast.AST) -> str:
    """'relpath:line name' of the nearest reached production function that both branches on the platform
    and runs a subprocess, '' when none. A platform gate that runs nothing (a fixture pins it) is no fork."""
    queue = deque([(test_module, unit, 0)])
    seen: Set[Tuple[str, int]] = set()
    while queue:
        module, func, hops = queue.popleft()
        key = (str(module.path), func.lineno)  # type: ignore[attr-defined]
        if key in seen:
            continue
        seen.add(key)
        if func is not unit and calendar._is_production(module):
            aliases, runners = _module_shape(module)
            if _branches(func, aliases) and _runs(func, runners):
                where = calendar._relative_to_root(module.path, module.root)
                return f"{where}:{func.lineno} {func.name}"  # type: ignore[attr-defined]
        if hops < MAX_HOPS:
            targets = calendar._call_targets(module, func, set())  # type: ignore[arg-type]
            queue.extend((m, f, hops + 1) for m, f in targets)
    return ""


def _guarded(unit: ast.AST, cls: Optional[ast.ClassDef], tree: ast.Module) -> bool:
    """A skip that reads the platform on the unit, its class or the module, or an expectation that does."""
    marks = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    decorators = list(getattr(unit, "decorator_list", [])) + (list(cls.decorator_list) if cls else [])
    decorators += [marks["pytestmark"]] if "pytestmark" in marks else []
    resolved = [marks.get(d.id, d) if isinstance(d, ast.Name) else d for d in decorators]
    if any(_reads_platform(mark) for mark in resolved):
        return True
    return any(
        _reads_platform(node.test)
        for node in ast.walk(unit)
        if isinstance(node, (ast.If, ast.IfExp, ast.Assert, ast.While))
    )


def _platform_count_rows(
    test_module: "calendar._Module", unit: ast.AST, cls: Optional[ast.ClassDef]
) -> List[Tuple[int, str]]:
    """Arm 2: an exact runner count on a reach that branches on the platform, the expectation unguarded."""
    lines = _exact_count_lines(unit, _runner_mocks(unit))
    if not lines or _guarded(unit, cls, test_module.tree):
        return []
    trail = _platform_branch_trail(test_module, unit)
    if not trail:
        return []
    return [
        (line, f"asserts an exact subprocess call count through {trail}, which branches on the platform - {_COUNT_FIX}")
        for line in lines
    ]


def scan_file(file_path: str, package_root: str) -> List[Tuple[int, str]]:
    """Every test unit in one file, both arms. A file that cannot be read or parsed reports nothing."""
    test_module = calendar._module_at(Path(file_path), Path(package_root))
    if test_module is None:
        return []
    rows: List[Tuple[int, str]] = []
    for unit, cls in calendar._test_units(test_module.tree):
        found = _own_command_line_reads(unit) + _platform_count_rows(test_module, unit, cls)
        rows.extend((line, f"{unit.name} {detail}") for line, detail in found)
    return sorted(rows)


def _result(score: int, checks: List[Dict], branch_path: str) -> Dict:
    """The pack's result shape, logged once."""
    json_handler.log_operation("check_completed", {"branch": branch_path, "score": score, "standard": _BYPASS_KEY})
    return {"passed": score >= PASS_THRESHOLD, "checks": checks, "score": score, "standard": STANDARD_NAME}


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch's tests for oracles that are only true on the host that wrote them."""
    branch_root = Path(branch_path)
    if is_bypassed(branch_path, _BYPASS_KEY, bypass_rules=bypass_rules):
        return _result(
            100,
            [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            branch_path,
        )

    files = calendar._corpus_files(branch_root, load_ignore_entries(branch_root))
    if not files:
        return _result(
            100,
            [{"name": "Host coupled oracle", "passed": True, "message": "No tests/ Python files to check"}],
            branch_path,
        )

    package_root = str(branch_root.resolve().parent)
    rows = [
        (rel, lineno, detail)
        for path in files
        for rel in [calendar._relative(path, branch_root)]
        for lineno, detail in scan_file(str(path), package_root)
        if not is_bypassed(rel, _BYPASS_KEY, lineno, bypass_rules)
    ]
    dirty_files = {rel for rel, _, _ in rows}
    score = int((len(files) - len(dirty_files)) / len(files) * 100)
    if not rows:
        message = f"No test reads its own process title or counts commands across a platform fork in {len(files)} files"
        return _result(score, [{"name": "Host coupled oracle", "passed": True, "message": message}], branch_path)

    preview = "; ".join(f"{rel}:{lineno} {detail.split(' - ')[0]}" for rel, lineno, detail in rows[:3])
    suffix = f" (and {len(rows) - 3} more)" if len(rows) > 3 else ""
    check = {
        "name": "Host coupled oracle",
        "passed": False,
        "message": f"{len(rows)} host-coupled oracle(s) in {len(dirty_files)}/{len(files)} files: {preview}{suffix}",
        "violations": [{"file": rel, "line": lineno, "name": detail} for rel, lineno, detail in rows],
    }
    return _result(score, [check], branch_path)
