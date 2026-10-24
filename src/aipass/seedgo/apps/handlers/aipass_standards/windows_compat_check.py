# =================== AIPass ====================
# Name: windows_compat_check.py
# Description: Windows Compatibility Standards Checker Handler
# Version: 1.7.1
# Created: 2026-05-10
# Modified: 2026-10-24
# =============================================

"""Windows Compatibility Standards Checker Handler."""

import ast
from pathlib import Path
from typing import Callable, Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.applicability import is_test_path
from aipass.seedgo.apps.handlers.aipass_standards.check_support import (
    collect_child_linenos,
    find_enclosing_function,
    is_platform_guard,
    lines_in_guarded_blocks,
    references_platform,
)
from aipass.seedgo.apps.handlers.aipass_standards.exclusive_create_race import find_exclusive_create_races
from aipass.seedgo.apps.handlers.aipass_standards.mock_repr_path import find_mock_repr_paths
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.aipass_standards.text_fixture_bytes_oracle import find_text_fixture_bytes_oracles
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

# APPLIES_TO: Windows CI runs the suite; a Unix-only API in a test fails it.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

_POSIX_ONLY_MODULES = frozenset({"fcntl", "pwd", "grp", "termios", "resource"})

# Deferred-import arm: a module one platform lacks, imported at call time.
_PLATFORM_ONLY_MODULES = _POSIX_ONLY_MODULES | frozenset({"msvcrt", "winreg"})

_IMPORT_CATCHING_TYPES = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})

_POSIX_ONLY_OS_ATTRS = frozenset({"WNOHANG"})

_POSIX_ONLY_OS_CALLS = frozenset({"fork", "setpgid", "killpg", "getpgid", "waitpid"})

_TEST_POSIX_CALLS: dict[tuple[str, str], str] = {
    ("os", "chmod"): "os.chmod() — Windows ignores permission bits",
    ("os", "symlink"): "os.symlink() — Windows needs privileges",
    ("os", "getuid"): "os.getuid() — not available on Windows",
    ("os", "getgid"): "os.getgid() — not available on Windows",
    ("os", "chown"): "os.chown() — not available on Windows",
    ("stat", "S_IMODE"): "stat.S_IMODE() — Unix permission assertion",
}


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


def _platform_only_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    """The platform-only module names an import statement binds."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names if alias.name.split(".")[0] in _PLATFORM_ONLY_MODULES]
    if node.module and node.module.split(".")[0] in _PLATFORM_ONLY_MODULES:
        return [node.module]
    return []


def _try_body_catches_import(node: ast.Try, child: ast.AST) -> bool:
    """True when ``child`` sits in the try body and a handler catches ImportError."""
    if not any(child is stmt or child in ast.walk(stmt) for stmt in node.body):
        return False
    for handler in node.handlers:
        if handler.type is None:
            return True
        types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        if any(isinstance(t, ast.Name) and t.id in _IMPORT_CATCHING_TYPES for t in types):
            return True
    return False


def _deferred_import_sites(
    node: ast.AST, stack: list[ast.AST]
) -> list[tuple[ast.Import | ast.ImportFrom, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Imports of platform-only modules inside a function, outside any ImportError catch."""
    sites: list[tuple[ast.Import | ast.ImportFrom, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.Import, ast.ImportFrom)) and _platform_only_names(child):
            funcs = [s for s in stack if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
            caught = any(isinstance(s, ast.Try) and _try_body_catches_import(s, child) for s in stack)
            if funcs and not caught:
                sites.append((child, funcs[-1]))
        sites.extend(_deferred_import_sites(child, stack + [child]))
    return sites


def _find_deferred_platform_imports(tree: ast.Module, reported: set[int]) -> list[tuple[int, str]]:
    """Flag a platform-only module imported at call time (devpulse a831fe55).

    A deferred import is decided when the function runs, after a test may have
    pretended sys.platform: registry's _FileLock imported fcntl under
    ``sys.platform != 'win32'`` and a darwin-pretending test made the Windows
    runner import it. A module-level import (gated or try/except) is decided
    once at import, before any test runs, so it is not read here. Lines the
    unguarded-import arm already reports are skipped: one row per line.
    """
    violations: list[tuple[int, str]] = []
    for node, func in _deferred_import_sites(tree, []):
        if node.lineno in reported:
            continue
        name = _platform_only_names(node)[0]
        stmt = f"import {name}" if isinstance(node, ast.Import) else f"from {name} import ..."
        cure = "bind it once at module level, try/except ImportError -> None"
        violations.append((node.lineno, f"{stmt} inside {func.name}() -- {cure}"))
    return violations


_STREAM_PROBES = frozenset({"isatty", "get_terminal_size"})
_SYS_STREAMS = frozenset({"stdout", "stderr", "__stdout__", "__stderr__"})


def _executed_nodes(node: ast.AST):
    """Every node of one expression or simple statement, minus lambda/def bodies."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield current
        stack.extend(ast.iter_child_nodes(current))


def _compound_parts(stmt: ast.stmt) -> tuple[list[ast.AST], list[ast.stmt]] | None:
    """(head expressions, nested statements) a compound statement runs, or None for a simple one."""
    if isinstance(stmt, ast.ClassDef):
        return [], stmt.body
    if isinstance(stmt, ast.Try):
        return [], stmt.body + stmt.orelse + stmt.finalbody
    if isinstance(stmt, (ast.If, ast.While)):
        return [stmt.test], stmt.body + stmt.orelse
    if isinstance(stmt, ast.With):
        return [item.context_expr for item in stmt.items], stmt.body
    if isinstance(stmt, ast.For):
        return [stmt.iter], stmt.body + stmt.orelse
    return None


def _import_time_nodes(body: list[ast.stmt]):
    """Nodes a module runs when imported: no function body, main guard or except fallback."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) or _is_main_guard(stmt):
            continue
        parts = _compound_parts(stmt)
        if parts is None:
            yield from _executed_nodes(stmt)
            continue
        heads, nested = parts
        for head in heads:
            yield from _executed_nodes(head)
        yield from _import_time_nodes(nested)


def _console_constructors(tree: ast.Module) -> set[str]:
    """Names that build a rich Console: aliases of it, and same-file subclasses that keep its __init__ answer.

    A subclass that defines ``_color_system`` decides colour itself (cli display's
    _LiveConsole re-detects it per print) and is not a constructor here.
    """
    names = {"Console"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "rich.console":
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "Console")
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    grew = True
    while grew:
        grew = False
        for cls in classes:
            if cls.name in names or any(
                isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "_color_system"
                for stmt in cls.body
            ):
                continue
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in cls.bases}
            if bases & names:
                names.add(cls.name)
                grew = True
    return names


