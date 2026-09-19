# =================== AIPass ====================
# Name: windows_compat_check.py
# Description: Windows Compatibility Standards Checker Handler
# Version: 1.2.0
# Created: 2026-05-10
# Modified: 2026-09-17
# =============================================

"""Windows Compatibility Standards Checker Handler."""

import ast
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.exclusive_create_race import find_exclusive_create_races
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

_POSIX_ONLY_MODULES = frozenset({"fcntl", "pwd", "grp", "termios", "resource"})

_POSIX_ONLY_OS_ATTRS = frozenset({"WNOHANG"})

_POSIX_ONLY_OS_CALLS = frozenset({"fork", "setpgid", "killpg", "getpgid", "waitpid"})

_GUARDED_EXCEPT_TYPES = frozenset(
    {
        "ImportError",
        "ModuleNotFoundError",
        "OSError",
        "PermissionError",
        "ProcessLookupError",
    }
)

_TEST_POSIX_CALLS: dict[tuple[str, str], str] = {
    ("os", "chmod"): "os.chmod() — Windows ignores permission bits",
    ("os", "symlink"): "os.symlink() — Windows needs privileges",
    ("os", "getuid"): "os.getuid() — not available on Windows",
    ("os", "getgid"): "os.getgid() — not available on Windows",
    ("os", "chown"): "os.chown() — not available on Windows",
    ("stat", "S_IMODE"): "stat.S_IMODE() — Unix permission assertion",
}


def _is_platform_guard(node: ast.expr) -> bool:
    """Return True if the test expression is a sys.platform or os.name comparison."""
    if isinstance(node, ast.Compare):
        left = node.left
        if isinstance(left, ast.Attribute) and isinstance(left.value, ast.Name):
            if left.value.id == "sys" and left.attr == "platform":
                return True
            if left.value.id == "os" and left.attr == "name":
                return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "hasattr":
            return True
    if isinstance(node, ast.BoolOp):
        return any(_is_platform_guard(v) for v in node.values)
    return False


def _collect_child_linenos(node: ast.AST) -> set[int]:
    """Walk all descendants and return line numbers where present."""
    lines: set[int] = set()
    for child in ast.walk(node):
        lineno = getattr(child, "lineno", None)
        if lineno is not None:
            lines.add(lineno)
    return lines


def _handler_catches_guarded_type(handler: ast.ExceptHandler) -> bool:
    """Return True if the except handler catches an import/OS error type."""
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in _GUARDED_EXCEPT_TYPES
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in _GUARDED_EXCEPT_TYPES for elt in handler.type.elts)
    return False


def _lines_in_guarded_blocks(tree: ast.Module) -> set[int]:
    """Collect line numbers inside platform guard blocks or try/except ImportError."""
    guarded: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_platform_guard(node.test):
            guarded.update(_collect_child_linenos(node))
        if isinstance(node, ast.Try):
            if any(_handler_catches_guarded_type(h) for h in node.handlers):
                guarded.update(_collect_child_linenos(node))

    return guarded


def _check_import_node(node: ast.Import, guarded: set[int]) -> list[tuple[int, str]]:
    """Check a single Import node for POSIX-only module names."""
    return [
        (node.lineno, f"import {alias.name}")
        for alias in node.names
        if alias.name in _POSIX_ONLY_MODULES and node.lineno not in guarded
    ]


def _find_posix_import_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Find unguarded imports of POSIX-only modules."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.extend(_check_import_node(node, guarded))
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            if node.module.split(".")[0] in _POSIX_ONLY_MODULES and node.lineno not in guarded:
                violations.append((node.lineno, f"from {node.module} import ..."))
    return violations


def _find_posix_constant_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Find unguarded references to POSIX-only constants like os.WNOHANG."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id == "os" and node.attr in _POSIX_ONLY_OS_ATTRS:
            if node.lineno not in guarded:
                violations.append((node.lineno, f"os.{node.attr}"))
        if node.value.id == "signal" and node.attr == "SIGPIPE":
            if node.lineno not in guarded:
                violations.append((node.lineno, "signal.SIGPIPE"))
    return violations


