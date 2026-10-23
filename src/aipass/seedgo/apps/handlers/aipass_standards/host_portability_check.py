# =================== AIPass ====================
# Name: host_portability_check.py
# Description: Host Portability Standards Checker Handler
# Version: 1.4.0
# Created: 2026-09-12
# Modified: 2026-10-22
# =============================================

"""Host Portability Standards Checker Handler.

Reference: host_portability.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.applicability import is_retired_path
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.aipass_standards.windows_compat_check import (
    _collect_child_linenos,
    _find_enclosing_function,
    _is_platform_guard,
    _lines_in_guarded_blocks,
    _references_platform,
)
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

# APPLIES_TO: its own corpus already reads tests/; a /proc read in a test is real.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "HOST_PORTABILITY"
_BYPASS_KEY = "host_portability"

#: Split so this file's own source cannot be read as an occurrence of the
#: literal it hunts. Same device windows_compat_check uses for /tmp.
_PROC_ROOT = "/" + "proc"
_SYS_ROOT = "/" + "sys/"

#: Directories this checker never walks, plus the two trees that are not source.
_SKIP_DIRS = SOURCE_SKIP_DIRS

#: The roots a branch's own code lives in: every macOS failure this standard exists to prevent was a test,
#: and skills keeps its built-in skills in lib/. Widened HERE only; the per-file audit corpus stays apps/.
_CORPUS_ROOTS = ("apps", "tests", "lib")

#: Calls that hand a string to the filesystem. A `/proc` literal anywhere else (a dict key, an argv element,
#: a skipif reason) opens nothing.
_FS_CONSTRUCTORS = frozenset({"open", "Path", "PosixPath", "PurePath"})
_FS_METHODS = frozenset(
    {
        "readlink",
        "listdir",
        "stat",
        "lstat",
        "scandir",
        "exists",
        "isfile",
        "isdir",
        "read_text",
        "read_bytes",
        "open",
        "iterdir",
    }
)

#: Constructors whose result is a path object, not a filesystem touch.
_PATH_CONSTRUCTORS = frozenset({"Path", "PosixPath", "PurePath"})

#: Except types that make a missing /proc (or a missing binary) a handled fact
#: rather than a crash. `_lines_in_guarded_blocks` already covers OSError and
#: the import family; FileNotFoundError and the broad catches are added here.
_FS_EXCEPT_TYPES = frozenset(
    {
        "FileNotFoundError",
        "NotADirectoryError",
        "IsADirectoryError",
        "IOError",
        "EnvironmentError",
        "Exception",
        "BaseException",
    }
)

#: The pytest context that expects an exception; around a missing-file error it is a guard.
RAISES = "raises"

#: Calls that answer "is it there" - the other honest guard for a /proc read.
_EXISTENCE_CALLS = frozenset({"exists", "is_file", "is_dir", "isfile", "isdir", "is_mount"})

#: The ONLY argv[0] names read. Measured, not imagined: each one is absent on
#: at least one host in the support matrix and present on the author's.
_NON_PORTABLE_BINARIES = frozenset(
    {
        "tmux",
        "systemctl",
        "loginctl",
        "sysctl",
        "gnome-terminal",
        "xfce4-terminal",
        "konsole",
        "xterm",
        "wt",
        "tasklist",
    }
)

#: Portable enough that scoring them adds 134 rows and no bugs. Named rather
#: than merely omitted so a later reader knows the omission was a decision.
PORTABLE_BINARIES = frozenset(
    {"git", "bash", "sh", "drone", "python3", "sleep", "gh", "ps", "lsof", "pgrep", "npm", "ruff"}
)

_SUBPROCESS_RUNNERS = frozenset({"run", "Popen", "check_output", "call", "check_call"})

#: Below this the branch fails the standard, matching every other checker here.
PASS_THRESHOLD = 75

#: Arm D: the generic classes whose __new__ picks a flavour. A concrete flavour
#: (PosixPath, PureWindowsPath, ...) carries its own _flavour on every Python.
_FLAVOURLESS_BASES = frozenset({"Path", "PurePath"})
_FLAVOUR_FIX = "below Python 3.12 Path.__new__ needs _flavour on the subclass (AttributeError on 3.10 and 3.11)"

#: Arm E: the two spellings a path can carry. RESOLVED passed through
#: ``.resolve()`` / ``os.path.realpath`` (or a same-file helper that returns
#: one); AS_GIVEN is the host's own answer, which keeps a symlinked prefix.
RESOLVED = "resolved"
AS_GIVEN = "as given"
#: Calls whose answer keeps the spelling the host hands out (macOS: /var, not /private/var).
_HOST_SPELLINGS = (
    "Path.home",
    "Path.cwd",
    "os.getcwd",
    "tempfile.gettempdir",
    "tempfile.mkdtemp",
    "tempfile.TemporaryDirectory",
)
#: Calls and methods that carry their first argument's (or receiver's) spelling through.
_CARRYING_WRAPPERS = frozenset({"str", "Path", "PurePath", "PosixPath", "os.fspath", "os.path.join"})
_CARRYING_METHODS = frozenset({"as_posix", "joinpath", "absolute", "with_name", "with_suffix"})
#: Methods that compare two paths' spellings.
_PATH_COMPARISONS = frozenset({"relative_to", "is_relative_to", "startswith"})
_SPELLING_FIX = (
    "one side passes through resolve(), the other is Path.home()/Path.cwd()/os.getcwd()/tempfile as given; "
    "a symlinked prefix (macOS /var -> /private/var) makes them differ - resolve both"
)


def _reads_platform(node: ast.expr) -> bool:
    """True when the expression consults the host platform.

    ``_references_platform`` (windows_compat_check) knows ``sys.platform`` and ``os.name``; this adds the
    ``platform`` module.
    """
    if _references_platform(node):
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            if child.value.id == "platform" and child.attr in ("system", "machine", "mac_ver", "uname"):
                return True
    return False


def _platform_predicate_names(tree: ast.Module) -> frozenset:
    """Module-level functions that RETURN a platform answer.

    ``_openat2_available()`` returns ``sys.platform == "linux" and ...``, so
    ``if _openat2_available():`` is a platform guard wearing a name. Without
    this, drone's guarded openat2 path reads as unguarded.
    """
    names: Set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None and _reads_platform(child.value):
                names.add(node.name)
                break
    return frozenset(names)


def _is_platform_test(test: ast.expr, predicates: frozenset) -> bool:
    """True for a platform comparison, a hasattr probe, or a named predicate."""
    if _is_platform_guard(test) or _reads_platform(test):
        return True
    for child in ast.walk(test):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in predicates:
            return True
    return False


def _platform_branch_lines(tree: ast.Module, predicates: frozenset) -> Set[int]:
    """Every line inside an ``if`` whose test reads the platform."""
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_platform_test(node.test, predicates):
            lines.update(_collect_child_linenos(node))
    return lines


def _platform_true_operands(tree: ast.Module, predicates: frozenset) -> Set[int]:
    """``id()`` of every node in the ``X`` of an inline ``X if <platform test> else Y``.

    Nodes, not lines: both operands usually share one line, and ``Y`` runs where the platform is not the one
    tested, so it stays judged. A module-level constant has no function to read, so this is its only acquittal.
    """
    ids: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and _is_platform_test(node.test, predicates):
            ids.update(id(child) for child in ast.walk(node.body))
    return ids


def _function_tests_platform(func: ast.AST) -> bool:
    """True when anything in this function branches on the platform.

    Whole-function, not lines-before: guarded reads are written both ways (a platform return above the read,
    an exists() return below it), and a before-only rule convicts half of one idiom.
    """
    for node in ast.walk(func):
        test = getattr(node, "test", None)
        if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)) and test is not None:
            if _reads_platform(test):
                return True
    return False


def _handler_catches(handler: ast.ExceptHandler, wanted: frozenset) -> bool:
    """True if this except clause names one of ``wanted`` (or is bare)."""
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in wanted
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in wanted for elt in handler.type.elts)
    return False


def _fs_except_lines(tree: ast.Module) -> Set[int]:
    """Lines inside a try that catches a missing-file / broad error.

    Union this with ``_lines_in_guarded_blocks``, which already covers OSError
    and the import family but not FileNotFoundError or ``except Exception``.
    """
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_handler_catches(h, _FS_EXCEPT_TYPES) for h in node.handlers):
            lines.update(_collect_child_linenos(node))
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(_expects_missing(i.context_expr) for i in node.items):
            lines.update(_collect_child_linenos(node))
    return lines


def _expects_missing(context: ast.expr) -> bool:
    """``pytest.raises(X)`` where X is a missing-file error: the test passes on every host.

    A /proc read or missing binary inside it raises where the host lacks them, which is what the test claims.
    """
    if not (isinstance(context, ast.Call) and _tail_name(context.func) == RAISES and context.args):
        return False
    expected = context.args[0]
    names = expected.elts if isinstance(expected, ast.Tuple) else [expected]
    return any(_tail_name(name) in _FS_EXCEPT_TYPES | {"OSError"} for name in names)


def _calls_existence(node: ast.AST) -> bool:
    """True when the expression asks the filesystem whether something is there."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if child.func.attr in _EXISTENCE_CALLS:
                return True
    return False