def _is_sys_stream(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in _SYS_STREAMS
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _console_decides_colour(call: ast.Call) -> bool:
    """True when the call's own arguments settle colour without reading the host stream."""
    keywords = {kw.arg: kw.value for kw in call.keywords}
    if None in keywords:
        return True  # **kwargs: the decision is not in this file
    colour = keywords.get("color_system")
    forced = keywords.get("force_terminal")
    target = keywords.get("file")
    if isinstance(colour, ast.Constant) and colour.value is None:
        return True
    if isinstance(forced, ast.Constant) and isinstance(forced.value, bool):
        return True
    return target is not None and not _is_sys_stream(target)


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _find_import_time_stream_reads(tree: ast.Module) -> list[tuple[int, str]]:
    """Flag a colour or size answer fixed when the module is imported (cli b6655280).

    Rich runs _detect_color_system() in Console.__init__ and keeps the answer, so
    a console built at import -- force_terminal set from isatty() or left unset --
    answers for the stream as it was then. A conftest imported cli's display while
    pytest's capture was suspended; on a Windows xdist worker that stream is NUL,
    isatty() says True, and every later capture carried escape codes (PR #774).
    Read: module-level code (class bodies, if/try/with blocks), never a function
    body, an ``if __name__ == "__main__"`` block or an except handler (a fallback
    for an absent cross-branch import does not run where the fleet is installed).
    Acquitted: file= other than sys.stdout/sys.stderr, force_terminal=True/False,
    color_system=None, or a subclass that defines _color_system (per-print).
    """
    constructors = _console_constructors(tree)
    rows: dict[int, str] = {}
    for node in _import_time_nodes(tree.body):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in constructors and not _console_decides_colour(node):
            cure = "decide per print (cli display._LiveConsole) or pass file=/force_terminal= explicitly"
            rows[node.lineno] = f"module-level {name}() fixes its colour at import -- {cure}"
        elif name in _STREAM_PROBES and node.lineno not in rows:
            rows[node.lineno] = f"{name}() read at import -- read it when you print"
    return sorted(rows.items())


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
        if isinstance(node, ast.If) and is_platform_guard(node.test):
            guarded.update(collect_child_linenos(node))
    return guarded


def _has_early_platform_return(func_node: ast.FunctionDef | ast.AsyncFunctionDef, before_line: int) -> bool:
    for node in ast.walk(func_node):
        if not isinstance(node, ast.If) or node.lineno >= before_line:
            continue
        if not is_platform_guard(node.test):
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
        enclosing = find_enclosing_function(tree, node.lineno)
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


def _docstring_ids(tree: ast.Module) -> set[int]:
    """Ids of the docstring constants: prose that names /tmp writes nothing there."""
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, scopes)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }


