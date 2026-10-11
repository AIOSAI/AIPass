# =================== AIPass ====================
# Name: literal_path_check.py
# Description: Literal Absolute Path Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Literal Absolute Path Standards Checker Handler

Test template v1, item 22: paths in a test are built from ``tmp_path``, never
written as a literal ``/...``.

WHY THIS IS NOT ``hardcoded_path``. That standard hunts one species, a HOME
directory -- ``/home/<user>/``, ``/Users/<user>/``, ``C:\\Users\\<user>`` -- and
it hunts it by regex over every line of every file in the fleet. Item 22's own
example, ``Path("/nonexistent/path")``, has no home in it and ``hardcoded_path``
cannot see it. Measured 2026-09-22 over the 553 fleet test files: 2,491 literal
absolute paths, of which 164 are home-rooted. The other 2,327 had no checker.

WHY IT IS RESTRICTED TO AN ARGUMENT, AND THE RESTRICTION IS THE RULE.
``host_portability`` ARM A settled this shape for ``/proc``: a literal that
merely SITS somewhere is data, and only a literal HANDED to a call is a path the
test uses. The same split here throws out 2,327 nominations down to 874. The
positions it throws out are the ones that would have made the rule a nuisance:

    {"/srv/data/x.json": [...]}          a mock TABLE, keyed by path
    assert result == "/fake/repo"        the ORACLE, not an input
    mock.return_value = "/usr/bin/tmux"  what a STUB returns

Never convicted, each for a measured reason (counts over the 553 files):

  * A HOME-rooted literal (78 in argument position). ``hardcoded_path`` already
    convicts it. Two standards charging one line teaches a reader to read
    neither.
  * MOCK DATA (200): an argument to ``Mock``/``MagicMock``/``patch``/
    ``mock_open``/``parametrize``/``assert_called_*``, or a ``return_value=``,
    ``side_effect=``, ``new=``, ``reason=``, ``match=``, ``id=``/``ids=``
    keyword. The literal is what a stub RETURNS or what a skip's prose SAYS.
  * A URL PATH (188): the argument of ``get``/``post``/``put``/``delete``/
    ``head``/``request``/``websocket_connect``/``url_for``/``options``.
    ``client.get("/v1/whoami")`` names a route, not a file.
  * A SYSTEM ROOT (60): ``/bin``, ``/sbin``, ``/usr``, ``/etc``, ``/proc``,
    ``/sys``, ``/dev``, ``/var/run``, ``/opt``, ``/Library``, ``/System``,
    ``/Applications``. api's host-read fence tests hand ``/etc/passwd`` to the
    product precisely because it is a real file outside the fence; ``tmp_path``
    cannot express "a file the fence must refuse".
  * A PURE PATH CLASS (26): ``PurePath``, ``PurePosixPath``, ``PureWindowsPath``.
    They are string algebra and touch no filesystem by construction, which is
    how prax ``test_repo_root.py`` asserts that a POSIX path is not absolute to
    Windows.
  * A STRING OPERATION (10): ``startswith``, ``endswith``, ``split`` and their
    kin. The literal is a comparison operand that happens to be spelled as a
    call argument.
  * A DRIVE-LETTER literal (15 in 8 files) -- COUNTED and reported, never
    convicted. On a POSIX host ``tmp_path`` cannot produce ``C:\\proj\\AIPass``,
    so a rule that convicted memory's ``test_roots_lifecycle`` would be
    demanding a cross-OS test lie about its own subject. Same device
    ``named_encoding`` uses for latin-1: the count rides in the passing message
    so the number stays visible without being a verdict.

A NAME BOUND ONLY TO SUCH A LITERAL IS THE SAME HABIT, and is judged where the
name is USED (20 sites in 8 files: aipass ``test_adopt.py`` binds
``fake_home = "/fake/aipass/home"`` once and hands it to three calls). A name
bound to anything else anywhere in the file is dropped -- which value reaches
the call is a question one pass cannot answer. ARM A's ``_proc_bindings`` is the
precedent and the reason.

Two stated limits:

  * A literal containing WHITESPACE is not a path. hooks ``test_hook_test.py``
    binds a two-sentence refusal message that opens with ``/proj/...``; a rule
    without this guard convicts the prose. One site fleet-wide.
  * A literal that is never handed to a call -- a default argument, a bare
    return, an element of a list that is not itself an argument -- is not
    convicted. It is data until something uses it, and ARM A's measurement is
    why that line sits where it does.

The whole rule, measured 2026-09-22: 874 hits in 117 of 553 test files, 281 of
them the template's own shape, ``Path("/...")``.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "LITERAL_PATH"
STANDARD_KEY = "literal_path"

#: An absolute POSIX path: a slash followed by a path character. Bare "/" and
#: "//" are excluded by the second character -- a root separator alone carries
#: no habit to end.
_POSIX_ABS = re.compile(r"^/[A-Za-z0-9_.\-]")

#: A drive-rooted path. Counted, never convicted -- see the module docstring.
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


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


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
    reaches the call is then a question one pass cannot answer. Taken from
    ``host_portability`` ARM A's ``_proc_bindings``, for the same reason.
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


def _parse(source: str, what: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ruff already convicts a syntax error, and a line number invented for a
    statement Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[literal_path] Unparseable, nothing %s: %s", what, exc)
        return None


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, what was found, fix) for every literal absolute path in use."""
    tree = _parse(source, "scanned")
    if tree is None:
        return []

    bound = _path_bindings(tree)
    hits: List[Tuple[int, str, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _tail_name(node.func)
        for keyword_name, argument in _arguments(node):
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

    Counted, never convicted. ``tmp_path`` on a POSIX host cannot produce
    ``C:\\proj\\AIPass``, so a cross-OS test has no other way to spell its own
    subject.
    """
    tree = _parse(source, "counted")
    if tree is None:
        return []

    found: List[Tuple[int, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _tail_name(node.func)
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


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[literal_path] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


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
    """Check one test file for a literal absolute path handed to a call.

    Args:
        module_path: Path to the test file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
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

    # One line per hit, all inside ONE check rather than one check each --
    # checklist._format_failure prints the FIRST failed check and appends
    # "(+N more)", so N checks would show one hit and hide the rest.
    detail = "\n".join(f"{path.name}:{line} {name} - {fix}" for line, name, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