def _has_existence_exit(func: ast.AST) -> bool:
    """True when the function bails out on an existence test."""
    for node in ast.walk(func):
        if not isinstance(node, ast.If) or not _calls_existence(node.test):
            continue
        for stmt in node.body:
            for child in ast.walk(stmt):
                if isinstance(child, (ast.Return, ast.Raise, ast.Continue)):
                    return True
    return False


#: Hosts whose name in a skipif predicate means "the host that HAS the recipe".
_RECIPE_HOSTS = frozenset({"linux", "darwin"})

#: (owner, attribute) pairs whose patch forces the platform lane.
_PLATFORM_ATTRS = frozenset({("sys", "platform"), ("os", "name"), ("platform", "system")})

#: Filesystem primitives whose patch means the unit supplies the answer itself.
_FS_PRIMITIVES = frozenset(
    {"open", "listdir", "readlink", "scandir", "stat", "lstat", "iterdir", "read_text", "read_bytes", "exists", "Path"}
)

_PATCH_CALLS = frozenset({"setattr", "patch", "object"})


def _tail_name(node: ast.expr) -> str:
    """The last name in ``a.b.c`` or ``c``, else ""."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _mark_kind(mark: ast.expr) -> str:
    """ "skip" or "skipif" for a pytest skip mark, called or bare, else ""."""
    target = mark.func if isinstance(mark, ast.Call) else mark
    if isinstance(target, ast.Attribute) and target.attr in ("skip", "skipif"):
        return target.attr
    return ""


def _module_skip_marks(tree: ast.Module) -> Tuple[Dict[str, ast.expr], List[ast.expr]]:
    """Module-level names bound to a skip mark, and the module's own ``pytestmark``.

    ``_posix_only = pytest.mark.skipif(...)`` then ``@_posix_only`` is how many fleet guards are spelled.
    """
    aliases: Dict[str, ast.expr] = {}
    module_marks: List[ast.expr] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
        marks = [value for value in values if _mark_kind(value)]
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if not marks:
            continue
        for name in names:
            if name == "pytestmark":
                module_marks.extend(marks)
            else:
                aliases[name] = marks[0]
    return aliases, module_marks


def _skip_marks(decorators: Iterable[ast.expr], aliases: Dict[str, ast.expr]) -> List[ast.expr]:
    """The skip marks among these decorators, aliases resolved."""
    resolved = [aliases.get(dec.id, dec) if isinstance(dec, ast.Name) else dec for dec in decorators]
    return [mark for mark in resolved if _mark_kind(mark)]


def _names_recipe_host(predicate: ast.expr) -> bool:
    """True when a skipif predicate names the host that HAS the recipe, or probes the recipe.

    ``sys.platform == "win32"`` does not: it names one host that lacks the recipe, and macOS, which lacks it
    too, runs the unit.
    """
    for child in ast.walk(predicate):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value.lower() in _RECIPE_HOSTS or child.value.startswith((_PROC_ROOT, _SYS_ROOT)):
                return True
        if isinstance(child, ast.Call) and _tail_name(child.func) == "which":
            return True
    return False


def _is_guard_mark(mark: ast.expr) -> bool:
    """An unconditional skip, or a skipif whose predicate names the recipe host."""
    if _mark_kind(mark) == "skip":
        return True
    return isinstance(mark, ast.Call) and any(_names_recipe_host(arg) for arg in mark.args)


def _guarded_unit_lines(tree: ast.Module, aliases: Dict[str, ast.expr], module_marks: List[ast.expr]) -> Set[int]:
    """Every line of every unit (or class) whose skip names the recipe host."""
    if any(_is_guard_mark(mark) for mark in module_marks):
        return _collect_child_linenos(tree)
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if any(_is_guard_mark(mark) for mark in _skip_marks(node.decorator_list, aliases)):
            lines.update(_collect_child_linenos(node))
    return lines


def _patched_pair(call: ast.Call) -> Tuple[str, str]:
    """(owner, attribute) a monkeypatch.setattr / patch / patch.object call replaces."""
    if _tail_name(call.func) not in _PATCH_CALLS or not call.args:
        return "", ""
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        parts = first.value.split(".")
        return (parts[-2] if len(parts) > 1 else ""), parts[-1]
    second = call.args[1] if len(call.args) > 1 else None
    if isinstance(second, ast.Constant) and isinstance(second.value, str):
        return _tail_name(first), second.value
    return "", ""


def _manufactures_its_lane(unit: ast.AST) -> bool:
    """True when the unit patches the platform, or the filesystem primitive a read reaches.

    ai_mail test_wake.py replaces ``builtins.open``; aipass test_doctor.py
    replaces the module's ``Path`` and forces ``os.name``. Neither asks the
    host anything, so neither one's gate is what makes it portable.
    """
    for node in ast.walk(unit):
        if not isinstance(node, ast.Call):
            continue
        owner, attr = _patched_pair(node)
        if (owner, attr) in _PLATFORM_ATTRS or attr in _FS_PRIMITIVES:
            return True
    return False


def _caller_guarded_functions(tree: ast.Module, platform_lines: Set[int]) -> frozenset:
    """Functions whose EVERY call site in this module sits under a platform test.

    One hop, not a full call graph. That is enough for the shape it exists for
    - a Linux-only helper reached only from ``if <platform>:`` - and it cannot
    launder the fallback twin, whose call site is the ``else`` leg.
    """
    call_lines: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            call_lines.setdefault(node.func.id, []).append(node.lineno)
    return frozenset(name for name, lines in call_lines.items() if lines and all(ln in platform_lines for ln in lines))


def _proc_literal(node: ast.expr) -> str:
    """The ``/proc...`` text of this node, or "" when it is not one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(_PROC_ROOT):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        head = node.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str) and head.value.startswith(_PROC_ROOT):
            return head.value + "{...}"
    return ""


