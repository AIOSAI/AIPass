# =================== AIPass ====================
# Name: mock_repr_path.py
# Description: Windows compat - a path asserted against the repr of a mock call (advisory arm, tests)
# Version: 1.0.0
# Created: 2026-09-18
# Modified: 2026-09-18
# =============================================

r"""
Windows compat -- a path asserted against the repr of a mock call.

The incident (CI 35416653326, Windows): three of flow's lock tests built
``" ".join(str(c) for c in mock_logger.error.call_args_list)`` and asserted
``str(lock) in logged``.  ``str(call(...))`` is the mock call's repr, and repr
escapes a backslash, so the Windows path ``C:\Users\...`` is spelled
``C:\\Users\\...`` in that text and the substring check fails.  A POSIX path
has no backslash for repr to escape -- the text is a fixed point there -- so no
Linux or macOS run can go red on it.

The shape, read per function with a small name-flow pass:

* REPR TEXT -- ``str()``, ``repr()`` or an f-string of a mock call record:
  ``m.call_args``, ``m.call_args_list``, ``m.mock_calls``, an element of one
  (a loop or comprehension variable), or its ``.args`` / ``.kwargs`` / ``[0]``
  containers.  A str of a tuple is a repr of its members too.  Joins, slices,
  case changes and names bound to any of these carry it.
* PATH TEXT -- ``str()`` / ``os.fspath()`` / an f-string of a path object: the
  ``tmp_path`` / ``tmpdir`` fixture, ``Path(...)``, ``tempfile`` and
  ``os.path`` results, and anything built from those with ``/``,
  ``.with_suffix()``, ``.parent`` and the other path-returning members.
* The sink -- ``in`` / ``not in`` / ``==`` / ``!=`` with PATH TEXT on one side
  and REPR TEXT on the other, or ``.count/.find/.index/.startswith/.endswith``
  of REPR TEXT given PATH TEXT.  ``in`` goes red on Windows; ``not in`` passes
  there without checking anything.

Deliberately NOT flagged:

* A real message string: ``c.args[0]``, ``m.call_args[0][0]``,
  ``c.kwargs["msg"]`` -- one level inside the args container, the value itself.
  That is the cure.
* A path side that repr cannot change: ``.name`` / ``.stem`` / ``.suffix``,
  ``.as_posix()`` / ``.as_uri()``, ``Path("one_part")``.
* A path side the test already escaped: ``repr(str(p))``, ``str(p).replace(...)``,
  or a repr text passed through ``.replace(...)``.
* A test inside a ``sys.platform`` / ``os.name`` guard or skipif.

Known misses, named rather than hidden: a path the test reaches only through a
fixture with an ordinary name (``def test_x(self, branch):``), an attribute
(``self.lock``) or a helper's return value -- the flow pass reads names bound
in the function and the two tmp fixtures, nothing else.  A ``%``-format or
``.format()`` of a path is read as opaque.  ``lock.as_posix() in logged`` is
not flagged although it fails on Windows too when the product logged
``str(lock)``: which spelling the product used is not in the test.

Pure: takes a parsed tree, never touches the disk.
"""

import ast
from typing import Iterator

CALLS = "calls"  # a list of call records
CALL = "call"  # one call record
ARGS = "args"  # a call record's args tuple / kwargs dict
REPR = "repr"  # text holding a repr of any of the three above
REPRS = "reprs"  # a sequence of REPR texts
PATH = "path"  # a path object, or text spelling a path natively

_RECORD_KINDS = frozenset({CALLS, CALL, ARGS})

_CALL_LISTS = frozenset({"call_args_list", "mock_calls", "method_calls", "await_args_list"})
_CALL_RECORDS = frozenset({"call_args", "await_args"})
_ARGS_MEMBERS = frozenset({"args", "kwargs"})

