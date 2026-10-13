# =================== AIPass ====================
# Name: rendered_path_oracle_check.py
# Description: Rendered Path Oracle Standards Checker Handler
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-13
# =============================================

"""
Rendered Path Oracle Standards Checker Handler

A test that asserts a PATH, spelled whole inside an f-string, against output a
console RENDERED. Green on Linux, red on Windows and macOS. The specimen is
@aipass's ``test_aipass_main.py``, ``TestMain.test_a_crash_whose_log_cannot_be_
written_still_ends_on_the_crash_not_a_traceback`` (PR #787)::

    log_home = tmp_path / "system_logs"
    ...
    _out, err = capsys.readouterr()
    assert f"... Permission denied: '{log_home}')" in err

TWO FRAGILITIES, and the second survives a cure for the first:

  WRAP. Rich wraps a line at the console's width (the fleet conftest pins
  200). A Windows tmp path (``C:\\Users\\runneradmin\\AppData\\Local\\Temp\\
  pytest-of-runneradmin\\...``) or macOS's ``/private/var/folders/...`` pushes
  the line past it, and the wrapped output no longer holds the substring.

  REPR. ``str(OSError)`` renders the filename with ``%r``, so on Windows the
  backslashes are DOUBLED, and ``'{log_home}'`` (single backslashes) never
  matches, wrap or not. A wider console does not cure this one.

THE CURE is a stable fragment: assert the message's words without the path,
and the path's ``.name`` (``"system_logs" in err``), or compare the path
through a channel nothing renders (a returned value, the exception's
``.filename``).

WHAT IS CONVICTED, inside one ``def test_*`` -- one finding per assert:

  NEEDLE: an f-string with a FormattedValue that is a PATH: the ``tmp_path``
  parameter itself, a name bound in the test to ``tmp_path`` /
  ``tmp_path_factory.mktemp(...)`` / an expression rooted at one (``/``,
  ``.joinpath``, ``.resolve()``, ...), a name bound to ``Path(...)`` /
  ``PurePath(...)`` and their siblings, ``str(<path>)``, or ``<path>.parent``.
  ``<path>.name`` / ``.stem`` / ``.suffix`` is NOT a path -- it is the cure.

  HAYSTACK: captured console output: a name from ``out, err =
  capsys.readouterr()`` (or ``capfd``), ``captured.out`` / ``.err`` on a name
  bound to ``readouterr()``, ``capsys.readouterr().out`` inline or bound, and
  ``result.output`` / ``.stdout`` / ``.stderr`` on a name bound to a
  ``CliRunner`` ``invoke`` or a ``subprocess.run``. A plain alias of one of
  these (``out = captured.out``) is the same value and is followed.

  THE COMPARE: ``needle in haystack``, ``not in``, and ``==`` / ``!=`` with
  the needle on either side.

HELD, never convicted: an f-string bound to a name first (``msg = f"..."``
then ``msg in err``), a haystack TRANSFORMED before the compare (``said =
" ".join(err.split())`` -- the specimen's own wrap cure, still REPR-fragile),
``check_output``'s return, ``tmpdir`` (py.path), and a path that reached the
test through a helper or a fixture other than ``tmp_path``. Each needs a data
flow the AST cannot settle in one function; guessing would convict cures.
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple, Union

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

#: Advisory, then ratchet. Fleet 2026-10-13, 762 test files: the specimen was
#: already cured by @aipass, and 9 asserts elsewhere convict (backup 8, devpulse
#: 1). branch_audit keeps an ADVISORY standard out of the gating average, so
#: landing it moves no branch's number; gate it once the nine are cured.
ADVISORY = True

STANDARD = "RENDERED_PATH_ORACLE"
STANDARD_KEY = "rendered_path_oracle"

TEST_PREFIX = "test_"

#: The fixture that IS a path.
TMP_PATH = "tmp_path"
#: The session factory whose ``mktemp`` returns one.
TMP_PATH_FACTORY = "tmp_path_factory"

#: Constructors that build a path from whatever they are given.
PATH_CONSTRUCTORS = frozenset({"Path", "PurePath", "PosixPath", "WindowsPath", "PurePosixPath", "PureWindowsPath"})

#: Methods of a path that return another path.
PATH_METHODS = frozenset({"joinpath", "resolve", "absolute", "with_name", "with_suffix", "with_stem", "expanduser"})

#: Attributes of a path that are themselves a path. ``.name``, ``.stem`` and
#: ``.suffix`` are absent on purpose: they are the cure.
PATH_ATTRIBUTES = frozenset({"parent"})

#: The capture fixtures whose ``readouterr()`` holds what the console printed.
CAPTURE_FIXTURES = frozenset({"capsys", "capfd"})

#: The streams of a ``readouterr()`` result.
CAPTURE_STREAMS = frozenset({"out", "err"})

#: The streams of a CliRunner or subprocess result.
RESULT_STREAMS = frozenset({"output", "stdout", "stderr"})

CURE = 'assert the words without the path, and the path\'s .name ("system_logs" in err)'

WHY = (
    "WRAP: Rich wraps at the console width and a Windows/macOS tmp path crosses it; "
    "REPR: an OSError renders the path with %r, doubling Windows backslashes"
)

FUNCTION_NODE = Union[ast.FunctionDef, ast.AsyncFunctionDef]


def _own_nodes(function: FUNCTION_NODE) -> Iterator[ast.AST]:
    """Every node in a test's body, not descending into a nested def or class.

    A name is bound in ONE function; a helper defined inside the test binds
    its own.
    """
    stack: List[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.append(child)


def _is_path(node: ast.AST, paths: Set[str]) -> bool:
    """Whether an expression is a filesystem path, by its shape and the test's bindings."""
    if isinstance(node, ast.Name):
        return node.id in paths
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path(node.left, paths)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_ATTRIBUTES and _is_path(node.value, paths)
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        if func.id in PATH_CONSTRUCTORS:
            return True
        return func.id == "str" and len(node.args) == 1 and _is_path(node.args[0], paths)
    if isinstance(func, ast.Attribute):
        if func.attr in PATH_CONSTRUCTORS:  # pathlib.Path(...)
            return True
        if func.attr == "mktemp" and isinstance(func.value, ast.Name) and func.value.id == TMP_PATH_FACTORY:
            return True
        return func.attr in PATH_METHODS and _is_path(func.value, paths)
    return False


