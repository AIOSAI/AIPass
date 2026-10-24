# =================== AIPass ====================
# Name: clear_text_secret_logging_check.py
# Description: Clear Text Secret Logging Standards Checker Handler
# Version: 1.3.1
# Created: 2026-10-10
# Modified: 2026-10-24
# =============================================

"""Clear Text Secret Logging Standards Checker Handler

Reference: clear_text_secret_logging.md
"""

from functools import partial
import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import read_text, result

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "CLEAR_TEXT_SECRET_LOGGING"
STANDARD_KEY = "clear_text_secret_logging"

#: The prax logger's levels; each is a sink in SystemLogger.
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "critical", "exception"})

#: The receiver every branch imports the prax logger as.
LOGGER_NAMES = frozenset({"logger"})

#: The names an ``from aipass.prax... import`` binds a logger under.
PRAX_LOGGER_EXPORTS = frozenset({"logger", "system_logger"})

#: The dispatch's secret words, each as the run of whole segments it must match.
SECRET_WORDS: Tuple[Tuple[str, ...], ...] = (
    ("secret",),
    ("secrets",),
    ("token",),
    ("tokens",),
    ("password",),
    ("passwords",),
    ("passwd",),
    ("api", "key"),
    ("apikey",),
    ("credential",),
    ("credentials",),
    ("bearer",),
    ("auth", "header"),
    ("access", "key"),
    ("private", "key"),
    ("trusted",),
    ("confidential",),
)

#: The secret words whose CALL result seeds arm 2: CodeQL's own source words.
#: ``untrusted`` is its own segment, so never matches; token and password calls stay arm 1.
CALL_SOURCE_WORDS = frozenset({"secret", "secrets", "trusted", "confidential"})

#: CodeQL's not-a-source words: a call name holding one anywhere seeds nothing.
SOURCE_EXCLUSIONS = (
    "hash",
    "md5",
    "sha",
    "random",
    "encode",
    "encrypt",
    "public",
    "user",
    "login",
    "logging",
    "clear",
    "redact",
)

#: Words that never SEED arm 2 from a binding or an attribute (arm 1 still reads them):
#: a token is a parser word in this fleet (argparse's ``args.tokens``).
QUIET_SEED_WORDS = frozenset({"token", "tokens"})

#: Verbs of a call that PUTS a secret somewhere: its result is a status, not the secret.
SETTER_VERBS = frozenset({"set", "write", "save", "put", "delete", "remove", "drop", "rotate", "revoke"})

#: A segment beside the secret word that makes the identifier name the secret, not hold it.
IDENTIFIER_SEGMENTS = frozenset(
    {
        "id",
        "ids",
        "count",
        "counts",
        "n",
        "num",
        "store",
        "path",
        "paths",
        "name",
        "names",
        "slug",
        "file",
        "filename",
        "dir",
        "label",
        "kind",
        "type",
        "len",
        "length",
        "size",
    }
)

#: Segments of a call name that redact what it is handed.
REDACTIONS = frozenset({"redact", "redacted", "mask", "masked", "scrub", "scrubbed", "len"})

#: The most characters of a secret a slice may show and still be a redaction.
MAX_SHOWN = 4

#: Calls that hand their argument's value on unchanged, for this rule's purpose.
PASS_THROUGH_CALLS = frozenset(
    {"str", "repr", "Path", "fspath", "sorted", "list", "tuple", "set", "frozenset", "dict", "reversed"}
)

#: Reads whose result is (part of) the value they are called on. Only the receiver
#: carries: a ``.get(k, default)`` default is not followed.
FOLLOWED_READS = frozenset({"get", "pop", "setdefault", "items", "keys", "values"})

#: Adds that put a value into the collection they are called on.
#: ``seen.append(key)`` binds ``seen``. ``insert(i, x)`` is judged on ``x`` only.
FOLLOWED_ADDS = frozenset({"append", "extend", "add", "insert"})

#: Whether a dict literal holding a built key or value is built.
FOLLOW_DICT_LITERALS = True

#: Verbs of a def that READS a secret document out of a store (get_secret, read_secret).
READER_VERBS = frozenset({"get", "read", "load", "fetch"})

#: The verb of a def that LISTS a store's documents (list_secrets): it returns
#: names, never a secret, so it is no reader; its parameters are the namespace.
LISTER_VERBS = frozenset({"list"})