_TMP_FIXTURES = frozenset({"tmp_path", "tmpdir"})
_PATH_CLASSES = frozenset({"Path", "PurePath", "WindowsPath", "PureWindowsPath", "PosixPath", "PurePosixPath"})
_PATH_METHODS = frozenset(
    {"with_suffix", "with_name", "with_stem", "joinpath", "resolve", "absolute", "expanduser", "relative_to", "mktemp"}
)
_PATH_ATTRS = frozenset({"parent"})
_PATH_FACTORIES = frozenset({("tempfile", "mkdtemp"), ("tempfile", "gettempdir"), ("os", "getcwd"), ("os", "fspath")})
_OS_PATH_FUNCS = frozenset({"join", "abspath", "realpath", "normpath", "dirname", "expanduser"})
_TEXT_KEEPERS = frozenset({"lower", "upper", "casefold", "strip", "lstrip", "rstrip"})
_SEARCH_METHODS = frozenset({"count", "find", "index", "rfind", "rindex", "startswith", "endswith"})

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _dotted(node: ast.expr) -> tuple[str, ...]:
    """``a.b.c`` as ("a", "b", "c"); empty when any link is not a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ()
    parts.append(node.id)
    return tuple(reversed(parts))


def _single_part_constant(args: list[ast.expr]) -> bool:
    """``Path("name")`` -- one constant with no separator: nothing for repr to escape."""
    return (
        len(args) == 1
        and isinstance(args[0], ast.Constant)
        and isinstance(args[0].value, str)
        and "/" not in args[0].value
        and "\\" not in args[0].value
    )


def _bind(target: ast.expr, kind: str | None, env: dict[str, str]) -> None:
    """Record a binding; a tuple target unpacks a call record into its containers."""
    if kind is None:
        return
    if isinstance(target, ast.Name):
        env.setdefault(target.id, kind)
    elif isinstance(target, (ast.Tuple, ast.List)):
        inner = ARGS if kind == CALL else (REPR if kind == REPRS else None)
        for elt in target.elts:
            _bind(elt, inner, env)


def _element_kind(kind: str | None) -> str | None:
    """The kind of one item when iterating a value of this kind."""
    return {CALLS: CALL, REPRS: REPR}.get(kind or "")


def _comprehension_env(node: ast.expr, env: dict[str, str]) -> dict[str, str]:
    local = dict(env)
    for gen in getattr(node, "generators", []):
        local.pop(getattr(gen.target, "id", ""), None)
        _bind(gen.target, _element_kind(classify(gen.iter, local)), local)
    return local


def _classify_call(node: ast.Call, env: dict[str, str]) -> str | None:
    func = node.func
    name = _dotted(func)
    first = classify(node.args[0], env) if node.args else None
    if isinstance(func, ast.Name):
        if func.id in ("str", "repr") and len(node.args) == 1:
            if first in _RECORD_KINDS:
                return REPR
            return first if func.id == "str" and first in (PATH, REPR) else None
        if func.id == "map" and len(node.args) == 2 and _dotted(node.args[0]) in (("str",), ("repr",)):
            return REPRS if classify(node.args[1], env) in (CALLS, ARGS) else None
        if func.id in ("list", "tuple", "sorted") and node.args:
            return first if first in (CALLS, REPRS) else None
        if func.id in _PATH_CLASSES:
            return None if _single_part_constant(node.args) else PATH
        return None
    if not isinstance(func, ast.Attribute):
        return None
    if name[-1:] and name[-1] in _PATH_CLASSES:
        return None if _single_part_constant(node.args) else PATH
    if name[-2:] and name[-2] in _PATH_CLASSES and func.attr in ("home", "cwd"):
        return PATH
    if name[-2:] in _PATH_FACTORIES:
        return PATH if func.attr != "fspath" or first == PATH else None
    if name[-3:-1] == ("os", "path") and func.attr in _OS_PATH_FUNCS:
        return PATH
    owner = classify(func.value, env)
    if func.attr == "join" and node.args and owner is None:
        return REPR if classify(node.args[0], env) == REPRS else None
    if owner == REPR and func.attr in _TEXT_KEEPERS:
        return REPR
    if owner == REPR and func.attr == "splitlines":
        return REPRS
    if owner == PATH and func.attr in _PATH_METHODS:
        return PATH
    if name[-1:] == ("mktemp",) and name[:1] == ("tmp_path_factory",):
        return PATH
    return None


def classify(node: ast.expr, env: dict[str, str]) -> str | None:
    """The kind of value an expression holds, or None when it is none of ours."""
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Attribute):
        if node.attr in _CALL_LISTS:
            return CALLS
        if node.attr in _CALL_RECORDS:
            return CALL
        owner = classify(node.value, env)
        if owner == CALL and node.attr in _ARGS_MEMBERS:
            return ARGS
        if owner == PATH and node.attr in _PATH_ATTRS:
            return PATH
        return None
    if isinstance(node, ast.Subscript):
        owner = classify(node.value, env)
        return {CALLS: CALL, CALL: ARGS, REPR: REPR, REPRS: REPR}.get(owner or "")
    if isinstance(node, ast.Call):
        return _classify_call(node, env)
    if isinstance(node, ast.BinOp):
        sides = {classify(node.left, env), classify(node.right, env)}
        if isinstance(node.op, ast.Div) and PATH in sides:
            return PATH
        if isinstance(node.op, ast.Add):
            return REPR if REPR in sides else (PATH if PATH in sides else None)
        return None
    if isinstance(node, ast.JoinedStr):
        formatted = [v.value for v in node.values if isinstance(v, ast.FormattedValue) and v.conversion != ord("r")]
        kinds = {classify(v, env) for v in formatted}
        return REPR if kinds & _RECORD_KINDS else (PATH if PATH in kinds else None)
    if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        inner = classify(node.elt, _comprehension_env(node, env))
        return REPRS if inner == REPR else (CALLS if inner == CALL else None)
    if isinstance(node, ast.IfExp):
        return classify(node.body, env) or classify(node.orelse, env)
    return None


def _own_statements(func: ast.AST) -> Iterator[ast.AST]:
    """Every node in a function body, not descending into nested scopes."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*_SCOPES, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _node_bindings(node: ast.AST) -> list[tuple[ast.expr, ast.expr, bool]]:
    """(target, value, iterated) for the names one statement binds."""
    if isinstance(node, ast.Assign):
        return [(target, node.value, False) for target in node.targets]
    if isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
        return [(node.target, node.value, False)]
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [(node.target, node.iter, True)]
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return [(node.optional_vars, node.context_expr, False)]
    return []