def _is_readouterr(node: ast.AST) -> bool:
    """``capsys.readouterr()`` / ``capfd.readouterr()``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "readouterr"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in CAPTURE_FIXTURES
    )


def _is_runner_call(node: ast.AST, runners: Set[str]) -> bool:
    """A CliRunner ``invoke`` or a ``subprocess.run``: a result whose streams are output."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    func = node.func
    if func.attr == "run":
        return isinstance(func.value, ast.Name) and func.value.id == "subprocess"
    if func.attr != "invoke":
        return False
    base = func.value
    if isinstance(base, ast.Name):
        return base.id in runners
    return isinstance(base, ast.Call) and _call_name(base) == "CliRunner"


def _call_name(node: ast.Call) -> str:
    """The tail name a call is made through: ``a.b.C(...)`` -> ``C``."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


class _Bindings:
    """What each name in one test was bound to, as far as this rule cares."""

    def __init__(self) -> None:
        self.paths: Set[str] = set()
        self.output: Set[str] = set()  # a str of captured output
        self.captures: Set[str] = set()  # a readouterr() result
        self.results: Set[str] = set()  # a CliRunner / subprocess result
        self.runners: Set[str] = set()  # a CliRunner

    def is_haystack(self, node: ast.AST) -> bool:
        """Whether an expression is console output a test captured."""
        if isinstance(node, ast.Name):
            return node.id in self.output
        if not isinstance(node, ast.Attribute):
            return False
        base = node.value
        if node.attr in CAPTURE_STREAMS:
            if _is_readouterr(base):
                return True
            if isinstance(base, ast.Name) and base.id in self.captures:
                return True
        if node.attr in RESULT_STREAMS:
            return isinstance(base, ast.Name) and base.id in self.results
        return False

    def bind(self, target: ast.AST, value: ast.AST) -> bool:
        """Record one assignment; True when it taught the bindings something new."""
        before = self._size()
        if isinstance(target, ast.Tuple) and _is_readouterr(value):
            self.output.update(elt.id for elt in target.elts if isinstance(elt, ast.Name))
        elif isinstance(target, ast.Name):
            self._bind_name(target.id, value)
        return self._size() != before

    def _bind_name(self, name: str, value: ast.AST) -> None:
        """File one name under the first kind its value is."""
        kinds = (
            (self.paths, _is_path(value, self.paths)),
            (self.captures, _is_readouterr(value)),
            (self.output, self.is_haystack(value)),
            (self.results, _is_runner_call(value, self.runners)),
            (self.runners, isinstance(value, ast.Call) and _call_name(value) == "CliRunner"),
        )
        for bucket, matches in kinds:
            if matches:
                bucket.add(name)
                return

    def _size(self) -> int:
        """How much is known, so a pass can tell whether it learned anything."""
        return len(self.paths) + len(self.output) + len(self.captures) + len(self.results) + len(self.runners)


def _assignments(nodes: List[ast.AST]) -> List[Tuple[ast.AST, ast.AST]]:
    """(target, value) for every simple binding in a test, in source order."""
    pairs: List[Tuple[int, ast.AST, ast.AST]] = []
    for node in nodes:
        if isinstance(node, ast.Assign):
            pairs.extend((node.lineno, target, node.value) for target in node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pairs.append((node.lineno, node.target, node.value))
        elif isinstance(node, ast.NamedExpr):
            pairs.append((node.lineno, node.target, node.value))
    return [(target, value) for _line, target, value in sorted(pairs, key=lambda p: p[0])]


def _bindings(function: FUNCTION_NODE, nodes: List[ast.AST]) -> _Bindings:
    """The test's bindings, closed to a fixed point (an alias may precede its source in walk order)."""
    known = _Bindings()
    params = function.args.posonlyargs + function.args.args + function.args.kwonlyargs
    if any(arg.arg == TMP_PATH for arg in params):
        known.paths.add(TMP_PATH)
    pairs = _assignments(nodes)
    learned = True
    while learned:
        learned = False
        for target, value in pairs:
            learned = known.bind(target, value) or learned
    return known