def _find_hardcoded_tmp_violations(tree: ast.Module, guarded: set[int]) -> list[tuple[int, str]]:
    """Flag hardcoded /tmp paths — use tempfile module instead."""
    violations: list[tuple[int, str]] = []
    seen_lines: set[int] = set()
    docstrings = _docstring_ids(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in docstrings:
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


def _is_pytest_mark(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "mark"
        and isinstance(node.value, ast.Name)
        and node.value.id == "pytest"
    )


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
            if any(references_platform(arg) for arg in dec.args):
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

    for lineno, desc in _find_backslashed_tmp_writes(func_node):
        if lineno not in guarded and lineno not in seen_lines:
            violations.append((lineno, desc))
            seen_lines.add(lineno)


# A tmp_path name holding a backslash (PR #774, CI round three): one file on
# POSIX, a tree whose parents do not exist on Windows, so the write raises
# there before the code under test runs. Only a literal segment of a path
# rooted at the tmp_path / tmpdir fixture, and only when the test writes it: a
# name only read or handed on is the same missing file on both hosts.
_TMP_ROOTS = frozenset({"tmp_path", "tmpdir"})
_PATH_WRITE_METHODS = frozenset({"write_text", "write_bytes", "touch", "mkdir"})


def _backslashed_literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and "\\" in node.value:
        return node.value
    return None


def _backslashed_tmp_name(node: ast.expr) -> str | None:
    """The backslashed literal segment of a tmp_path-rooted path expression, else None."""
    found = None
    while True:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            found = _backslashed_literal(node.right) or found
            node = node.left
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            for arg in node.args:
                found = _backslashed_literal(arg) or found
            node = node.func.value
        else:
            break
    return found if isinstance(node, ast.Name) and node.id in _TMP_ROOTS else None


def _opens_for_writing(call: ast.Call, mode_index: int) -> bool:
    modes = [kw.value for kw in call.keywords if kw.arg == "mode"]
    if len(call.args) > mode_index:
        modes.append(call.args[mode_index])
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str) and set(m.value) & set("wax+") for m in modes)


