# =================== AIPass ====================
# Name: literal_path_check.py
# Description: Literal Absolute Path Standards Checker Handler
# Version: 1.1.0
# Created: 2026-09-22
# Modified: 2026-10-30
# =============================================

"""
Literal Absolute Path Standards Checker Handler

Reference: literal_path.md
"""

from functools import partial
import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result, tail_name

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "LITERAL_PATH"
STANDARD_KEY = "literal_path"

#: An absolute POSIX path: a slash followed by a path character. Bare "/" and
#: "//" are excluded by the second character -- a root separator alone carries
#: no habit to end.
_POSIX_ABS = re.compile(r"^/[A-Za-z0-9_.\-]")

#: A drive-rooted path. Counted, never convicted -- see literal_path.md.
_DRIVE_ABS = re.compile(r"^[A-Za-z]:[\\/]")

#: hardcoded_path's own ground, spelled as that checker spells it, so one line
#: is never charged by two standards.
_HOME_ROOTED = re.compile(r"^(/home/[a-zA-Z][\w.\-]+/|/Users/[a-zA-Z][\w.\-]+/)")

#: Real places on a real host. A test that names one is naming its subject.
_SYSTEM_ROOTS: Tuple[str, ...] = (
    "/bin/",
    "/sbin/",
    "/usr/",
    "/etc/",
    "/proc",
    "/sys/",
    "/dev/",
    "/var/run/",
    "/opt/",
    "/Library/",
    "/System/",
    "/Applications/",
)

#: Calls whose arguments are a stub's data, not a path the test opens.
_MOCK_CALLS: frozenset[str] = frozenset(
    {
        "Mock",
        "MagicMock",
        "AsyncMock",
        "PropertyMock",
        "patch",
        "object",
        "mock_open",
        "parametrize",
        "assert_called_with",
        "assert_any_call",
        "assert_called_once_with",
    }
)

#: Keywords that carry a stub's data or a marker's prose.
_MOCK_KEYWORDS: frozenset[str] = frozenset({"return_value", "side_effect", "new", "reason", "match", "id", "ids"})

#: Client verbs whose first argument is a route, not a file.
_URL_CALLS: frozenset[str] = frozenset(
    {"get", "post", "put", "delete", "head", "request", "websocket_connect", "url_for", "options"}
)

#: Path classes that cannot touch a filesystem.
_PURE_PATH_CLASSES: frozenset[str] = frozenset({"PurePath", "PurePosixPath", "PureWindowsPath"})

#: str methods that compare or cut. The literal is an operand, not a path.
_STRING_OPS: frozenset[str] = frozenset(
    {
        "startswith",
        "endswith",
        "split",
        "rsplit",
        "join",
        "replace",
        "count",
        "index",
        "find",
        "strip",
        "lstrip",
        "rstrip",
        "partition",
        "rpartition",
        "format",
        "removeprefix",
        "removesuffix",
    }
)

FIX = "build it from tmp_path; a literal absolute path is the next host's failure"


def _is_path_literal(value: str) -> bool:
    """Whether this string is an absolute path this rule can judge.

    Whitespace disqualifies it: a refusal message that opens with a path is
    prose, and hooks ``test_hook_test.py`` binds exactly one.
    """
    if len(value) < 3 or any(char.isspace() for char in value):
        return False
    return bool(_POSIX_ABS.match(value))


def _is_drive_literal(value: str) -> bool:
    """Whether this string is a drive-rooted path -- counted, never convicted."""
    if len(value) < 3 or "\n" in value:
        return False
    return bool(_DRIVE_ABS.match(value))


def _acquittal(call_name: str, keyword_name: str | None, value: str) -> str | None:
    """Why this argument is not a violation, or None when it is one."""
    if _HOME_ROOTED.match(value):
        return "home-rooted (hardcoded_path)"
    if call_name in _MOCK_CALLS or keyword_name in _MOCK_KEYWORDS:
        return "mock data"
    if call_name in _URL_CALLS:
        return "url path"
    if call_name in _PURE_PATH_CLASSES:
        return "pure path class"
    if call_name in _STRING_OPS:
        return "string operation"
    if value.startswith(_SYSTEM_ROOTS):
        return "system root"
    return None