def _find_posix_call_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Find unguarded calls to POSIX-only os functions."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            continue
        if func.value.id == "os" and func.attr in _POSIX_ONLY_OS_CALLS:
            if node.lineno not in guarded:
                violations.append((node.lineno, f"os.{func.attr}()"))
    return violations


def _find_os_kill_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Find os.kill() calls not inside a try/except that catches OSError."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
            and func.attr == "kill"
            and node.lineno not in guarded
        ):
            violations.append((node.lineno, "os.kill() without OSError handling"))
    return violations


def _platform_guarded_lines(tree: ast.Module) -> set[int]:
    """Collect line numbers inside platform guards only (NOT try/except)."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_platform_guard(node.test):
            guarded.update(_collect_child_linenos(node))
    return guarded


def _find_enclosing_function(tree: ast.Module, target_lineno: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if target_lineno in _collect_child_linenos(node):
            if best is None or node.lineno > best.lineno:
                best = node
    return best


def _has_early_platform_return(func_node: ast.FunctionDef | ast.AsyncFunctionDef, before_line: int) -> bool:
    for node in ast.walk(func_node):
        if not isinstance(node, ast.If) or node.lineno >= before_line:
            continue
        if not _is_platform_guard(node.test):
            continue
        for body_stmt in node.body:
            for child in ast.walk(body_stmt):
                if isinstance(child, (ast.Return, ast.Raise)):
                    return True
    return False


def _find_os_kill_signal0_violations(tree: ast.Module, platform_guarded: set[int]) -> list[tuple[int, str]]:
    """Flag os.kill(pid, 0) — the liveness probe that kills on Windows.

    try/except does NOT guard this: the target process is terminated
    before the exception. Only a platform guard (sys.platform/os.name)
    is valid — either wrapping the call or early-returning before it.
    """
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
            and func.attr == "kill"
        ):
            continue
        if len(node.args) < 2:
            continue
        sig_arg = node.args[1]
        if not (isinstance(sig_arg, ast.Constant) and sig_arg.value == 0):
            continue
        if node.lineno in platform_guarded:
            continue
        enclosing = _find_enclosing_function(tree, node.lineno)
        if enclosing and _has_early_platform_return(enclosing, node.lineno):
            continue
        violations.append(
            (node.lineno, "os.kill(pid, 0) — terminates target on Windows (use OpenProcess+GetExitCodeProcess)")
        )
    return violations


def _find_start_new_session_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Flag start_new_session=True (POSIX-only subprocess kwarg)."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.lineno in guarded:
            continue
        for kw in node.keywords:
            if kw.arg == "start_new_session" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                violations.append((node.lineno, "start_new_session=True (POSIX-only)"))
    return violations


_TMP_PREFIX = "/" + "tmp" + "/"
_TMP_EXACT = "/" + "tmp"


def _find_hardcoded_tmp_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Flag hardcoded /tmp paths — use tempfile module instead."""
    violations: list[tuple[int, str]] = []
    seen_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        val = node.value
        if node.lineno in guarded or node.lineno in seen_lines:
            continue
        if val == _TMP_EXACT or _TMP_PREFIX in val:
            preview = repr(val) if len(val) <= 40 else repr(val[:37] + "...")
            violations.append((node.lineno, f"hardcoded {_TMP_EXACT} path: {preview}"))
            seen_lines.add(node.lineno)
    return violations


_APLAY_CMD = "a" + "play"


def _find_aplay_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Flag POSIX-only audio commands (no macOS/Windows alternative)."""
    violations: list[tuple[int, str]] = []
    seen_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.lineno in guarded or node.lineno in seen_lines:
            continue
        if _APLAY_CMD in node.value:
            violations.append((node.lineno, f"{_APLAY_CMD} command (POSIX-only — needs afplay/winsound alternatives)"))
            seen_lines.add(node.lineno)
    return violations


def _find_shell_true_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Flag shell=True in subprocess calls (behavior differs Windows vs Unix)."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.lineno in guarded:
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                violations.append((node.lineno, "shell=True (behavior differs Windows vs Unix)"))
    return violations


def _is_main_guard(node: ast.AST) -> int:
    """Return the line number if node is 'if __name__ == "__main__"', else 0."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return 0
    left = node.test.left
    if not (isinstance(left, ast.Name) and left.id == "__name__"):
        return 0
    if any(isinstance(c, ast.Constant) and c.value == "__main__" for c in node.test.comparators):
        return node.lineno
    return 0