def _is_fs_call(node: ast.Call) -> bool:
    """True when this call hands its arguments to the filesystem."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _FS_CONSTRUCTORS
    if isinstance(func, ast.Attribute):
        return func.attr in _FS_METHODS or func.attr in _FS_CONSTRUCTORS
    return False


def _unwrap_path(node: ast.expr) -> ast.expr:
    """The argument of ``Path(x)`` and its kin, or the node itself."""
    if isinstance(node, ast.Call) and _tail_name(node.func) in _PATH_CONSTRUCTORS and node.args:
        return node.args[0]
    return node


def _proc_bindings(tree: ast.Module) -> Tuple[Dict[str, str], Set[int]]:
    """Names bound ONLY to /proc literals, and the ids of those bound value nodes.

    A name bound only to a /proc literal (``meminfo_path = "/proc/meminfo"`` then ``open(meminfo_path)``)
    is read; a name bound to anything else anywhere in the file is dropped.
    """
    texts: Dict[str, str] = {}
    values: Dict[str, List[int]] = {}
    other: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        text = _proc_literal(_unwrap_path(node.value))
        if not text:
            other.add(name)
            continue
        texts.setdefault(name, text)
        values.setdefault(name, []).append(id(node.value))
    bound = {name: text for name, text in texts.items() if name not in other}
    return bound, {value for name in bound for value in values[name]}


def _fs_operands(node: ast.Call) -> List[ast.expr]:
    """The arguments a filesystem call reads, plus the receiver of a method call."""
    operands: List[ast.expr] = list(node.args) + [kw.value for kw in node.keywords]
    if isinstance(node.func, ast.Attribute):
        operands.append(node.func.value)
    return operands


def _proc_nominations(tree: ast.Module, guarded: Set[int]) -> List[Tuple[int, str]]:
    """Every ``/proc`` literal that reaches a filesystem call, directly or through a name.

    A ``Path(...)`` bound to a name is judged where the name is USED, not where it is built: building a
    Path touches nothing. A call whose ``id()`` is in ``guarded`` (:func:`_platform_true_operands`) is not nominated.
    """
    bound, bound_values = _proc_bindings(tree)
    found: List[Tuple[int, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in bound_values or id(node) in guarded or not _is_fs_call(node):
            continue
        for arg in _fs_operands(node):
            text = _proc_literal(arg) or (bound.get(arg.id, "") if isinstance(arg, ast.Name) else "")
            key = (arg.lineno, text)
            if not text or key in seen:
                continue
            seen.add(key)
            found.append(key)
    return found


def _proc_violations(tree: ast.Module, skipped: Set[int], predicates: frozenset) -> List[Tuple[int, str]]:
    """Arm A: unguarded reads of the Linux-only /proc filesystem."""
    nominations = _proc_nominations(tree, _platform_true_operands(tree, predicates))
    if not nominations:
        return []

    platform_lines = _platform_branch_lines(tree, predicates)
    handled = _lines_in_guarded_blocks(tree) | _fs_except_lines(tree) | platform_lines
    caller_guarded = _caller_guarded_functions(tree, platform_lines)

    violations: List[Tuple[int, str]] = []
    for lineno, text in nominations:
        if lineno in handled or lineno in skipped:
            continue
        enclosing = _find_enclosing_function(tree, lineno)
        if enclosing is not None:
            if _function_tests_platform(enclosing) or _has_existence_exit(enclosing):
                continue
            if enclosing.name in caller_guarded:
                continue
        preview = text if len(text) <= 44 else text[:41] + "..."
        violations.append((lineno, f"reads {preview!r} - {_PROC_ROOT} is Linux-only (absent on macOS and Windows)"))
    return violations


def _subprocess_aliases(tree: ast.Module) -> frozenset:
    """Names this module calls the subprocess module by."""
    names: Set[str] = {"subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" and alias.asname:
                    names.add(alias.asname)
    return frozenset(names)


def _runner_argv0(node: ast.Call, aliases: frozenset) -> str:
    """The bare literal argv[0] of a subprocess runner call, or "".

    A Name, a starred element or an f-string argv[0] returns "" on purpose: a dynamic spelling is usually the cure.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _SUBPROCESS_RUNNERS:
        return ""
    if not (isinstance(func.value, ast.Name) and func.value.id in aliases):
        return ""
    if not node.args:
        return ""
    argv = node.args[0]
    if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
        return ""
    head = argv.elts[0]
    if isinstance(head, ast.Constant) and isinstance(head.value, str):
        return head.value
    return ""


