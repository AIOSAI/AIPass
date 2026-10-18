# =================== AIPass ====================
# Name: text_fixture_bytes_oracle.py
# Description: Windows compat - a text-mode fixture with a newline meets a bytes oracle (advisory arm, tests)
# Version: 1.0.0
# Created: 2026-10-15
# Modified: 2026-10-17
# =============================================

r"""
Windows compat -- a fixture written in text mode, checked as bytes.

Pure: takes a parsed tree, never touches the disk. Reference: windows_compat.md.
"""

import ast
from typing import Iterator

from aipass.seedgo.apps.handlers.aipass_standards.mock_repr_path import (
    PATH,
    classify,
    function_env,
    helper_table,
    platform_skipped,
)

FILE_BYTES = "file_bytes"  # bytes read off the disk
DIGEST = "digest"  # a hash of FILE_BYTES
LENGTH = "length"  # len() of FILE_BYTES
LIT_BYTES = "lit_bytes"  # a bytes literal, or a str literal's .encode()
LIT_DIGEST = "lit_digest"  # a str / bytes literal, or a digest of LIT_BYTES
LIT_LENGTH = "lit_length"  # an int literal, or len() of LIT_BYTES
NL_TEXT = "nl_text"  # str literal content holding a newline
HANDLE = "handle"  # a file opened for text-mode writing

_SINKS = {
    FILE_BYTES: (LIT_BYTES, "bytes"),
    DIGEST: (LIT_DIGEST, "a digest of the bytes"),
    LENGTH: (LIT_LENGTH, "the byte length"),
}

_DIGEST_METHODS = frozenset({"hexdigest", "digest"})
_NO_TRANSLATION = frozenset({"", "\n"})
_WRITE_MODE_CHARS = frozenset("wax+")

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _str_has_newline(node: ast.expr, env: dict[str, str]) -> bool:
    """A str literal, an f-string's literal parts or a name bound to either, holding a newline."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and "\n" in node.value
    if isinstance(node, ast.JoinedStr):
        return any(_str_has_newline(part, env) for part in node.values if isinstance(part, ast.Constant))
    if isinstance(node, ast.Name):
        return env.get(node.id) == NL_TEXT
    return False


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _translates(call: ast.Call) -> bool:
    """False when the call passes newline="" / newline="\\n": no translation on write."""
    newline = _kw(call, "newline")
    return not (isinstance(newline, ast.Constant) and newline.value in _NO_TRANSLATION)


def _text_write_mode(call: ast.Call, mode_index: int) -> bool:
    mode = call.args[mode_index] if len(call.args) > mode_index else _kw(call, "mode")
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return False
    return "b" not in mode.value and bool(_WRITE_MODE_CHARS & set(mode.value))


def _opens_text_for_writing(node: ast.expr) -> bool:
    """``open(x, "w")`` / ``io.open(x, "w")`` / ``P.open("w")`` without a no-translation newline."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return _text_write_mode(node, 1) and _translates(node)
    if isinstance(func, ast.Attribute) and func.attr == "open":
        index = 1 if isinstance(func.value, ast.Name) and func.value.id == "io" else 0
        return _text_write_mode(node, index) and _translates(node)
    return False


def _own_nodes(func: ast.AST) -> Iterator[ast.AST]:
    """Every node in a function body, not descending into nested scopes."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*_SCOPES, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _assignments(func: ast.AST) -> list[tuple[ast.expr, ast.expr]]:
    """(target, value) for plain-name bindings in a function's own body, in source order."""
    pairs: list[tuple[ast.expr, ast.expr]] = []
    for node in _own_nodes(func):
        if isinstance(node, ast.Assign):
            pairs.extend((target, node.value) for target in node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            pairs.append((node.target, node.value))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            pairs.append((node.optional_vars, node.context_expr))
    return sorted(pairs, key=lambda pair: (pair[1].lineno, pair[1].col_offset))


def _is_hashlib_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "hashlib"
        and len(node.args) == 1
    )


def kind_of(node: ast.expr, env: dict[str, str]) -> str | None:
    """The oracle-side kind of an expression, or None when it is none of ours."""
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bytes):
            return LIT_BYTES
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return LIT_LENGTH
        return NL_TEXT if _str_has_newline(node, env) else None
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "len" and len(node.args) == 1:
        inner = kind_of(node.args[0], env)
        return {FILE_BYTES: LENGTH, LIT_BYTES: LIT_LENGTH}.get(inner or "")
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr == "read_bytes" and not node.args:
        return FILE_BYTES
    if func.attr == "encode" and isinstance(func.value, (ast.Constant, ast.JoinedStr)):
        return LIT_BYTES
    if func.attr in _DIGEST_METHODS and _is_hashlib_call(func.value):
        inner = kind_of(func.value.args[0], env)  # type: ignore[attr-defined]
        return {FILE_BYTES: DIGEST, LIT_BYTES: LIT_DIGEST}.get(inner or "")
    return None