def _find_cp1252_entry_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Flag entry points using Rich console without sys.stdout.reconfigure()."""
    has_rich_import = False
    has_reconfigure = False
    main_line = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("rich") or node.module.startswith("aipass.cli"):
                has_rich_import = True
        if not main_line:
            main_line = _is_main_guard(node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "reconfigure":
                has_reconfigure = True
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "reconfigure"
            ):
                has_reconfigure = True

    if has_rich_import and main_line and not has_reconfigure:
        return [(main_line, "Rich console entry point without sys.stdout.reconfigure() — cp1252 risk on Windows")]
    return []


def _is_test_file(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def _is_pytest_mark(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "mark"
        and isinstance(node.value, ast.Name)
        and node.value.id == "pytest"
    )


def _references_platform(node: ast.expr) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            if (child.value.id == "sys" and child.attr == "platform") or (
                child.value.id == "os" and child.attr == "name"
            ):
                return True
    return False


def _has_platform_skipif(decorators: list[ast.expr]) -> bool:
    for dec in decorators:
        if isinstance(dec, ast.Attribute) and dec.attr == "skip" and _is_pytest_mark(dec.value):
            return True
        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
            continue
        func = dec.func
        if func.attr == "skip" and _is_pytest_mark(func.value):
            return True
        if func.attr == "skipif" and _is_pytest_mark(func.value):
            if any(_references_platform(arg) for arg in dec.args):
                return True
    return False


def _match_posix_call(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name):
        return None
    key = (node.func.value.id, node.func.attr)
    return _TEST_POSIX_CALLS.get(key)


def _match_stat_constant(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
        return None
    if node.value.id == "stat" and node.attr.startswith("S_I") and node.attr != "S_IMODE":
        return f"stat.{node.attr} — Unix permission constant"
    return None


def _scan_test_body(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    guarded: set[int],
    violations: list[tuple[int, str]],
) -> None:
    seen_lines: set[int] = set()
    for node in ast.walk(func_node):
        lineno = getattr(node, "lineno", None)
        if lineno is None or lineno in guarded or lineno in seen_lines:
            continue

        desc = _match_posix_call(node) or _match_stat_constant(node)
        if desc:
            violations.append((lineno, desc))
            seen_lines.add(lineno)


def _collect_unguarded_tests(
    parent: ast.Module | ast.ClassDef,
    class_skipif: bool = False,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    results: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.iter_child_nodes(parent):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        if not class_skipif and not _has_platform_skipif(node.decorator_list):
            results.append(node)
    return results


def _find_test_platform_violations(
    tree: ast.Module,
    guarded: set[int],
) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    targets: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    targets.extend(_collect_unguarded_tests(tree))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            targets.extend(_collect_unguarded_tests(node, _has_platform_skipif(node.decorator_list)))

    for func in targets:
        _scan_test_body(func, guarded, violations)

    return violations


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for Windows-incompatible patterns."""
    path = Path(module_path)

    if is_bypassed(module_path, "windows_compat", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "WINDOWS_COMPAT",
        }

    if path.suffix != ".py" or path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Windows compat",
                    "passed": True,
                    "message": "File skipped (non-target)",
                }
            ],
            "score": 100,
            "standard": "WINDOWS_COMPAT",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File exists",
                    "passed": False,
                    "message": f"File not found: {module_path}",
                }
            ],
            "score": 0,
            "standard": "WINDOWS_COMPAT",
        }

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File readable",
                    "passed": False,
                    "message": f"Error reading file: {e}",
                }
            ],
            "score": 0,
            "standard": "WINDOWS_COMPAT",
        }

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        logger.info("Skipped %s: SyntaxError during parse", path)
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File parseable",
                    "passed": False,
                    "message": f"Syntax error: {e}",
                }
            ],
            "score": 0,
            "standard": "WINDOWS_COMPAT",
        }

    guarded = _lines_in_guarded_blocks(tree)
    platform_only = _platform_guarded_lines(tree)

    all_violations: list[tuple[int, str]] = []
    all_violations.extend(_find_posix_import_violations(tree, guarded))
    all_violations.extend(_find_posix_constant_violations(tree, guarded))
    all_violations.extend(_find_posix_call_violations(tree, guarded))
    all_violations.extend(_find_os_kill_violations(tree, guarded))
    all_violations.extend(_find_os_kill_signal0_violations(tree, platform_only))
    all_violations.extend(_find_start_new_session_violations(tree, guarded))
    all_violations.extend(_find_hardcoded_tmp_violations(tree, guarded))
    all_violations.extend(_find_aplay_violations(tree, guarded))
    all_violations.extend(_find_shell_true_violations(tree, guarded))
    all_violations.extend(_find_cp1252_entry_violations(tree))

    if _is_test_file(path):
        all_violations.extend(_find_test_platform_violations(tree, guarded))

    non_bypassed = [
        (ln, desc) for ln, desc in all_violations if not is_bypassed(module_path, "windows_compat", ln, bypass_rules)
    ]
    non_bypassed.sort(key=lambda x: x[0])

    checks = []
    violation_count = len(non_bypassed)

    if violation_count == 0:
        checks.append(
            {
                "name": "Windows compat",
                "passed": True,
                "message": "No unguarded POSIX-only patterns found",
            }
        )
    else:
        previews = [f"L{ln}: {desc}" for ln, desc in non_bypassed[:3]]
        preview_str = "; ".join(previews)
        suffix = f" (and {violation_count - 3} more)" if violation_count > 3 else ""
        checks.append(
            {
                "name": "Windows compat",
                "passed": False,
                "message": f"{violation_count} unguarded POSIX pattern(s): {preview_str}{suffix}",
            }
        )

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "windows_compat"},
    )
    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "WINDOWS_COMPAT",
    }