def _which_guarded_names(func: ast.AST) -> Set[str]:
    """Binary names this function probes with ``shutil.which(...)``."""
    probed: Set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        called_which = (isinstance(target, ast.Attribute) and target.attr == "which") or (
            isinstance(target, ast.Name) and target.id == "which"
        )
        if not called_which or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            probed.add(first.value)
    return probed


def _binary_violations(tree: ast.Module, predicates: frozenset) -> Tuple[List[Tuple[int, str]], int]:
    """Arm B: a non-portable binary run with nothing standing behind it.

    Returns the violations and the count of sites that acquitted, so the
    message can say how much of the picture the score is NOT carrying.
    """
    aliases = _subprocess_aliases(tree)
    nominations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _runner_argv0(node, aliases)
        if name in _NON_PORTABLE_BINARIES:
            nominations.append((node.lineno, name))
    if not nominations:
        return [], 0

    platform_lines = _platform_branch_lines(tree, predicates)
    handled = _lines_in_guarded_blocks(tree) | _fs_except_lines(tree) | platform_lines

    violations: List[Tuple[int, str]] = []
    acquitted = 0
    for lineno, name in nominations:
        if lineno in handled:
            acquitted += 1
            continue
        enclosing = _find_enclosing_function(tree, lineno)
        if enclosing is not None:
            if name in _which_guarded_names(enclosing) or _function_tests_platform(enclosing):
                acquitted += 1
                continue
        violations.append(
            (
                lineno,
                f"runs {name!r} with no shutil.which({name!r}) probe, platform test or "
                "FileNotFoundError handler - a missing binary raises out of exec, "
                "so check=False does not help",
            )
        )
    return violations, acquitted