def _digest_literal(node: ast.expr) -> bool:
    """A hex string or a bytes digest spelled in the test."""
    return isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))


def _oracle_env(func: ast.AST) -> dict[str, str]:
    env: dict[str, str] = {}
    for target, value in _assignments(func):
        if isinstance(target, ast.Name):
            kind = kind_of(value, env)
            if kind is None and _opens_text_for_writing(value):
                kind = HANDLE
            if kind is not None:
                env.setdefault(target.id, kind)
            elif _digest_literal(value):
                env.setdefault(target.id, LIT_DIGEST)
    return env


def _side_matches(node: ast.expr, kind: str | None, wanted: str) -> bool:
    """The literal side a sink wants; a digest also takes any str / bytes literal."""
    if kind == wanted:
        return True
    return wanted == LIT_DIGEST and (_digest_literal(node) or kind == LIT_BYTES)


def _judge(node: ast.Compare, env: dict[str, str]) -> str | None:
    operands = [node.left, *node.comparators]
    for index, op in enumerate(node.ops):
        if not isinstance(op, (ast.Eq, ast.NotEq)):
            continue
        pair = (operands[index], operands[index + 1])
        kinds = [kind_of(side, env) for side in pair]
        for here, there in ((0, 1), (1, 0)):
            sink = _SINKS.get(kinds[here] or "")
            if sink and _side_matches(pair[there], kinds[there], sink[0]):
                return (
                    f"{sink[1]} read off the disk compared with a literal, but a fixture here was written in text "
                    "mode with a newline - write_text / open('w') writes each \\n as \\r\\n on Windows, red there; "
                    "write the fixture with write_bytes(b'...') or pass newline=''"
                )
    return None


def _writes_newline_text(func: ast.AST, path_env: dict[str, str]) -> bool:
    """A text-mode write of literal content holding a newline, in this function's own body."""
    env = _oracle_env(func)
    for node in _own_nodes(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr, owner = node.func.attr, node.func.value
        content = node.args[0] if node.args else _kw(node, "data")
        if attr == "write_text" and content is not None:
            if classify(owner, path_env) == PATH and _str_has_newline(content, env) and _translates(node):
                return True
        if attr in ("write", "writelines") and content is not None:
            text_handle = (isinstance(owner, ast.Name) and env.get(owner.id) == HANDLE) or _opens_text_for_writing(
                owner
            )
            items = content.elts if isinstance(content, (ast.List, ast.Tuple)) else [content]
            if text_handle and any(_str_has_newline(item, env) for item in items):
                return True
    return False


def _reached_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Same-module names a function can reach: its parameters (fixtures) and functions it calls by name."""
    names = {arg.arg for arg in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]}
    for node in _own_nodes(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            receiver = target.value.id
            if receiver in ("self", "cls") or receiver[:1].isupper():
                names.add(target.attr)
    return names


class _Module:
    """Which functions of one module write a text-mode newline fixture, directly or through what they reach."""

    def __init__(self, tree: ast.Module) -> None:
        self.helpers = helper_table(tree)
        self.defs: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        for node in ast.walk(tree):
            if isinstance(node, _SCOPES) and not node.name.startswith("test"):
                self.defs.setdefault(node.name, []).append(node)
        self._memo: dict[int, bool] = {}

    def has_fixture(self, func: ast.FunctionDef | ast.AsyncFunctionDef, seen: frozenset[int] = frozenset()) -> bool:
        """True when the function, or a same-module fixture / helper it reaches, writes the fixture."""
        key = id(func)
        if key in self._memo:
            return self._memo[key]
        if key in seen:
            return False
        found = _writes_newline_text(func, function_env(func, self.helpers))
        if not found:
            reached = [helper for name in _reached_names(func) for helper in self.defs.get(name, [])]
            found = any(self.has_fixture(helper, seen | {key}) for helper in reached if helper is not func)
        self._memo[key] = found
        return found


def _tests(node: ast.AST, skipped: bool) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]]:
    """Every test function with whether a platform skip covers it."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _tests(child, skipped or platform_skipped(child.decorator_list))
        elif isinstance(child, _SCOPES):
            if child.name.startswith("test"):
                yield child, skipped or platform_skipped(child.decorator_list)
        elif not isinstance(child, ast.Lambda):
            yield from _tests(child, skipped)


def find_text_fixture_bytes_oracles(tree: ast.Module, platform_guarded: set[int]) -> list[tuple[int, str]]:
    """Bytes oracles in tests whose fixture was written in text mode with a newline."""
    module = _Module(tree)
    found: dict[int, str] = {}
    for func, skipped in _tests(tree, False):
        if skipped:
            continue
        env = _oracle_env(func)
        for node in _own_nodes(func):
            if isinstance(node, ast.Compare):
                verdict = _judge(node, env)
                if verdict and node.lineno not in platform_guarded and module.has_fixture(func):
                    found.setdefault(node.lineno, verdict)
    return sorted(found.items())