#: Message keywords a log call may pass its message under instead of the first argument.
MESSAGE_KEYWORDS = frozenset({"msg", "message"})

#: Comprehensions: their result is built from what they iterate.
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)

#: String methods whose result is still the value they were called on.
STRING_METHODS = frozenset({"strip", "lstrip", "rstrip", "lower", "upper", "casefold", "decode", "encode"})

#: Logging keywords that are not part of the message.
NON_MESSAGE_KEYWORDS = frozenset({"exc_info", "stack_info", "stacklevel", "extra"})

#: How many passes the file-local derivation may take to settle.
MAX_PASSES = 10

CURE = (
    "log the field's name, its len() or its last four characters, or redact()/mask() it - "
    "and when the value is no secret, rename it so the line no longer says it is"
)

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")


def segments(identifier: str) -> List[str]:
    """An identifier's lower-case segments: snake_case and camelCase both split."""
    return [part for part in _CAMEL.sub(r"\1_\2", identifier).lower().split("_") if part]


def secret_word(identifier: str) -> str | None:
    """The secret word an identifier holds as whole segments, or None.

    None too when another segment says the identifier NAMES a secret (token_id)
    or redacts one (redact_secret).
    """
    parts = segments(identifier)
    for word in SECRET_WORDS:
        width = len(word)
        for start in range(len(parts) - width + 1):
            if tuple(parts[start : start + width]) != word:
                continue
            others = parts[:start] + parts[start + width :]
            if any(part in IDENTIFIER_SEGMENTS or part in REDACTIONS for part in others):
                return None
            return "_".join(word)
    return None


def _identifier(expr: ast.expr) -> str | None:
    """The name a Name, Attribute or Call reads under."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Call):
        return _identifier(expr.func)
    return None


def _is_redaction(name: str) -> bool:
    """Whether a call name redacts what it is handed."""
    return any(part in REDACTIONS for part in segments(name))


def _call_seeds(name: str) -> bool:
    """Whether a call so named returns a secret, by CodeQL's source model."""
    if secret_word(name) not in CALL_SOURCE_WORDS:
        return False
    if any(word in name.lower() for word in SOURCE_EXCLUSIONS):
        return False
    return not any(part in SETTER_VERBS for part in segments(name))


class _Handed(str):
    """A derived origin that reached a function through its parameter ``param``.

    A return built from it says the function passes that parameter through;
    it does not taint every call of the function, only a call that hands the
    parameter a derived value (the same-file hop).
    """

    param: str

    def __new__(cls, origin: str, param: str) -> "_Handed":
        handed = super().__new__(cls, origin)
        handed.param = param
        return handed