def _bindings(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.expr, ast.expr, bool]]:
    """Every binding in a function's own body, in source order."""
    bindings = [binding for node in _own_statements(func) for binding in _node_bindings(node)]
    return sorted(bindings, key=lambda b: (b[1].lineno, b[1].col_offset))


def function_env(func: ast.FunctionDef | ast.AsyncFunctionDef, outer: dict[str, str]) -> dict[str, str]:
    """Names bound in one function, classified; fixture params and the enclosing env seed it."""
    env = dict(outer)
    for arg in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]:
        env.pop(arg.arg, None)
        if arg.arg in _TMP_FIXTURES:
            env[arg.arg] = PATH
    bindings = _bindings(func)
    for _ in range(4):
        before = dict(env)
        for target, value, iterated in bindings:
            kind = classify(value, env)
            _bind(target, _element_kind(kind) if iterated else kind, env)
        if env == before:
            break
    return env


def _pairs(node: ast.Compare) -> Iterator[tuple[ast.expr, ast.cmpop, ast.expr]]:
    operands = [node.left, *node.comparators]
    for index, op in enumerate(node.ops):
        yield operands[index], op, operands[index + 1]


def _judge_compare(node: ast.Compare, env: dict[str, str]) -> str | None:
    for left, op, right in _pairs(node):
        kinds = (classify(left, env), classify(right, env))
        if isinstance(op, ast.In) and kinds == (PATH, REPR):
            return "a path is searched for in a mock call's repr - repr doubles each Windows backslash, red on Windows"
        if isinstance(op, ast.NotIn) and kinds == (PATH, REPR):
            return "a path is ruled out of a mock call's repr - repr doubles each Windows backslash, vacuous on Windows"
        if isinstance(op, (ast.Eq, ast.NotEq)) and set(kinds) == {PATH, REPR}:
            return "a path is compared with a mock call's repr - repr doubles each Windows backslash"
    return None


def _judge_search(node: ast.Call, env: dict[str, str]) -> str | None:
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in _SEARCH_METHODS and node.args):
        return None
    if classify(func.value, env) == REPR and classify(node.args[0], env) == PATH:
        return f"a path is searched for with .{func.attr}() in a mock call's repr - repr doubles each Windows backslash"
    return None


def _scan(node: ast.AST, env: dict[str, str], found: dict[int, str]) -> None:
    """Walk one function's expressions, entering comprehensions with their own names bound."""
    if isinstance(node, (*_SCOPES, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, _COMPREHENSIONS):
        env = _comprehension_env(node, env)
    verdict = None
    if isinstance(node, ast.Compare):
        verdict = _judge_compare(node, env)
    elif isinstance(node, ast.Call):
        verdict = _judge_search(node, env)
    if verdict and isinstance(node, ast.expr):
        found.setdefault(node.lineno, verdict)
    for child in ast.iter_child_nodes(node):
        _scan(child, env, found)


def _functions(node: ast.AST, outer: dict[str, str], skipped: bool) -> Iterator[tuple[ast.AST, dict[str, str], bool]]:
    """Every function with its classified env and whether a platform skip covers it."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _functions(child, {}, skipped or _platform_skipped(child.decorator_list))
        elif isinstance(child, _SCOPES):
            env = function_env(child, outer)
            here = skipped or _platform_skipped(child.decorator_list)
            yield child, env, here
            yield from _functions(child, env, here)
        elif not isinstance(child, ast.Lambda):
            yield from _functions(child, outer, skipped)


def _references_platform(node: ast.expr) -> bool:
    return any(_dotted(n) in (("sys", "platform"), ("os", "name")) for n in ast.walk(node) if isinstance(n, ast.expr))


def _platform_skipped(decorators: list[ast.expr]) -> bool:
    """A skipif naming sys.platform / os.name, or a bare skip."""
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _dotted(target)
        if name[:2] != ("pytest", "mark"):
            continue
        if name[-1:] == ("skip",):
            return True
        if name[-1:] == ("skipif",) and isinstance(dec, ast.Call) and any(_references_platform(a) for a in dec.args):
            return True
    return False


def find_mock_repr_paths(tree: ast.Module, platform_guarded: set[int]) -> list[tuple[int, str]]:
    """Paths asserted against the repr text of a mock call.

    Args:
        tree: Parsed module.
        platform_guarded: Line numbers inside sys.platform / os.name guards.

    Returns:
        (line, description) per offending comparison, in source order.
    """
    found: dict[int, str] = {}
    for func, env, skipped in _functions(tree, {}, False):
        if skipped:
            continue
        for stmt in getattr(func, "body", []):
            _scan(stmt, env, found)
    return sorted((line, desc) for line, desc in found.items() if line not in platform_guarded)