# =============================================================================
# ADVISORY: exclusive creates that lose the Windows delete-pending race
# =============================================================================
#
# CI 35192484222 (Windows): api's token store lock caught FileExistsError only,
# a create against a lock mid-removal answered PermissionError, and the revoke
# thread died. The detector and its measured false-positive boundary live in
# exclusive_create_race.py.
#
# check_branch_info(), not check_module(): a new scored arm inside a gating
# standard reds every branch holding a hit on the commit that lands it (the
# 09-13 lesson), and 5 branches hold one today. Info lines carry no score and
# render at any score. The ratchet is one line: extend all_violations in
# check_module() with find_exclusive_create_races() once the owners cure.
#
# Corpus is the scored lane's: apps/**/*.py minus __init__.py and skip dirs,
# so the ratchet moves no file in or out. The branch's windows_compat bypass
# rules silence a line here exactly as they will once it scores. The info
# channel is handed no rules, so this reads them itself -- which also means
# `audit --no-bypass` does not reach these lines.

_LOCK_RACE_LABEL = "windows_compat lock race (advisory)"


def _advisory_corpus(branch_root: Path) -> list[Path]:
    apps = branch_root / "apps"
    if not apps.is_dir():
        return []
    return [
        f
        for f in sorted(apps.rglob("*.py"))
        if f.name != "__init__.py"
        and not is_disabled_file(f.name)
        and not any(part in SOURCE_SKIP_DIRS for part in f.relative_to(branch_root).parts)
    ]


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored lines: exclusive creates a Windows delete-pending state breaks.

    Args:
        branch_path: Branch root to inspect.

    Returns:
        One "(advisory)" line per offending create; empty when clean.
    """
    branch_root = Path(branch_path)
    corpus = _advisory_corpus(branch_root)
    if not corpus:
        return []
    bypass_rules = load_bypass_rules(branch_path)
    lines: list[str] = []
    for path in corpus:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, ValueError) as e:
            logger.info("[windows_compat] advisory scan skipped %s: %s", path, e)
            continue
        rel = path.relative_to(branch_root).as_posix()
        for lineno, desc in find_exclusive_create_races(tree, _platform_guarded_lines(tree)):
            if is_bypassed(str(path), "windows_compat", lineno, bypass_rules):
                continue
            lines.append(f"{_LOCK_RACE_LABEL}: {rel}:{lineno} {desc}")
    if lines:
        json_handler.log_operation(
            "windows_compat_advisory_lines",
            {"branch": branch_root.name, "count": len(lines), "standard": "windows_compat"},
        )
    return lines