def _int_bound(node: ast.expr | None) -> int | None:
    """A slice bound as an int, or None when it is absent or not a literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _int_bound(node.operand)
        return -inner if inner is not None else None
    return None


def _shows_little(piece: ast.Slice) -> bool:
    """A slice that shows at most MAX_SHOWN characters: [-4:], [:4], [0:3]."""
    if piece.step is not None:
        return False
    lower, upper = _int_bound(piece.lower), _int_bound(piece.upper)
    if piece.upper is None and lower is not None and -MAX_SHOWN <= lower < 0:
        return True
    start = 0 if piece.lower is None else lower
    return start is not None and start >= 0 and upper is not None and 0 <= upper - start <= MAX_SHOWN


def _source_text(expr: ast.expr) -> str:
    """Short source text for a row."""
    text = ast.unparse(expr)
    return text if len(text) <= 60 else text[:57] + "..."


class _File:
    """One parsed file: its functions, and what is derived from a secret in each scope."""

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.functions: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, node)
        self.derived: Dict[ast.AST, Dict[str, str]] = {tree: {}}
        self.returns: Dict[ast.AST, str] = {}
        # The same-file hop: the parameters a function hands back in its
        # return. A call's result is derived when it hands one of these a
        # derived value; a call that hands them clean values stays clean.
        self.passes: Dict[ast.AST, Set[str]] = {}
        # Comprehension targets bound to what they iterate, while one is read.
        self.overlay: Dict[str, str] = {}
        self.loggers = _logger_names(tree)
        # Arm 2 starts only from a secret-named module-level binding, attribute read or
        # source call; never from a parameter, loop or with target or function-local name.
        # A secret-named Name, Attribute or Call ON the log line is still arm 1 (scan sets this).
        self.reading_log_line = False
        self.module_secrets = _module_secret_bindings(tree)
        self.scope_locals: Dict[ast.AST, Set[str]] = {tree: set()}

    def _starts_arm_two(self, expr: ast.Name | ast.Attribute, scope: ast.AST) -> bool:
        """Whether a secret-named reference may seed the derivation (see __init__)."""
        if secret_word(_identifier(expr) or "") in QUIET_SEED_WORDS:
            return False
        if isinstance(expr, ast.Attribute):
            return True
        if expr.id not in self.module_secrets:
            return False
        if scope not in self.scope_locals:
            self.scope_locals[scope] = _local_names(scope)
        return expr.id not in self.scope_locals[scope]

    def lookup(self, scope: ast.AST, name: str) -> str | None:
        """Where a name in a scope was derived from, falling back to the module's."""
        found = self.overlay.get(name)
        if found is None:
            found = self.derived.get(scope, {}).get(name)
        return found if found is not None else self.derived[self.tree].get(name)

    def callee(self, call: ast.Call) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        """The same-file function a call reaches, by name or as self./cls. method."""
        func = call.func
        if isinstance(func, ast.Name):
            return self.functions.get(func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in ("self", "cls"):
            return self.functions.get(func.attr)
        return None

    def leak(self, expr: ast.expr, scope: ast.AST) -> str | None:
        """What a value carries in clear text: the secret name it holds or came from, or None."""
        if isinstance(expr, ast.Subscript):
            if isinstance(expr.slice, ast.Slice) and _shows_little(expr.slice):
                return None
            return self.leak(expr.value, scope)
        if isinstance(expr, ast.Starred):
            return self.leak(expr.value, scope)
        if isinstance(expr, ast.Call):
            return self._call_leak(expr, scope)
        if isinstance(expr, (ast.Name, ast.Attribute)):
            return self._reference_leak(expr, scope)
        if isinstance(expr, ast.JoinedStr):
            return self._first(
                (piece.value for piece in expr.values if isinstance(piece, ast.FormattedValue)),
                scope,
            )
        if isinstance(expr, ast.BinOp):
            return self._first((expr.left, expr.right), scope)
        if isinstance(expr, (ast.Tuple, ast.List)):
            return self._first(expr.elts, scope)
        if isinstance(expr, ast.Dict) and FOLLOW_DICT_LITERALS:
            return self._first([*(key for key in expr.keys if key is not None), *expr.values], scope)
        if isinstance(expr, ast.IfExp):
            return self._first((expr.body, expr.orelse), scope)
        if isinstance(expr, COMPREHENSIONS):
            return self._comprehension_leak(expr, scope)
        return None

    def _comprehension_leak(
        self, expr: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp, scope: ast.AST
    ) -> str | None:
        """A comprehension: its element, read with each target bound to what it iterates."""
        saved = dict(self.overlay)
        try:
            for generator in expr.generators:
                origin = self.leak(generator.iter, scope)
                if origin is not None:
                    self.overlay.update((name, origin) for name in _target_names(generator.target))
            parts = [expr.key, expr.value] if isinstance(expr, ast.DictComp) else [expr.elt]
            return self._first(parts, scope)
        finally:
            self.overlay = saved

    def _first(self, exprs, scope: ast.AST) -> str | None:
        """The first leak among several expressions."""
        for expr in exprs:
            found = self.leak(expr, scope)
            if found is not None:
                return found
        return None

    def _reference_leak(self, expr: ast.Name | ast.Attribute, scope: ast.AST) -> str | None:
        """A Name or Attribute: named as a secret, or derived from one in this file."""
        name = _identifier(expr)
        if name is not None and secret_word(name) is not None:
            if self.reading_log_line or self._starts_arm_two(expr, scope):
                return _source_text(expr)
        if isinstance(expr, ast.Name):
            return self.lookup(scope, expr.id)
        if isinstance(expr.value, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
            root = expr.value
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name):
                return self.lookup(scope, root.id)
        return None

    def _call_leak(self, call: ast.Call, scope: ast.AST) -> str | None:
        """A call: a redaction, a pass-through, a same-file derived return, or a secret-named call."""
        name = _identifier(call.func)
        if name is not None and _is_redaction(name):
            return None
        if isinstance(call.func, ast.Attribute) and call.func.attr in STRING_METHODS:
            return self.leak(call.func.value, scope)
        if isinstance(call.func, ast.Attribute) and call.func.attr == "format":
            return self._first([call.func.value, *call.args, *(kw.value for kw in call.keywords)], scope)
        if isinstance(call.func, ast.Attribute) and call.func.attr == "join":
            return self._first(call.args, scope)
        if name in PASS_THROUGH_CALLS:
            return self._first([*call.args, *(kw.value for kw in call.keywords)], scope)
        if isinstance(call.func, ast.Attribute) and call.func.attr in FOLLOWED_READS:
            found = self.leak(call.func.value, scope)
            if found is not None:
                return found
        target = self.callee(call)
        if target is not None:
            found = self.returns.get(target) or self._hop(call, target, scope)
            if found is not None:
                return found
        if name is not None and secret_word(name) is not None:
            if self.reading_log_line or _call_seeds(name):
                return _source_text(call)
        return None

    def _hop(self, call: ast.Call, target: ast.FunctionDef | ast.AsyncFunctionDef, scope: ast.AST) -> str | None:
        """The same-file hop: what this call hands a parameter the callee returns."""
        passed = self.passes.get(target, set())
        return self._first((value for param, value in _handed(call, target) if param in passed), scope)


def _logger_names(tree: ast.Module) -> Set[str]:
    """``logger`` and every name a prax import binds a logger under."""
    names = set(LOGGER_NAMES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "aipass.prax" or node.module.startswith("aipass.prax."):
                names.update(alias.asname or alias.name for alias in node.names if alias.name in PRAX_LOGGER_EXPORTS)
    return names


def _scoped_nodes(body: List[ast.stmt]) -> Iterator[ast.AST]:
    """Every node of a scope's body, not descending into nested functions or classes' functions.

    The module's own top-level ``def`` statements are skipped too: each function
    is its own scope, and reading its body again as the module's made one
    function's locals every function's (a log line was reported twice).
    """
    stack: List[ast.AST] = [node for node in body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                stack.append(child)


def _target_names(target: ast.expr | None) -> List[str]:
    """Every plain name an assignment target binds.

    A subscript or attribute target binds no name: ``entry["k"] = token`` puts a
    value inside ``entry``, and the names in its index are read, not bound.
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _target_names(element)]
    return []


def _bindings(node: ast.AST) -> List[Tuple[List[str], ast.expr]]:
    """(names bound, the value bound) for an assignment, loop or with item."""
    if isinstance(node, ast.Assign):
        return [([name for target in node.targets for name in _target_names(target)], node.value)]
    if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and node.value is not None:
        return [(_target_names(node.target), node.value)]
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return [(_target_names(node.target), node.iter)]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [(_target_names(item.optional_vars), item.context_expr) for item in node.items if item.optional_vars]
    return []


def _module_secret_bindings(tree: ast.Module) -> Set[str]:
    """Secret-named names an assignment at the module's top level binds (SECRETS_BASE = ...)."""
    names: Set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            for bound, _value in _bindings(statement):
                names.update(name for name in bound if secret_word(name) is not None)
    return names


def _local_names(scope: ast.AST) -> Set[str]:
    """Names a function binds for itself, parameters included: they shadow a module binding."""
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    args = scope.args
    names = {arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    names.update(arg.arg for arg in (args.vararg, args.kwarg) if arg is not None)
    for node in _scoped_nodes(scope.body):
        for bound, _value in _bindings(node):
            names.update(bound)
    return names


def _scopes(tree: ast.Module) -> List[Tuple[ast.AST, List[ast.stmt]]]:
    """(scope node, body) for the module and every function in it."""
    scopes: List[Tuple[ast.AST, List[ast.stmt]]] = [(tree, tree.body)]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append((node, node.body))
    return scopes


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    """Positional parameter names, in order."""
    return [arg.arg for arg in [*function.args.posonlyargs, *function.args.args]]


def _derive_bindings(file: _File, node: ast.AST, scope: ast.AST) -> bool:
    """Mark the names an assignment, loop or with item binds from a secret-derived value."""
    known = file.derived.setdefault(scope, {})
    changed = False
    for names, value in _bindings(node):
        origin = file.leak(value, scope)
        if origin is None:
            continue
        for name in names:
            if name not in known:
                known[name] = origin
                changed = True
    return changed


def _derive_return(file: _File, node: ast.AST, scope: ast.AST) -> bool:
    """Mark a function whose return hands back a secret-derived value, or a parameter's."""
    if not isinstance(node, ast.Return) or node.value is None or scope in file.returns:
        return False
    origin = file.leak(node.value, scope)
    if origin is None:
        return False
    if isinstance(origin, _Handed):
        passed = file.passes.setdefault(scope, set())
        if origin.param in passed:
            return False
        passed.add(origin.param)
        return True
    file.returns[scope] = origin
    return True


def _derive_pass(file: _File, scopes: List[Tuple[ast.AST, List[ast.stmt]]]) -> bool:
    """One pass of the file-local derivation. Returns whether anything new was learned."""
    changed = False
    for scope, body in scopes:
        for node in _scoped_nodes(body):
            changed = _derive_bindings(file, node, scope) or changed
            changed = _derive_return(file, node, scope) or changed
            if isinstance(node, ast.Call):
                changed = _derive_parameters(file, node, scope) or changed
                changed = _derive_add(file, node, scope) or changed
    return changed


def _derive_add(file: _File, call: ast.Call, scope: ast.AST) -> bool:
    """Mark a collection a built value is added to: ``seen.append(key)`` binds ``seen``."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr in FOLLOWED_ADDS and isinstance(func.value, ast.Name)):
        return False
    known = file.derived.setdefault(scope, {})
    if func.value.id in known:
        return False
    added = call.args[1:] if func.attr == "insert" else call.args
    for value in added:
        origin = file.leak(value, scope)
        if origin is not None:
            known[func.value.id] = origin
            return True
    return False


def _derive_parameters(file: _File, call: ast.Call, scope: ast.AST) -> bool:
    """Mark a same-file callee's parameters that this call hands a secret-derived value."""
    target = file.callee(call)
    if target is None:
        return False
    known = file.derived.setdefault(target, {})
    changed = False
    for param, value in _handed(call, target):
        if param in known:
            continue
        origin = file.leak(value, scope)
        if origin is not None:
            known[param] = _Handed(origin, param)
            changed = True
    return changed


def _handed(call: ast.Call, target: ast.FunctionDef | ast.AsyncFunctionDef) -> List[Tuple[str, ast.expr]]:
    """(parameter, the argument a call hands it) for a same-file callee; ``*args`` hands nothing."""
    params = _parameters(target)
    if isinstance(call.func, ast.Attribute) and params and params[0] in ("self", "cls"):
        params = params[1:]
    handed = list(zip(params, call.args))
    handed += [(kw.arg, kw.value) for kw in call.keywords if kw.arg is not None]
    return [(param, value) for param, value in handed if not isinstance(value, ast.Starred)]


def _message_pieces(call: ast.Call) -> List[ast.expr]:
    """The expressions a log call writes: its positional args and message keywords."""
    return [*call.args, *(kw.value for kw in call.keywords if kw.arg not in NON_MESSAGE_KEYWORDS)]


def _is_log_call(node: ast.Call, loggers: Set[str]) -> bool:
    """A call of a prax logger level."""
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in LOG_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in loggers
    )


def _is_secret_def(name: str, verbs: frozenset) -> bool:
    """A def named on CodeQL's source words (as _call_seeds reads them) with one of ``verbs`` as a segment."""
    return _call_seeds(name) and any(part in verbs for part in segments(name))


def _required_positional(function: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    """Positional parameters without a default, ``self``/``cls`` left out."""
    params = _parameters(function)
    required = params[: len(params) - len(function.args.defaults)]
    return [param for param in required if param not in ("self", "cls")]


def _document_parameters(tree: ast.Module) -> Dict[ast.AST, Set[str]]:
    """Each secret reader's DOCUMENT parameters: the names its callers list out of the store."""
    defs = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    listers = [node for node in defs if _is_secret_def(node.name, LISTER_VERBS)]
    if not listers:
        return {}
    namespace = {param for lister in listers for param in _parameters(lister)}
    documents: Dict[ast.AST, Set[str]] = {}
    for node in defs:
        if not _is_secret_def(node.name, READER_VERBS) or _is_secret_def(node.name, LISTER_VERBS):
            continue
        rebound = {name for child in _scoped_nodes(node.body) for bound, _value in _bindings(child) for name in bound}
        names = {param for param in _required_positional(node) if param not in namespace and param not in rebound}
        if names:
            documents[node] = names
    return documents


def _message(call: ast.Call) -> ast.expr | None:
    """A log call's MESSAGE: its first positional argument, or a msg=/message= keyword."""
    if call.args:
        return None if isinstance(call.args[0], ast.Starred) else call.args[0]
    return next((kw.value for kw in call.keywords if kw.arg in MESSAGE_KEYWORDS), None)


def _named_in_message(expr: ast.expr, names: Set[str]) -> str | None:
    """The document parameter a message expression writes, or None."""
    if isinstance(expr, ast.Name):
        return expr.id if expr.id in names else None
    for piece in _message_parts(expr):
        found = _named_in_message(piece, names)
        if found is not None:
            return found
    return None


def _message_parts(expr: ast.expr) -> List[ast.expr]:
    """The sub-expressions of a message piece whose text the message carries."""
    if isinstance(expr, ast.JoinedStr):
        return [piece.value for piece in expr.values if isinstance(piece, ast.FormattedValue)]
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Mod)):
        return [expr.left, expr.right]
    if isinstance(expr, ast.Tuple):
        return list(expr.elts)
    if isinstance(expr, ast.Subscript):
        shows_little = isinstance(expr.slice, ast.Slice) and _shows_little(expr.slice)
        return [] if shows_little else [expr.value]
    if isinstance(expr, ast.Call):
        return _message_call_pieces(expr)
    return []


def _message_call_pieces(call: ast.Call) -> List[ast.expr]:
    """What a call inside the message hands on unchanged: str()/repr(), string methods, .format()."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in STRING_METHODS:
        return [func.value]
    if isinstance(func, ast.Attribute) and func.attr == "format":
        return [func.value, *call.args, *(kw.value for kw in call.keywords)]
    if isinstance(func, ast.Name) and func.id in ("str", "repr"):
        return list(call.args)
    return []


def _reader_row(call: ast.Call, scope: ast.AST, documents: Dict[ast.AST, Set[str]]) -> str | None:
    """Arm 3: what a log line inside a secret reader writes of a document parameter in its MESSAGE."""
    names = documents.get(scope)
    message = _message(call)
    if not names or message is None:
        return None
    found = _named_in_message(message, names)
    if found is None:
        return None
    return f"{found} (a document name the secret reader {getattr(scope, 'name', '?')}() is handed)"


def _shown(piece: ast.expr, origin: str) -> str:
    """What a row says is logged: the piece, and the secret name it was built from when that differs."""
    text = _source_text(piece)
    return text if origin in text else f"{text} (built from {origin})"


def scan(source: str) -> List[Tuple[int, str]]:
    """(line, what is logged) for every log call that writes a secret in clear text.

    Raises SyntaxError when the source does not parse.
    """
    tree = ast.parse(source)
    file = _File(tree)
    scopes = _scopes(tree)
    for _ in range(MAX_PASSES):
        if not _derive_pass(file, scopes):
            break
    file.reading_log_line = True
    documents = _document_parameters(tree)
    rows: List[Tuple[int, str]] = []
    for scope, body in scopes:
        calls = [node for node in _scoped_nodes(body) if isinstance(node, ast.Call)]
        for call in calls:
            if not _is_log_call(call, file.loggers):
                continue
            handed = _reader_row(call, scope, documents)
            if handed is not None:
                rows.append((call.lineno, handed))
                continue
            for piece in _message_pieces(call):
                origin = file.leak(piece, scope)
                if origin is not None:
                    rows.append((call.lineno, _shown(piece, origin)))
                    break
    return sorted(set(rows))


_read = partial(read_text, tag="clear_text_secret_logging", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Clear-text secret logging", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for a log call that writes a secret, or a value built from one, in clear text."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)
    try:
        rows = scan(source)
    except SyntaxError as exc:
        logger.info("[clear_text_secret_logging] Unparseable %s: %s", module_path, exc)
        return _result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100)

    hits = [(line, what) for line, what in rows if not is_bypassed(module_path, STANDARD_KEY, line, bypass_rules)]
    if not hits:
        return _result(True, _one_check(True, "No log call writes a secret-named value in clear text"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per hit would hide the rest.
    detail = "\n".join(f"{path.name}:{line} logs {what} in clear text - {CURE}" for line, what in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