def _arguments(node: ast.Call) -> List[Tuple[str | None, ast.expr]]:
    """(keyword name or None, value) for every argument a call is handed."""
    positional: List[Tuple[str | None, ast.expr]] = [(None, arg) for arg in node.args]
    return positional + [(keyword.arg, keyword.value) for keyword in node.keywords]


def _string_value(node: ast.expr) -> str | None:
    """The value of a string literal, or None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _path_bindings(tree: ast.Module) -> Dict[str, str]:
    """Names bound ONLY to a convictable path literal, and that literal.

    A name assigned anything else anywhere in the file is dropped: which value
    reaches the call is then a question one pass cannot answer.
    """
    bound: Dict[str, str] = {}
    rejected: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        value = _string_value(node.value)
        if value is None or not _is_path_literal(value) or _acquittal("", None, value) is not None:
            rejected.add(name)
            continue
        bound.setdefault(name, value)
    return {name: value for name, value in bound.items() if name not in rejected}


def _url_helpers(tree: ast.Module) -> Dict[str, Set[int | str]]:
    """Same-file functions that hand a parameter straight to a client verb, and which parameters.

    ``_get(server, "/drop")`` reaches ``conn.request("GET", path)`` one hop down: each parameter is
    keyed by position and by name, so either spelling at the call site is the route.
    """
    helpers: Dict[str, Set[int | str]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [arg.arg for arg in function.args.args]
        forwarded: Set[int | str] = set()
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or tail_name(node.func) not in _URL_CALLS:
                continue
            for _keyword, argument in _arguments(node):
                if isinstance(argument, ast.Name) and argument.id in params:
                    forwarded |= {params.index(argument.id), argument.id}
        if forwarded:
            helpers[function.name] = forwarded
    return helpers


_parse = partial(parse, tag="literal_path")


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, what was found, fix) for every literal absolute path in use."""
    tree = _parse(source)
    if tree is None:
        return []

    bound = _path_bindings(tree)
    routes = _url_helpers(tree)
    hits: List[Tuple[int, str, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = tail_name(node.func)
        for position, (keyword_name, argument) in enumerate(_arguments(node)):
            if (keyword_name if keyword_name is not None else position) in routes.get(call_name, ()):
                continue
            value = _string_value(argument)
            if value is None and isinstance(argument, ast.Name):
                value = bound.get(argument.id)
            if value is None or not _is_path_literal(value):
                continue
            if _acquittal(call_name, keyword_name, value) is not None:
                continue
            key = (argument.lineno, value)
            if key in seen:
                continue
            seen.add(key)
            hits.append((argument.lineno, f'literal absolute path "{value}"', FIX))
    return sorted(hits)


def counted_drive_paths(source: str) -> List[Tuple[int, str]]:
    """(line, value) for every drive-rooted literal handed to a call.

    Counted, never convicted: ``tmp_path`` on a POSIX host cannot produce a drive-rooted path.
    """
    tree = _parse(source)
    if tree is None:
        return []

    found: List[Tuple[int, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = tail_name(node.func)
        for keyword_name, argument in _arguments(node):
            value = _string_value(argument)
            if value is None or not _is_drive_literal(value):
                continue
            if call_name in _MOCK_CALLS or keyword_name in _MOCK_KEYWORDS or call_name in _URL_CALLS:
                continue
            key = (argument.lineno, value)
            if key in seen:
                continue
            seen.add(key)
            found.append(key)
    return sorted(found)


_read = partial(read_text, tag="literal_path", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Literal path", "passed": passed, "message": message}]


def _clean_message(drive_paths: List[Tuple[int, str]]) -> str:
    """What a passing file says, carrying the drive-rooted count."""
    if not drive_paths:
        return "Every path in use is built, not written"
    subject = "path is" if len(drive_paths) == 1 else "paths are"
    return (
        f"Every path in use is built, not written "
        f"({len(drive_paths)} drive-rooted {subject} counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for a literal absolute path handed to a call."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    hits = [h for h in scan(source) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, _clean_message(counted_drive_paths(source))), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(f"{path.name}:{line} {name} - {fix}" for line, name, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