def _written_path(call: ast.Call) -> ast.expr | None:
    """The path a call writes or creates on disk, else None."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _PATH_WRITE_METHODS:
        return func.value
    if isinstance(func, ast.Attribute) and func.attr == "open" and _opens_for_writing(call, 0):
        return func.value
    if isinstance(func, ast.Name) and func.id == "open" and call.args and _opens_for_writing(call, 1):
        return call.args[0]
    return None


def _find_backslashed_tmp_writes(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[int, str]]:
    """Writes to a tmp_path name holding a backslash, in place or through a name bound once."""
    bindings: dict[str, list[str | None]] = {}
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            bindings.setdefault(node.targets[0].id, []).append(_backslashed_tmp_name(node.value))
    # A name bound more than once is not guessed at: which binding reaches the write needs flow.
    named = {name: values[0] for name, values in bindings.items() if len(values) == 1 and values[0]}

    rows: list[tuple[int, str]] = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        target = _written_path(node)
        if target is None:
            continue
        literal = named.get(target.id) if isinstance(target, ast.Name) else _backslashed_tmp_name(target)
        if literal:
            rows.append(
                (node.lineno, f"tmp_path name {literal!r} holds a backslash -- one file on POSIX, a tree on Windows")
            )
    return rows


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
                    "declined": True,
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
    except (SyntaxError, ValueError) as e:
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

    guarded = lines_in_guarded_blocks(tree)
    platform_only = _platform_guarded_lines(tree)

    all_violations: list[tuple[int, str]] = []
    posix_imports = _find_posix_import_violations(tree, guarded)
    all_violations.extend(posix_imports)
    all_violations.extend(_find_deferred_platform_imports(tree, {ln for ln, _ in posix_imports}))
    all_violations.extend(_find_posix_constant_violations(tree, guarded))
    all_violations.extend(_find_posix_call_violations(tree, guarded))
    all_violations.extend(_find_os_kill_violations(tree, guarded))
    all_violations.extend(_find_os_kill_signal0_violations(tree, platform_only))
    all_violations.extend(_find_start_new_session_violations(tree, guarded))
    all_violations.extend(_find_hardcoded_tmp_violations(tree, guarded))
    all_violations.extend(_find_aplay_violations(tree, guarded))
    all_violations.extend(_find_shell_true_violations(tree, guarded))
    all_violations.extend(_find_cp1252_entry_violations(tree))

    if is_test_path(str(path)):
        all_violations.extend(_find_test_platform_violations(tree, guarded))
    elif path.name != "conftest.py":
        all_violations.extend(_find_import_time_stream_reads(tree))

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
# ADVISORY: what a Linux seat cannot observe about Windows, pinned by shape
# =============================================================================
#
# Three arms, one reason: each Windows red passed on Linux because the Linux
# value is a degenerate case -- no delete-pending state for PermissionError to
# come from, no backslash for repr to double or Windows separator for a
# WindowsPath repr to re-render, no \r for text mode to add. No Linux run can go
# red on any of them, so the shape is read statically.
#
# * lock race -- CI 35192484222: api's token store lock caught FileExistsError
#   only; a create against a lock mid-removal answered PermissionError and the
#   revoke thread died. Detector: exclusive_create_race.py. Corpus is the scored
#   lane's (apps/**/*.py minus __init__.py and skip dirs), so the ratchet to a
#   scored rule moves no file in or out.
# * mock repr path -- CI 35416653326: three of flow's tests asserted str(lock)
#   in " ".join(str(c) for c in mock.call_args_list); repr spelled C:\\Users
#   where the path said C:\Users. Detector: mock_repr_path.py. A test-side
#   shape, so its corpus is tests/**/*.py -- a lane the scored audit never
#   walks, which makes this channel its only home, not a waypoint. CI
#   38843541023 (api test_host_lifetime) was this arm's second mechanism: a
#   Path argument renders as WindowsPath('C:/...') in the call repr.
# * text fixture bytes oracle -- CI 38843541023: hooks' settings-backup test
#   wrote its fixture with write_text('...\n') and asserted the backup's
#   read_bytes() == b'...\n'; text mode wrote \r\n on Windows. Detector:
#   text_fixture_bytes_oracle.py. Test-side, tests/**/*.py, like the repr arm.
#
# check_branch_info(), not check_module(): a new scored arm inside a gating
# standard reds every branch holding a hit on the commit that lands it (the
# 09-13 lesson). Info lines carry no score and render at any score. The
# lock-race ratchet is one line: extend all_violations in check_module() with
# find_exclusive_create_races() once the owners cure.
#
# The branch's windows_compat bypass rules silence a line here exactly as they
# would once it scores. The info channel is handed no rules, so this reads them
# itself -- which also means `audit --no-bypass` does not reach these lines.

_LOCK_RACE_LABEL = "windows_compat lock race (advisory)"
_MOCK_REPR_LABEL = "windows_compat mock repr path (advisory)"
_TEXT_BYTES_LABEL = "windows_compat text fixture bytes oracle (advisory)"


def _corpus(branch_root: Path, top: str) -> list[Path]:
    """Every .py under one top-level directory, minus disabled files and skip dirs."""
    base = branch_root / top
    if not base.is_dir():
        return []
    return [
        f
        for f in sorted(base.rglob("*.py"))
        if not is_disabled_file(f.name)
        and not any(part in SOURCE_SKIP_DIRS for part in f.relative_to(branch_root).parts)
    ]


def _advisory_corpus(branch_root: Path) -> list[Path]:
    return [f for f in _corpus(branch_root, "apps") if f.name != "__init__.py"]


def _advisory_lines(
    branch_root: Path,
    corpus: list[Path],
    finder: Callable[[ast.Module, set[int]], list[tuple[int, str]]],
    label: str,
    bypass_rules: list,
) -> list[str]:
    """One "<label>: <rel>:<line> <desc>" per finding the branch has not bypassed."""
    lines: list[str] = []
    for path in corpus:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, ValueError) as e:
            logger.info("[windows_compat] advisory scan skipped %s: %s", path, e)
            continue
        rel = path.relative_to(branch_root).as_posix()
        for lineno, desc in finder(tree, _platform_guarded_lines(tree)):
            if not is_bypassed(str(path), "windows_compat", lineno, bypass_rules):
                lines.append(f"{label}: {rel}:{lineno} {desc}")
    return lines


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored lines: Windows-only failures no Linux run can observe.

    Args:
        branch_path: Branch root to inspect.

    Returns:
        One "(advisory)" line per offending site -- exclusive creates in apps/,
        paths asserted against a mock call's repr and bytes oracles over a
        text-mode newline fixture in tests/; empty when clean.
    """
    branch_root = Path(branch_path)
    apps_corpus = _advisory_corpus(branch_root)
    tests_corpus = _corpus(branch_root, "tests")
    if not apps_corpus and not tests_corpus:
        return []
    bypass_rules = load_bypass_rules(branch_path)
    races = _advisory_lines(branch_root, apps_corpus, find_exclusive_create_races, _LOCK_RACE_LABEL, bypass_rules)
    reprs = _advisory_lines(branch_root, tests_corpus, find_mock_repr_paths, _MOCK_REPR_LABEL, bypass_rules)
    texts = _advisory_lines(branch_root, tests_corpus, find_text_fixture_bytes_oracles, _TEXT_BYTES_LABEL, bypass_rules)
    if races or reprs or texts:
        json_handler.log_operation(
            "windows_compat_advisory_lines",
            {
                "branch": branch_root.name,
                "lock_race": len(races),
                "mock_repr": len(reprs),
                "text_bytes": len(texts),
                "standard": "windows_compat",
            },
        )
    return races + reprs + texts
