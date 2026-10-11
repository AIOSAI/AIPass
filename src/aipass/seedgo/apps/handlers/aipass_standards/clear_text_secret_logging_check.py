# =================== AIPass ====================
# Name: clear_text_secret_logging_check.py
# Description: Clear Text Secret Logging Standards Checker Handler
# Version: 1.2.0
# Created: 2026-10-10
# Modified: 2026-10-11
# =============================================

"""
Clear Text Secret Logging Standards Checker Handler

WHERE IT CAME FROM. PR #774 round seven, head 38166f35: GitHub's CodeQL
check went red while every workflow job was green. Its one HIGH row,
py/clear-text-logging-sensitive-data, sits on prax ``apps/modules/logger.py:135``,
``SystemLogger.warning``: the fleet's one log sink, so CodeQL reports the SINK
and lists the two SOURCES it traced into it, both classified "secret". Read
against CodeQL's own source model (a ``foo.<name>`` attribute read whose name
says secret is a source), both are ``secrets_store.SECRETS_BASE`` reads in @api
``apps/handlers/host/tokens.py`` -- ``store_path()`` :182 and ``lock_path()``
:267 -- reaching three warning calls: the temp-store cleanup :324, the stale
lock :370 and ``_drop_lock`` :438. A path inside the secrets directory, not
the secret; the scanner read the name.

THIS RULE CONVICTS THE CALLER LINE, never the sink: a prax logger call
(``logger.debug/info/warning/error/critical/exception``, the receiver named
``logger`` or bound by an import from ``aipass.prax``) is a row when a piece of
its message -- a positional argument, an f-string piece, a ``%`` operand, a
``.format()`` argument or a ``+`` operand -- is:

  1. NAMED AS A SECRET. A Name, Attribute or Call whose identifier holds a
     secret word as a whole segment (``SECRET_WORDS``; ``api_key`` and its
     kin as consecutive segments, camelCase split). ``credentials[0]`` reads
     the collection; ``str()``, ``repr()``, ``Path()`` and the string methods
     (``.strip()`` ...) are looked through.
  2. BUILT IN THIS FILE FROM A SECRET-NAMED SOURCE. The derivation STARTS
     only from a secret-named module-level binding (``SECRETS_BASE = ...`` at
     the file's top level, read where no local shadows it), a secret-named
     attribute read (``secrets_store.SECRETS_BASE``, ``self.api_key``) -- a
     token word seeds neither (``QUIET_SEED_WORDS``) -- or, since 1.1.0
     (dispatch 39bfe173, CodeQL round nine), the RESULT of a call named by
     CodeQL's source words (``_get_secret(bot_id)``, ``load_trusted_keys()``;
     ``_call_seeds``: secret(s), trusted, confidential, none of CodeQL's
     exclusion words, no setter verb). It never starts from a parameter, a
     loop or ``with`` target or a function-local name. From a source it
     FOLLOWS: assignments (and loops or ``with`` items over a built value),
     comprehensions over a built value (their element read with the target
     bound to it), the wrappers sorted/list/tuple/set/dict/str/repr/join/
     format/f-strings, a same-file function whose ``return`` hands a built
     value back, a same-file parameter handed one, THE SAME-FILE HOP (a call
     whose argument is built, to a function that returns that parameter: the
     only place a parameter is followed, and per call -- a clean argument
     through the same helper stays clean), an attribute of a built name
     (``target.parent``), and since 1.2.0 (dispatch fad65d17, CodeQL round
     ten) the READS of a built value -- ``.get(k)``, ``.pop(k)``,
     ``.setdefault(k, d)``, ``.items()``, ``.keys()``, ``.values()``
     (``FOLLOWED_READS``; the receiver carries, a default does not) beside the
     subscripts and loops already followed -- and the ADDS of one:
     ``seen.append(key)``, ``.extend``, ``.add``, ``.insert(i, x)`` on ``x``
     bind the named collection (``FOLLOWED_ADDS``), and a dict literal
     holding a built key or value is built. A ``non_``/``not_`` prefix acquits nothing. This arm
     is what reaches the CodeQL rows: no name on those log lines says secret,
     the source they were built from does.

WHY ARM 2 STARTS SO NARROWLY. A parameter or loop variable called ``token``
is a shell word or a counter as often as a credential (drone's
``_resolve_mail_token(token)`` hands its argument back as ``command``); its
name is judged by arm 1 wherever it reaches a log line, and spreading from it
convicted lines that say nothing secret. A module-level binding and an
attribute are where a file names its secret stores; those are CodeQL's
sources too (SensitiveVariableAssignment, SensitiveAttributeAccess).

CHECK FIRST (2026-10-10, 1,301 product files in src/aipass/*/apps and lib):
16 rows in 8 files -- api 7 (arm 2: the six CodeQL-reachable warnings plus a
debug on the same lock path), drone 1, hooks 7, skills lib 1 (all arm 1).
Narrowings while measuring, each for a stated reason: 17 rows spread from
secret-named calls, 6 from a subscript target whose index was read as a
binding, and 9 from parameter, loop and local sources (the ruling above).

ROUND NINE (1.1.0, 2026-10-10, 1,302 files, the fleet at 0 rows before): CodeQL
traced @skills telegram ``config.py`` load_bot_config -- ``secret =
_get_secret(bot_id)``, ``strays = non_secret_keys(secret)`` (a sorted generator
over the document), ``strays`` on a warning -- which 1.0.0 missed. After the
widening: 0 rows on the live fleet (@skills had cured the line); the pre-cure
config.py convicts at its warning. Measured, each narrowing kept for its row:
call seeds from every secret word 10 (token_hex x4, issue_token,
context_fill_tokens x2, _get_turn_token x2, _without_credentials); adding
credential(s) to the call words 1 (_without_credentials); no setter-verb
exclusion 1 (@api host/config.py:150 from set_secret); token-word binding and
attribute seeds 1 (@prax monitor.py:274, argparse's ``args.tokens``). Arm 1's
new words trusted and confidential: 0 new rows.

ROUND TEN (1.2.0, 2026-10-11, 1,383 files): CodeQL's alert kept two sources
after rounds eight and nine; the chain it most plausibly reports is @api
host/tokens.py load_tokens -- ``stored = secrets_store.get_secret(...)``,
``records = stored.get("tokens")`` (lost here before 1.2.0), the
comprehension, touch_token's loop and ``_is_due(record.get("last_used"))`` --
to the ``last_used %r`` warning (:655). The pre-cure file (HEAD 6c3aa9aa)
convicts at :655 and only there (:631's token_id crosses from server.py);
@api's cure acquits. Live fleet 0 rows before and after; every sub-arm
(each read, each add, the dict literal) measured alone: 0 rows.

NOT A ROW, each for its reason:
  * An IDENTIFIER of a secret rather than the secret: a segment beside the
    word says what it is (``IDENTIFIER_SEGMENTS``: token_id, token_count,
    token_store, secret_path, secret_name, n_tokens -- the dispatch's own
    list and their plain kin).
  * A REDACTION: a call whose name holds redact, mask or scrub, ``len()``, or
    a slice that shows at most ``MAX_SHOWN`` characters (``[-4:]``). A wider
    slice (``token[:10]``) still shows the secret and stays a row.
  * The secret word inside a string constant: the message names a field, it
    does not carry one.
  * Any other receiver, ``print`` included: ``output_routing`` owns those.
  * Flow through another file's function: the derived arm is file-local, so a
    value that crosses a module boundary is judged again by its name there.

WHY NAMES RULE. A scanner and a stranger both read the name. A name that says
secret on a log line is a leak in the reader's eyes even when the value is
benign, so the cure for a false hit is the RENAME, and the rename is a cure,
not a dodge. A real secret is cured by the redaction above, or by leaving the
value out of the line.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

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

#: The secret words whose CALL result seeds arm 2: CodeQL's own source words
#: (secret|trusted|confidential; ``untrusted`` is its own segment, so never
#: matches). token and password calls stay arm 1 only: token_hex, issue_token.
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

#: Words that never SEED arm 2 from a binding or an attribute (arm 1 still reads
#: them on the log line): measured, a token is a parser word in this fleet --
#: argparse's ``args.tokens`` in prax monitor.py reached a log line as ``args``.
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

#: Reads whose result is (part of) the value they are called on (1.2.0, dispatch
#: fad65d17): ``stored.get("tokens")``, ``built.items()``. Only the receiver
#: carries: a ``.get(k, default)`` default is not followed.
FOLLOWED_READS = frozenset({"get", "pop", "setdefault", "items", "keys", "values"})

#: Adds that put a value into the collection they are called on (1.2.0):
#: ``seen.append(key)`` binds ``seen``. ``insert(i, x)`` is judged on ``x`` only.
FOLLOWED_ADDS = frozenset({"append", "extend", "add", "insert"})

#: Whether a dict literal holding a built key or value is built (1.2.0).
FOLLOW_DICT_LITERALS = True

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


# =============================================
# NAMES
# =============================================


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
    """Whether a call so named returns a secret, by CodeQL's source model.

    Its secret word is one of CALL_SOURCE_WORDS, kept by secret_word() (so
    secret_path() and redact_secret() acquit), no SOURCE_EXCLUSIONS word is in
    it anywhere (hash_secret, get_user_secret) and no SETTER_VERBS segment says
    it stores rather than returns (set_secret, delete_secret).
    """
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


# =============================================
# THE FILE'S SCOPES
# =============================================


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
        # Arm 2 STARTS only from a secret-named module-level binding
        # (SECRETS_BASE = ...), a secret-named attribute read
        # (secrets_store.SECRETS_BASE, self.api_key) or the result of a call
        # _call_seeds() names a source (_get_secret(bot_id); dispatch 39bfe173).
        # Never from a parameter, a loop or with target or a function-local
        # name: those convicted drone's `command` through
        # _resolve_mail_token(token) and memory's `message` on lines whose own
        # names say nothing (coordinator ruling 2026-10-10). Every secret-named
        # Name, Attribute or Call ON the log line is still arm 1. scan() sets
        # this to read.
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
        """A comprehension: its element, read with each target bound to what it iterates.

        ``sorted(key for key in document)`` carries the document's keys; a filter
        (``if key not in SECRET_FIELDS``) acquits nothing; ``len(key)`` as the
        element is a redaction like anywhere else.
        """
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
    """Mark a collection a built value is added to: ``seen.append(key)`` binds ``seen``.

    The receiver must be a plain name (``self.items.append(x)`` binds no name,
    like a subscript target); ``insert(i, x)`` is judged on ``x``, never ``i``.
    """
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
    rows: List[Tuple[int, str]] = []
    for scope, body in scopes:
        calls = [node for node in _scoped_nodes(body) if isinstance(node, ast.Call)]
        for call in calls:
            if not _is_log_call(call, file.loggers):
                continue
            for piece in _message_pieces(call):
                origin = file.leak(piece, scope)
                if origin is not None:
                    rows.append((call.lineno, _shown(piece, origin)))
                    break
    return sorted(set(rows))


# =============================================
# CHECK
# =============================================


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[clear_text_secret_logging] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Clear-text secret logging", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for a log call that writes a secret, or a value built from one, in clear text.

    Args:
        module_path: Path to the file to check.
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