#: A unit NAMED for Linux. The other half (non_linux, off_linux, not_linux) is
#: the portable case and is excluded by name.
_LINUX_NAME = re.compile(r"(?:^|_)linux(?:_|$)")
_OTHER_HALF_NAME = re.compile(r"(?:non|off|not)_linux")

#: A reason saying the recipe is Linux's: "Linux-only", or Linux beside a
#: Linux-only recipe word. "Linux + macOS only by contract" (hooks, ps-based)
#: names Linux and no such recipe, and its Windows-only gate is correct.
_LINUX_ONLY_PROSE = re.compile(r"linux[- ]only|only on linux", re.IGNORECASE)
_LINUX_WORD = re.compile(r"linux", re.IGNORECASE)
_RECIPE_PROSE = re.compile(
    "|".join(re.escape(word) for word in (_PROC_ROOT, _SYS_ROOT, "systemd", "systemctl")), re.IGNORECASE
)


def _reason_text(mark: ast.expr) -> str:
    """Every string in a mark's ``reason=``, joined."""
    if not isinstance(mark, ast.Call):
        return ""
    reasons = [kw.value for kw in mark.keywords if kw.arg == "reason"]
    return " ".join(
        child.value
        for reason in reasons
        for child in ast.walk(reason)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


def _declares_linux_recipe(name: str, gates: List[ast.expr]) -> bool:
    """True when the unit's name, or its gate's reason, says the recipe is Linux's."""
    if _LINUX_NAME.search(name) and not _OTHER_HALF_NAME.search(name):
        return True
    for gate in gates:
        reason = _reason_text(gate)
        if _LINUX_ONLY_PROSE.search(reason) or (_LINUX_WORD.search(reason) and _RECIPE_PROSE.search(reason)):
            return True
    return False


def _test_units(tree: ast.Module) -> List[Tuple[ast.AST, List[ast.expr]]]:
    """Each test function with the decorators it inherits from its class."""
    units: List[Tuple[ast.AST, List[ast.expr]]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            units.extend(
                (member, list(getattr(member, "decorator_list", [])) + node.decorator_list) for member in node.body
            )
        else:
            units.append((node, list(getattr(node, "decorator_list", []))))
    return [
        (unit, decorators)
        for unit, decorators in units
        if isinstance(unit, (ast.FunctionDef, ast.AsyncFunctionDef)) and unit.name.startswith("test")
    ]


def _gate_violations(
    tree: ast.Module, aliases: Dict[str, ast.expr], module_marks: List[ast.expr]
) -> List[Tuple[int, str]]:
    """Arm C: a platform skip naming only Windows, on a unit that declares a Linux recipe."""
    violations: List[Tuple[int, str]] = []
    for unit, decorators in _test_units(tree):
        marks = _skip_marks(decorators, aliases) + module_marks
        if any(_is_guard_mark(mark) for mark in marks):
            continue
        gates: List[ast.expr] = [
            mark for mark in marks if isinstance(mark, ast.Call) and any(_reads_platform(a) for a in mark.args)
        ]
        name = getattr(unit, "name", "")
        if not gates or not _declares_linux_recipe(name, gates) or _manufactures_its_lane(unit):
            continue
        violations.append(
            (
                gates[0].lineno,
                f"{name} is skipped where the predicate names Windows, but declares a Linux recipe - "
                "macOS runs it and lacks the recipe too; skip where the recipe is absent "
                "(sys.platform != 'linux') and name the recipe in the reason",
            )
        )
    return violations


def _flavourless_subclasses(tree: ast.Module) -> List[Tuple[int, str]]:
    """Classes whose base is ``Path`` or ``PurePath`` itself and carry no ``_flavour``."""
    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {_tail_name(base) for base in node.bases} & _FLAVOURLESS_BASES
        carried = any("_flavour" in ast.dump(statement) for statement in node.body)
        if bases and not carried:
            violations.append((node.lineno, f"class {node.name}({min(bases)}) - {_FLAVOUR_FIX}"))
    return violations


def _dotted(node: ast.expr) -> str:
    """``a.b.c`` for a Name/Attribute chain, else ''."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _is_host_spelling(call: ast.Call) -> bool:
    """Path.home() / Path.cwd() / os.getcwd() / tempfile.* as the host hands it out."""
    dotted = _dotted(call.func)
    return any(dotted == name or dotted.endswith("." + name) for name in _HOST_SPELLINGS)


def _call_spelling(call: ast.Call, env: Dict[str, str], funcs: Dict[str, str]) -> str:
    """The spelling a call's result carries: RESOLVED, AS_GIVEN or '' (unknown)."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "resolve":
        return RESOLVED
    if _dotted(func) == "os.path.realpath":
        return RESOLVED
    if _is_host_spelling(call):
        return AS_GIVEN
    if isinstance(func, ast.Name) and func.id in funcs:
        return funcs[func.id]
    if (_dotted(func) in _CARRYING_WRAPPERS or _tail_name(func) in _CARRYING_WRAPPERS) and call.args:
        return _spelling(call.args[0], env, funcs)
    if isinstance(func, ast.Attribute) and func.attr in _CARRYING_METHODS:
        return _spelling(func.value, env, funcs)
    return ""


def _spelling(node: ast.expr, env: Dict[str, str], funcs: Dict[str, str]) -> str:
    """RESOLVED when the value passed through resolve(), AS_GIVEN when it is the host's spelling, else ''."""
    if isinstance(node, ast.Call):
        return _call_spelling(node, env, funcs)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _spelling(node.left, env, funcs)
    if isinstance(node, ast.Attribute) and node.attr in ("parent", "parents"):
        return _spelling(node.value, env, funcs)
    if isinstance(node, ast.Subscript):
        return _spelling(node.value, env, funcs)
    if isinstance(node, ast.Name):
        return env.get(node.id, "")
    if isinstance(node, (ast.Tuple, ast.List)) and node.elts:
        kinds = {_spelling(element, env, funcs) for element in node.elts}
        return kinds.pop() if len(kinds) == 1 else ""
    if isinstance(node, (ast.GeneratorExp, ast.ListComp)):
        return _spelling(node.elt, env, funcs)
    return ""


def _bind(target: ast.expr, value: ast.expr, env: Dict[str, str], funcs: Dict[str, str]) -> None:
    """Record the spelling each assigned name now carries (last assignment wins)."""
    if isinstance(target, ast.Name):
        env[target.id] = _spelling(value, env, funcs)
    elif isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
            kinds = [_spelling(element, env, funcs) for element in value.elts]
        else:
            kinds = [_spelling(value, env, funcs)] * len(target.elts)
        for element, kind in zip(target.elts, kinds):
            if isinstance(element, ast.Name):
                env[element.id] = kind


def _own_nodes(func: ast.AST) -> List[ast.AST]:
    """Every node in *func*'s body, nested defs and lambdas excluded, in source order."""
    found: List[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))


def _compared_pairs(node: ast.AST) -> List[Tuple[ast.expr, ast.expr]]:
    """The (left, right) operand pairs a node compares as paths, else []."""
    if isinstance(node, ast.Compare):
        pairs: List[Tuple[ast.expr, ast.expr]] = []
        operands = [node.left, *node.comparators]
        for left, op, right in zip(operands, node.ops, operands[1:]):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                pairs.append((left, right))
            elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, ast.Attribute) and right.attr == "parents":
                pairs.append((left, right.value))
        return pairs
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _PATH_COMPARISONS
        and len(node.args) == 1
        and not isinstance(node.args[0], ast.Tuple)
    ):
        return [(node.func.value, node.args[0])]
    return []