def _path_in(needle: ast.AST, paths: Set[str]) -> str:
    """The source of the first path an f-string renders, or '' when it renders none."""
    if not isinstance(needle, ast.JoinedStr):
        return ""
    for part in needle.values:
        if isinstance(part, ast.FormattedValue) and _is_path(part.value, paths):
            return ast.unparse(part.value)
    return ""


def _offence(compare: ast.Compare, known: _Bindings) -> Tuple[str, str]:
    """(path, haystack) when this compare renders a path into captured output, else ('', '')."""
    if len(compare.ops) != 1:
        return "", ""
    left, op, right = compare.left, compare.ops[0], compare.comparators[0]
    if isinstance(op, (ast.In, ast.NotIn)):
        pairs = [(left, right)]
    elif isinstance(op, (ast.Eq, ast.NotEq)):
        pairs = [(left, right), (right, left)]
    else:
        return "", ""
    for needle, haystack in pairs:
        path = _path_in(needle, known.paths)
        if path and known.is_haystack(haystack):
            return path, ast.unparse(haystack)
    return "", ""


def _tests(tree: ast.Module) -> Iterator[FUNCTION_NODE]:
    """Every ``def test_*``, at module level or in a class."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(TEST_PREFIX):
            yield node


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[rendered_path_oracle] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str) -> List[Tuple[int, str, str, str]]:
    """(line, test name, path expression, haystack) for every offending assert."""
    tree = _parse(source)
    if tree is None:
        return []
    found: List[Tuple[int, str, str, str]] = []
    for function in _tests(tree):
        nodes = list(_own_nodes(function))
        known = _bindings(function, nodes)
        if not known.paths:
            continue
        for node in nodes:
            if not isinstance(node, ast.Assert):
                continue
            for compare in (n for n in ast.walk(node.test) if isinstance(n, ast.Compare)):
                path, haystack = _offence(compare, known)
                if path:
                    found.append((node.lineno, function.name, path, haystack))
                    break
    return sorted(found)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[rendered_path_oracle] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Rendered path oracle", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for a whole path asserted against rendered console output.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

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

    findings = scan(source)
    if not findings:
        return _result(True, _one_check(True, "No path is asserted whole against rendered output"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per assert would hide the rest.
    detail = "\n".join(
        f"{path.name}:{line} {name} — f-string renders path {{{expr}}} into {haystack}. {WHY} - {CURE}"
        for line, name, expr, haystack in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