def _bind_statement(node: ast.AST, env: Dict[str, str], funcs: Dict[str, str]) -> None:
    """Apply one assignment, annotated assignment or ``with ... as`` to *env*."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            _bind(target, node.value, env, funcs)
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        _bind(node.target, node.value, env, funcs)
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        _bind(node.optional_vars, node.context_expr, env, funcs)


def _walk_function(func: ast.AST, funcs: Dict[str, str]) -> Tuple[List[str], List[Tuple[int, ast.AST]]]:
    """One pass over *func* in source order: (spellings of its returns, mixed comparisons)."""
    env: Dict[str, str] = {}
    returns: List[str] = []
    mixed: List[Tuple[int, ast.AST]] = []
    for node in _own_nodes(func):
        kinds = [{_spelling(left, env, funcs), _spelling(right, env, funcs)} for left, right in _compared_pairs(node)]
        if {RESOLVED, AS_GIVEN} in kinds:
            mixed.append((getattr(node, "lineno", 0), node))
        if isinstance(node, ast.Return) and node.value is not None:
            returns.append(_spelling(node.value, env, funcs))
        _bind_statement(node, env, funcs)
    return returns, mixed


def _function_spellings(tree: ast.Module) -> Dict[str, str]:
    """Same-file module-level functions whose every known return carries one spelling.

    ``aipass_home()`` returns ``_absolute(raw)`` (RESOLVED) or None: RESOLVED.
    ``_search_bounds()`` returns ``Path.cwd(), Path.home()``: AS_GIVEN. Iterated to
    a fixed point so a helper of a helper is followed, inside this file only.
    """
    defs = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    funcs: Dict[str, str] = {}
    for _round in range(len(defs) + 1):
        changed = False
        for func in defs:
            kinds = {kind for kind in _walk_function(func, funcs)[0] if kind}
            spelling = kinds.pop() if len(kinds) == 1 else ""
            if spelling and funcs.get(func.name) != spelling:
                funcs[func.name] = spelling
                changed = True
        if not changed:
            break
    return funcs


def _mixed_spelling_comparisons(tree: ast.Module) -> List[Tuple[int, str]]:
    """In one function, a resolve()d path compared with Path.home()/cwd()/tempfile as given."""
    funcs = _function_spellings(tree)
    violations: List[Tuple[int, str]] = []
    seen: Set[int] = set()
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for lineno, node in _walk_function(func, funcs)[1]:
            if lineno in seen:
                continue
            seen.add(lineno)
            text = ast.unparse(node)
            text = text if len(text) <= 80 else text[:77] + "..."
            violations.append((lineno, f"`{text}` - {_SPELLING_FIX}"))
    return violations


#: Either one empties git's config; then nothing on the host answers who commits.
_GIT_CONFIG_EMPTIERS = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"})
#: git resolves author and committer separately, and the email is what a runner cannot auto-detect.
_COMMIT_EMAILS = ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL")
_IDENTITY_FIX = "a CI runner has no email git can auto-detect, so git commit exits 128; set "


def _unanswered_git_identity(tree: ast.Module) -> List[Tuple[int, str]]:
    """A file that empties git's config names no commit email: green only where the host supplies one.

    File-local: a fixture cannot know which consumer commits, so the file that empties the config answers.
    """
    strings = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    emptied = sorted(lineno for lineno, value in strings if value in _GIT_CONFIG_EMPTIERS)
    if not emptied or any("user.email" in value for _lineno, value in strings):
        return []
    named = {value for _lineno, value in strings}
    missing = [name for name in _COMMIT_EMAILS if name not in named]
    if not missing:
        return []
    return [(emptied[0], f"empties git's config, no {' or '.join(missing)} - {_IDENTITY_FIX}{', '.join(missing)}")]


def _corpus_files(branch_root: Path, ignore_entries: list) -> List[Path]:
    """Every auditable .py file under apps/, tests/ and lib/."""
    files: List[Path] = []
    for root_name in _CORPUS_ROOTS:
        root = branch_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if is_disabled_file(path.name) or is_retired_path(str(path)):
                continue
            if is_seedgo_ignored(str(path), branch_root, ignore_entries):
                continue
            files.append(path)
    return files


def _relative(path: Path, branch_root: Path) -> str:
    """Branch-relative posix path, falling back to the absolute one."""
    try:
        return path.relative_to(branch_root).as_posix()
    except ValueError as exc:
        logger.info("[host_portability] %s not relative to %s: %s", path, branch_root, exc)
        return path.as_posix()


def scan_file(file_path: str) -> Tuple[List[Tuple[int, str]], int]:
    """Every arm (A to F) over one file. Returns (violations, acquitted binary sites).

    A file that cannot be read or parsed reports NOTHING: an unparseable file is ruff's business.
    """
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[host_portability] cannot read %s: %s", path, exc)
        return [], 0
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.info("[host_portability] skipped %s: %s", path, exc)
        return [], 0

    predicates = _platform_predicate_names(tree)
    aliases, module_marks = _module_skip_marks(tree)
    violations = _proc_violations(tree, _guarded_unit_lines(tree, aliases, module_marks), predicates)
    binary_violations, acquitted = _binary_violations(tree, predicates)
    violations.extend(binary_violations)
    violations.extend(_gate_violations(tree, aliases, module_marks))
    violations.extend(_flavourless_subclasses(tree))
    violations.extend(_mixed_spelling_comparisons(tree))
    violations.extend(_unanswered_git_identity(tree))
    violations.sort(key=lambda row: row[0])
    return violations, acquitted


def _result(score: int, checks: List[Dict], branch_path: str) -> Dict:
    """The pack's result shape, logged once."""
    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": _BYPASS_KEY},
    )
    return {
        "passed": score >= PASS_THRESHOLD,
        "checks": checks,
        "score": score,
        "standard": STANDARD_NAME,
    }


def _violation_items(rows: Iterable[Tuple[str, int, str]]) -> List[Dict]:
    """Violations in the shape branch_audit's display reader expects."""
    return [{"file": rel, "line": lineno, "name": detail} for rel, lineno, detail in rows]


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for host assumptions: Linux-only OS calls and a 3.12-only Path subclass."""
    branch_root = Path(branch_path)

    if is_bypassed(branch_path, _BYPASS_KEY, bypass_rules=bypass_rules):
        return _result(
            100,
            [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            branch_path,
        )

    ignore_entries = load_ignore_entries(branch_root)
    files = _corpus_files(branch_root, ignore_entries)
    if not files:
        return _result(
            100,
            [{"name": "Host portability", "passed": True, "message": "No apps/, tests/ or lib/ Python files to check"}],
            branch_path,
        )

    rows: List[Tuple[str, int, str]] = []
    dirty_files: Set[str] = set()
    acquitted_total = 0
    for path in files:
        rel = _relative(path, branch_root)
        violations, acquitted = scan_file(str(path))
        acquitted_total += acquitted
        for lineno, detail in violations:
            if is_bypassed(rel, _BYPASS_KEY, lineno, bypass_rules):
                continue
            rows.append((rel, lineno, detail))
            dirty_files.add(rel)

    score = int((len(files) - len(dirty_files)) / len(files) * 100)
    checks: List[Dict] = []

    if rows:
        preview = "; ".join(f"{rel}:{lineno} {detail.split(' - ')[0]}" for rel, lineno, detail in rows[:3])
        suffix = f" (and {len(rows) - 3} more)" if len(rows) > 3 else ""
        checks.append(
            {
                "name": "Host portability",
                "passed": False,
                "message": (
                    f"{len(rows)} host assumption(s) in {len(dirty_files)}/{len(files)} files: {preview}{suffix}"
                ),
                "violations": _violation_items(rows),
            }
        )
    else:
        checks.append(
            {
                "name": "Host portability",
                "passed": True,
                "message": f"No unguarded {_PROC_ROOT} reads or non-portable binaries in {len(files)} files",
            }
        )

    if acquitted_total:
        checks.append(
            {
                "name": "Handled binary calls",
                "passed": True,
                "message": (
                    f"{acquitted_total} call(s) to a non-portable binary already carry a "
                    "shutil.which() probe, a platform test or a FileNotFoundError handler "
                    "- context, not scored"
                ),
            }
        )

    return _result(score, checks, branch_path)
