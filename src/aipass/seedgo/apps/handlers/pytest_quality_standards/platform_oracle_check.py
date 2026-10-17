# =================== AIPass ====================
# Name: platform_oracle_check.py
# Description: v5 - is this test's verdict a fact about the code or about the host
# Version: 1.1.0
# Created: 2026-09-08
# Modified: 2026-10-17
# =============================================

"""Is this test's pass or fail a fact about the code, or a fact about the host?

Reference: platform_oracle.md"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "platform_oracle"

#: Tried in order; a project matching none of them gets a whole-tree walk.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Everything else is reported and excluded from the score.
SCORING_SPECIES: tuple = ("LISTING_ORDER", "MODE_INJECTOR")

LISTING_CALLS: frozenset = frozenset({"iterdir", "listdir", "glob", "rglob", "scandir", "walk"})

#: `ast.walk` is in every checker in this pack and lists no directory.
NOT_LISTING_ROOTS: frozenset = frozenset({"ast", "os.path", "json", "re"})

UNORDERED_WRAPPERS: frozenset = frozenset({"set", "frozenset", "Counter"})

#: A sort over strings is byte order on every host; only `sorted()` over Path objects is platform-ordered.
STRING_VALUED_ATTRIBUTES: frozenset = frozenset({"name", "stem", "suffix"})

STRING_VALUED_CALLS: frozenset = frozenset({"str", "as_posix", "lower", "upper", "casefold", "strip", "format"})

#: `os.listdir` already answers with names, so its sort is a string sort.
STRING_LISTING_CALLS: frozenset = frozenset({"listdir"})

PATH_CONSTRUCTORS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

PATH_METHODS: frozenset = frozenset({"joinpath", "with_name", "with_suffix", "expanduser", "resolve", "absolute"})

#: `.name` and `.stem` are absent on purpose: they answer with a string.
PATH_ATTRIBUTES: frozenset = frozenset({"parent"})

SANDBOX_FIXTURES: frozenset = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

#: Same hazard as `tmp_path`: the Windows runner's TEMP is an 8.3 short name.
TEMPDIR_MAKERS: frozenset = frozenset(
    {
        "tempfile.TemporaryDirectory",
        "tempfile.mkdtemp",
        "tempfile.gettempdir",
        "tempfile.NamedTemporaryFile",
        "tempfile.TemporaryFile",
        "TemporaryDirectory",
        "mkdtemp",
        "gettempdir",
    }
)

#: Either side of a comparison carrying one of these has already taken the cure.
RESOLVING_CALLS: frozenset = frozenset({"resolve", "absolute", "realpath", "samefile", "readlink", "canonicalize"})

#: `/dev/null` EXACTLY is absent on purpose: as a sink it is correct; null as a DIRECTORY is the ENOTDIR.
DEVICE_PATH_PREFIXES: tuple = ("/dev/null/", "/dev/full", "/dev/zero/", "/proc/", "/sys/")

#: A mode literal without the owner write bit is read-only.
OWNER_WRITE_BIT: int = 0o200

#: A patch on one of these is the cure, so it acquits unconditionally.
WRITE_SEAMS: frozenset = frozenset(
    {
        "open",
        "write_text",
        "write_bytes",
        "write",
        "writelines",
        "replace",
        "rename",
        "mkdir",
        "touch",
        "unlink",
        "copy",
        "copy2",
        "copyfile",
        "move",
        "dump",
        "flush",
    }
)

OSERROR_TYPES: frozenset = frozenset(
    {
        "OSError",
        "IOError",
        "EnvironmentError",
        "PermissionError",
        "FileNotFoundError",
        "NotADirectoryError",
        "IsADirectoryError",
        "FileExistsError",
    }
)

#: A mock's warning counter is how a unit proves a failure production reports rather than raises.
FAILURE_WITNESSES: frozenset = frozenset(
    {
        "warning",
        "error",
        "critical",
        "exception",
        "call_count",
        "called",
        "call_args",
        "call_args_list",
    }
)

#: Filled by the operating system, not by the code under test.
OSERROR_ATTRIBUTES: frozenset = frozenset({"filename", "filename2", "strerror", "errno", "winerror"})

#: Per attribute, because "it differs" is not actionable and the cure differs for each.
OSERROR_ATTRIBUTE_HAZARD: Dict[str, str] = {
    "filename": (
        "a Windows subprocess launch raises FileNotFoundError with filename=None ([WinError 2]) while POSIX fills it in"
    ),
    "filename2": "the second filename is filled by POSIX rename/link failures and is None under Windows",
    "strerror": "the message text comes from the platform C library and is not the same string on both",
    "errno": "Windows translates its own error codes into errno, and the translation is not one to one",
    "winerror": "winerror does not exist on a POSIX OSError at all - reading it raises AttributeError",
}

#: Sealing `cwd` does not seal what is ABOVE it, which is the whole SHALLOW_SANDBOX species.
CWD_SEAM_NEEDLES: tuple = ("Path.cwd", "os.getcwd", "getcwdb", "pathlib.Path.cwd")

SANDBOX_MARKER_CALLS: frozenset = frozenset({"mkdir", "touch", "write_text", "write_bytes", "symlink_to", "makedirs"})

RENDERED_PATH_PARTS: frozenset = frozenset({"name", "stem", "parts", "parent"})

#: The full list lives in the report artifact.
MAX_REPORTED: int = 12


def _assign_bindings(node: ast.AST) -> List[Tuple[ast.expr, Optional[ast.expr]]]:
    """The (target, value) pairs one assignment statement binds."""
    if isinstance(node, ast.Assign):
        return [(target, node.value) for target in node.targets]
    if isinstance(node, ast.AnnAssign):
        return [(node.target, node.value)]
    return []


def _context_bindings(node: ast.AST) -> List[Tuple[ast.expr, Optional[ast.expr]]]:
    """The (target, value) pairs one `with` or `for` header binds."""
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [(i.optional_vars, i.context_expr) for i in node.items if i.optional_vars is not None]
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [(node.target, node.iter)]
    return []


def _bindings(unit_node: ast.AST) -> Iterator[Tuple[ast.expr, Optional[ast.expr]]]:
    """Every (target, value) pair a unit binds a name through.

    `with ... as td` counts beside plain assignment: the UNRESOLVED_TMP_PATH row is spelled that way.
    Two helpers, not an elif chain: an elif ladder reads as four nesting levels to deep_nesting."""
    for node in ast.walk(unit_node):
        yield from _assign_bindings(node)
        yield from _context_bindings(node)


def _names_under(node: ast.AST) -> Set[str]:
    """Every dotted call target and bare name under a node."""
    found: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Call):
            dotted = corpus.dotted_name(child.func)
            if dotted:
                found.add(dotted)
    return found


def _tail(dotted: str) -> str:
    """The last segment of a dotted spelling."""
    return dotted.rsplit(".", 1)[-1]


def _grow(unit_node: ast.AST, accept) -> Set[str]:
    """Names a unit binds from an expression `accept` recognises, to a fixed point.

    ONE MECHANISM, THREE ARMS, so they cannot disagree about what "derived from" means; it never leaves the unit."""
    bound: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for target, value in _bindings(unit_node):
            if not isinstance(target, ast.Name) or target.id in bound or value is None:
                continue
            if accept(value, bound):
                bound.add(target.id)
                changed = True
    return bound


def _is_sandbox_path(node: ast.expr, bound: Set[str]) -> bool:
    """True when an expression is a PATH rooted in a temporary directory.

    A path, not a string read off one: `tmp_path.name` is not accepted."""
    if isinstance(node, ast.Name):
        return node.id in bound
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_sandbox_path(node.left, bound)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_ATTRIBUTES and _is_sandbox_path(node.value, bound)
    if isinstance(node, ast.Call):
        return _is_sandbox_call(node, bound)
    return False


def _is_sandbox_call(node: ast.Call, bound: Set[str]) -> bool:
    """True when a call mints, or carries forward, a temporary directory."""
    dotted = corpus.dotted_name(node.func)
    if dotted in TEMPDIR_MAKERS:
        return True
    if isinstance(node.func, ast.Name) and node.func.id in PATH_CONSTRUCTORS:
        return any(_is_sandbox_path(argument, bound) for argument in node.args)
    if _tail(dotted) == "str" and node.args:
        return _is_sandbox_path(node.args[0], bound)
    if isinstance(node.func, ast.Attribute) and node.func.attr in PATH_METHODS:
        return _is_sandbox_path(node.func.value, bound)
    return False


def sandbox_names(unit_node: ast.AST) -> Set[str]:
    """Every name in a unit that holds a path under a temporary directory.

    Seeded with the pytest fixture names themselves."""
    seeds = set(SANDBOX_FIXTURES)
    return seeds | _grow(unit_node, lambda value, bound: _is_sandbox_path(value, seeds | bound))


def _argument_text(argument: ast.expr) -> Set[str]:
    """The seam names one patch argument names, as text.

    An f-string is read piece by piece: either half may be the one an acquittal needs."""
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return {argument.value}
    if isinstance(argument, ast.JoinedStr):
        found: Set[str] = set()
        for value in argument.values:
            found |= _argument_text(value)
        return found
    if isinstance(argument, ast.FormattedValue):
        return _argument_text(argument.value)
    name = corpus.dotted_name(argument) if isinstance(argument, (ast.Name, ast.Attribute)) else ""
    return {name} if name else set()


def _is_patching_call(dotted: str) -> bool:
    """True when a dotted call spelling replaces a seam for the test's duration.

    A local alias counts (`patch as _patch`); `endswith("_patch")` catches it without catching `dispatch`."""
    tail = _tail(dotted)
    if tail in {"setattr", "delattr"}:
        return dotted.startswith("monkeypatch.")
    return tail in {"patch", "object", "dict"} or tail.endswith("_patch")


def module_level_strings(tree: ast.Module) -> Dict[str, str]:
    """Module-level names bound to a plain string literal.

    The other half of the one hop: `patch(LOGGER_PATCH)` is judged by the constant's value, not its name."""
    strings: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        targets: Sequence[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                strings[target.id] = node.value.value
    return strings


def patch_calls(unit_node: ast.AST) -> List[ast.Call]:
    """Every seam-replacing call in a unit, in source order."""
    return [
        node
        for node in ast.walk(unit_node)
        if isinstance(node, ast.Call) and _is_patching_call(corpus.dotted_name(node.func))
    ]


def patched_targets(unit_node: ast.AST, module_strings: Optional[Dict[str, str]] = None) -> Set[str]:
    """Every seam this unit replaces, as text an acquittal can be matched against.

    TEXT, not resolved objects: resolving would import the branch under audit.
    `module_strings` defaults to none: a caller with no tree gets the literal-only reading."""
    known = module_strings or {}
    targets: Set[str] = set()
    for node in patch_calls(unit_node):
        for argument in node.args:
            for text in _argument_text(argument):
                targets.add(text)
                if text in known:
                    targets.add(known[text])
    return targets


def _listing_call(node: ast.AST) -> str:
    """The directory-listing call under a node, by dotted spelling, or ""."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        dotted = corpus.dotted_name(child.func)
        if _tail(dotted) not in LISTING_CALLS:
            continue
        root = dotted.rsplit(".", 1)[0] if "." in dotted else ""
        if root in NOT_LISTING_ROOTS:
            continue
        return dotted or _tail(dotted)
    return ""


def _inherited_listing(value: ast.expr, named: Dict[str, str]) -> str:
    """The listing spelling a value inherits from a name it reads, or ""."""
    for name in sorted(_names_under(value) & set(named)):
        return named[name]
    return ""


def _listing_names(unit_node: ast.AST) -> Dict[str, str]:
    """Names bound, one hop, to something a directory listing produced.

    A dict, not a set: the finding prints the listing's own spelling, never a loop variable's name."""
    named: Dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for target, value in _bindings(unit_node):
            if not isinstance(target, ast.Name) or target.id in named or value is None:
                continue
            source = _listing_call(value) or _inherited_listing(value, named)
            if source:
                named[target.id] = source
                changed = True
    return named


def _listing_source(node: ast.expr, listing: Dict[str, str]) -> str:
    """How this side of a comparison got its contents from the filesystem, or ""."""
    return _listing_call(node) or _inherited_listing(node, listing)


def _list_literal_side(left: ast.expr, right: ast.expr) -> Tuple[Optional[ast.List], ast.expr]:
    """The list-literal half of a comparison and the other half, or (None, left)."""
    if isinstance(left, ast.List):
        return left, right
    if isinstance(right, ast.List):
        return right, left
    return None, left


def _sorted_calls(node: ast.AST) -> List[ast.Call]:
    """Every `sorted(...)` textually inside a node."""
    return [c for c in ast.walk(node) if isinstance(c, ast.Call) and _tail(corpus.dotted_name(c.func)) == "sorted"]


def _is_string_valued(node: ast.expr) -> bool:
    """True when an expression answers with a string rather than with a Path."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.Attribute):
        return node.attr in STRING_VALUED_ATTRIBUTES
    if isinstance(node, ast.Call):
        tail = _tail(corpus.dotted_name(node.func))
        return tail in STRING_VALUED_CALLS or tail in STRING_LISTING_CALLS
    return False


def _sort_is_neutral(call: ast.Call) -> str:
    """Why one `sorted(...)` does not carry a platform order, or "".

    Any key displaces `PurePath.__lt__`, and a sort over strings never touches it;
    either way the order is the same on every host."""
    if any(kw.arg == "key" for kw in call.keywords):
        return "sorted() supplies an explicit key, so Path's own comparison is not what orders it"
    if not call.args:
        return ""
    subject = call.args[0]
    if isinstance(subject, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        if _is_string_valued(subject.elt):
            return "sorted() is applied to strings, not Paths, so the order is byte order on every host"
        return ""
    if _is_string_valued(subject):
        return "sorted() is applied to strings, not Paths, so the order is byte order on every host"
    return ""


def _neutral_sort_names(unit_node: ast.AST) -> Set[str]:
    """Names bound from a sort that carries no platform order."""

    def accept(value: ast.expr, _bound: Set[str]) -> bool:
        """True when a bound value came from a neutral sort."""
        return any(_sort_is_neutral(call) for call in _sorted_calls(value))

    return _grow(unit_node, accept)


def _order_is_neutralised(node: ast.Compare, other: ast.expr, neutral: Set[str]) -> str:
    """Why this comparison does not depend on order, or "" when it does.

    The hop counts for a neutral sort, not for the both-sides rule: a `sorted()` on the literal side
    alone leaves the listing in Path order, so both-sides is read textually."""
    left, right = node.left, node.comparators[0]
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and _tail(corpus.dotted_name(call.func)) in UNORDERED_WRAPPERS:
            return f"the comparison is wrapped in {_tail(corpus.dotted_name(call.func))}(), which has no order"
    for call in _sorted_calls(node):
        reason = _sort_is_neutral(call)
        if reason:
            return reason
    if _names_under(other) & neutral:
        return "the listed side was sorted without Path comparison one hop away"
    if _sorted_calls(left) and _sorted_calls(right):
        return "both sides are sorted by the same rule"
    return ""


def listing_order_rows(unit: corpus.TestUnit) -> List[Dict]:
    """Findings for an ordered equality against a directory listing."""
    listing = _listing_names(unit.node)
    neutral = _neutral_sort_names(unit.node)
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
            continue
        literal, other = _list_literal_side(node.left, node.comparators[0])
        if literal is None or len(literal.elts) < 2:
            continue
        source = _listing_source(other, listing)
        if not source or _order_is_neutralised(node, other, neutral):
            continue
        rows.append(
            _finding(
                "LISTING_ORDER",
                unit,
                node.lineno,
                f"an ordered equality against a {len(literal.elts)}-element list literal, where the other "
                f"side came from {source} - sorted() over Paths is case-SENSITIVE on POSIX and CASE-FOLDED "
                f"under ntpath, so a sorted listing is still platform-ordered. Compare the set, or sort the "
                f"names as strings",
            )
        )
    return rows


def _mode_spellings(node: ast.expr) -> Set[str]:
    """Every `S_I*` name in a mode expression, dotted or bare.

    Its own reader: `_names_under` reads `stat.S_IREAD` as the single name "stat", so the dotted form escaped."""
    found: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return {name for name in found if name.startswith("S_I")}


def _readonly_mode(node: ast.expr) -> str:
    """How this mode expression removes the write bit, or "".

    A bare int is read against the owner write bit, a `stat.S_I*` expression by its names (any W keeps it writable).
    `isinstance(True, int)` holds, so booleans are refused rather than read as mode 1."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            return ""
        return "" if node.value & OWNER_WRITE_BIT else oct(node.value)
    spellings = _mode_spellings(node)
    if not spellings:
        return ""
    if any("W" in name for name in spellings):
        return ""
    return " | ".join(sorted(spellings))


def _chmod_injector(node: ast.Call) -> str:
    """How a chmod call makes a path unwritable, or "".

    The mode is the LAST positional argument in both `os.chmod(p, m)` and `p.chmod(m)`."""
    if _tail(corpus.dotted_name(node.func)) != "chmod" or not node.args:
        return ""
    mode = _readonly_mode(node.args[-1])
    return f"chmod to {mode}" if mode else ""


def _device_literal(node: ast.AST) -> str:
    """The POSIX-only device path this node writes down, or ""."""
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return ""
    text = node.value
    return text if text.startswith(DEVICE_PATH_PREFIXES) else ""


def _injectors_in(unit_node: ast.AST) -> List[Tuple[int, str]]:
    """Every filesystem-mood failure injector in a unit, as (line, description)."""
    found: List[Tuple[int, str]] = []
    for node in ast.walk(unit_node):
        if isinstance(node, ast.Call):
            described = _chmod_injector(node)
            if described:
                found.append((node.lineno, described))
        device = _device_literal(node)
        if device:
            found.append((getattr(node, "lineno", -1), f"the POSIX-only device path {device!r}"))
    return found


def _asserts_on_failure(unit: corpus.TestUnit) -> bool:
    """True when the unit's oracle is about a failure rather than about a value.

    `pytest.raises(OSError)`, or a mock logger's `warning.call_count` when production reports instead of raising."""
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and _tail(corpus.dotted_name(node.func)) in {"raises", "warns"}:
            if _names_under(node) & OSERROR_TYPES:
                return True
    for statement in corpus.asserts_in(unit):
        for child in ast.walk(statement):
            if isinstance(child, ast.Attribute) and child.attr in FAILURE_WITNESSES:
                return True
    return False


def _seam_injects_the_failure(unit_node: ast.AST, module_strings: Dict[str, str]) -> str:
    """The patched write seam that makes this unit's failure portable, or "".

    NOT NEGOTIABLE: the seam is the cure this arm teaches, so it can never be what the arm flags."""
    for text in patched_targets(unit_node, module_strings):
        if _tail(text) in WRITE_SEAMS:
            return text
    for node in patch_calls(unit_node):
        for keyword in node.keywords:
            if keyword.arg == "side_effect" and _names_under(keyword.value) & OSERROR_TYPES:
                return "side_effect on a patched seam"
    return ""


#: The test's own call of the kind a mode bit refuses, made to ask the platform.
PROBE_CALLS: frozenset = frozenset({"unlink", "write_text", "write_bytes", "mkdir", "open"})


def _is_probe_try(node: ast.AST) -> bool:
    """True for a ``try`` whose body makes a PROBE_CALLS call."""
    if not isinstance(node, ast.Try):
        return False
    calls = [child for statement in node.body for child in ast.walk(statement) if isinstance(child, ast.Call)]
    return any(_tail(corpus.dotted_name(call.func)) in PROBE_CALLS for call in calls)


def probe_helpers(tree: ast.Module) -> Set[str]:
    """Module-level functions whose body holds a probe ``try``: the platform asked one call away."""
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(map(_is_probe_try, ast.walk(node)))
    }


def _assigned_names(statements: List[ast.stmt]) -> Set[str]:
    """Every bare name assigned anywhere in these statements."""
    return {
        target.id
        for statement in statements
        for node in ast.walk(statement)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _probe_answers(unit_node: ast.AST, helpers: Set[str]) -> Set[str]:
    """Names that hold what the platform answered to the test's own probe call."""
    answers: Set[str] = set()
    for node in ast.walk(unit_node):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if corpus.dotted_name(node.value.func) in helpers:
                answers |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        if isinstance(node, ast.Try) and _is_probe_try(node):
            answers |= _assigned_names(node.body + [s for handler in node.handlers for s in handler.body])
    return answers


def _asks_the_platform(unit_node: ast.AST, after_line: int, helpers: Set[str]) -> bool:
    """True when, after the injector, the unit branches on its own probe's answer.

    Not read: whether the probe's path stands under the chmod's directory; no dataflow is followed."""
    answers = _probe_answers(unit_node, helpers)
    return any(
        isinstance(node, ast.If) and node.lineno > after_line and bool(_names_under(node.test) & answers)
        for node in ast.walk(unit_node)
    )


def mode_injector_rows(
    unit: corpus.TestUnit, module_strings: Optional[Dict[str, str]] = None, helpers: Optional[Set[str]] = None
) -> List[Dict]:
    """Findings for a failure injected by the filesystem's mood, not at a seam.

    ``helpers`` are the module's ``probe_helpers``; a unit that asks the platform and branches on the answer is no row."""
    injectors = _injectors_in(unit.node)
    if not injectors or not _asserts_on_failure(unit):
        return []
    if _seam_injects_the_failure(unit.node, module_strings or {}):
        return []
    line, described = injectors[0]
    if _asks_the_platform(unit.node, line, helpers or set()):
        return []
    return [
        _finding(
            "MODE_INJECTOR",
            unit,
            line if line > 0 else unit.line,
            f"the failure this unit asserts on is injected by {described} rather than at a patched seam - "
            f"Windows ignores POSIX mode bits for the owner and has no /dev/null directory semantics, so "
            f"the write SUCCEEDS there, nothing raises, and the must-fail assertion reads zero. Patch the "
            f"write seam with an OSError side_effect instead",
        )
    ]


def _raises_capture_name(node: ast.AST) -> str:
    """The name a `with pytest.raises(...) as name` binds, or ""."""
    if not isinstance(node, (ast.With, ast.AsyncWith)):
        return ""
    for item in node.items:
        call = item.context_expr
        if not isinstance(call, ast.Call) or _tail(corpus.dotted_name(call.func)) not in {"raises", "warns"}:
            continue
        if isinstance(item.optional_vars, ast.Name):
            return item.optional_vars.id
    return ""


def _captured_exception_names(unit_node: ast.AST) -> Set[str]:
    """Names holding an exception the unit caught, plus one hop off them.

    The hop reaches `cause = exc_info.value.__cause__`, the name the assertion is written against."""
    seeds: Set[str] = set()
    for node in ast.walk(unit_node):
        if isinstance(node, ast.ExceptHandler) and node.name:
            seeds.add(node.name)
        captured = _raises_capture_name(node)
        if captured:
            seeds.add(captured)
    if not seeds:
        return seeds
    return seeds | _grow(unit_node, lambda value, bound: bool(_names_under(value) & (seeds | bound)))


def _root_name(node: ast.AST) -> str:
    """The leftmost bare name of an attribute, subscript or call chain, or ""."""
    current: ast.AST = node
    while not isinstance(current, ast.Name):
        if isinstance(current, (ast.Attribute, ast.Subscript)):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        else:
            return ""
    return current.id


def _unit_manufactures_the_error(unit_node: ast.AST) -> str:
    """The OS-error the unit builds ITSELF, or "".

    ONLY OS-FILLED WHEN THE OS FILLED IT: a `raise OSError(errno.EXDEV, ...)` or `side_effect=OSError(...)`
    the unit wrote puts its own literal in `.errno`, the same on every platform."""
    for node in ast.walk(unit_node):
        if isinstance(node, ast.Raise) and node.exc is not None and _names_under(node.exc) & OSERROR_TYPES:
            return ast.unparse(node.exc)
    for node in patch_calls(unit_node):
        for keyword in node.keywords:
            if keyword.arg == "side_effect" and _names_under(keyword.value) & OSERROR_TYPES:
                return ast.unparse(keyword.value)
    return ""


def oserror_attribute_rows(unit: corpus.TestUnit) -> List[Dict]:
    """Nominations for an assertion on an OS-filled exception attribute."""
    captured = _captured_exception_names(unit.node)
    if not captured or _unit_manufactures_the_error(unit.node):
        return []
    rows: List[Dict] = []
    seen: Set[str] = set()
    for statement in corpus.asserts_in(unit):
        for child in ast.walk(statement):
            if not isinstance(child, ast.Attribute) or child.attr not in OSERROR_ATTRIBUTES:
                continue
            if _root_name(child.value) not in captured or child.attr in seen:
                continue
            seen.add(child.attr)
            rows.append(
                _finding(
                    "OSERROR_ATTRIBUTE",
                    unit,
                    statement.lineno,
                    f"asserts on .{child.attr} of a caught exception - {OSERROR_ATTRIBUTE_HAZARD[child.attr]}. "
                    f"Assert the TYPE and the chain, and if the name matters assert it in our own wrapper's "
                    f"message, which we fill on every platform",
                )
            )
    return rows


def _carries_a_resolver(node: ast.AST) -> bool:
    """True when any call under a node normalises a path against the filesystem."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _tail(corpus.dotted_name(child.func)) in RESOLVING_CALLS:
            return True
    return False


def _sandbox_is_resolved_once(unit_node: ast.AST, sandbox: Set[str]) -> bool:
    """True when the unit rebinds a sandbox name through a resolver.

    `tmp_path = tmp_path.resolve()` up front cures every later comparison without saying so on its line."""
    for target, value in _bindings(unit_node):
        if isinstance(target, ast.Name) and target.id in sandbox and value is not None:
            if _carries_a_resolver(value):
                return True
    return False


def unresolved_tmp_path_rows(unit: corpus.TestUnit) -> List[Dict]:
    """Nominations for an unresolved temp-path equality."""
    sandbox = sandbox_names(unit.node)
    if _sandbox_is_resolved_once(unit.node, sandbox):
        return []
    values = _bound_values(unit.node)
    spies = _spy_parameters(unit.node)
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
            continue
        left, right = node.left, node.comparators[0]
        pair = _unresolved_pair(left, right, sandbox, values, spies)
        if not pair:
            continue
        rows.append(
            _finding(
                "UNRESOLVED_TMP_PATH",
                unit,
                node.lineno,
                f"compares a temp-directory path against {pair} with a plain == and no resolver on either "
                f"side - a Windows runner's TEMP is an 8.3 short name (RUNNER~1) until it is resolved, and "
                f"Path == Path compares TEXT. Resolve both sides, or use os.path.samefile",
            )
        )
    return rows


def _unresolved_pair(
    left: ast.expr,
    right: ast.expr,
    sandbox: Set[str],
    values: Dict[str, ast.expr],
    spies: Set[str],
) -> str:
    """A description of the produced side of an unresolved comparison, or "".

    Exactly one side must be sandbox-derived: both is the test's own arithmetic, neither is not this species."""
    if _carries_a_resolver(left) or _carries_a_resolver(right):
        return ""
    left_is_sandbox = _is_sandbox_path(left, sandbox)
    right_is_sandbox = _is_sandbox_path(right, sandbox)
    if left_is_sandbox == right_is_sandbox:
        return ""
    produced = right if left_is_sandbox else left
    if isinstance(produced, ast.Constant) or not _produces_a_path(produced, sandbox, values, spies):
        return ""
    return ast.unparse(produced)


def _target_names(target: ast.expr) -> List[str]:
    """Every name one binding target introduces, tuple unpack included.

    `email, cwd = guard_mod._resolve_caller()` binds both names to the call."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [element.id for element in target.elts if isinstance(element, ast.Name)]
    return []


def _bound_values(unit_node: ast.AST) -> Dict[str, ast.expr]:
    """Name -> the expression it was first bound from, inside this unit."""
    values: Dict[str, ast.expr] = {}
    for target, value in _bindings(unit_node):
        if value is None:
            continue
        for name in _target_names(target):
            values.setdefault(name, value)
    return values


def _spy_parameters(unit_node: ast.AST) -> Set[str]:
    """Parameter names of functions the unit defines INSIDE itself.

    A stand-in production calls receives its arguments FROM production, so they count as produced."""
    found: Set[str] = set()
    for node in ast.walk(unit_node):
        if node is unit_node or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        arguments = node.args
        found |= {a.arg for a in arguments.args + arguments.posonlyargs + arguments.kwonlyargs}
    return found


def _came_out_of_the_subject(node: ast.expr, values: Dict[str, ast.expr], spies: Set[str]) -> bool:
    """True when a value can be traced to something the unit did not build.

    POSITIVE EVIDENCE, NOT THE ABSENCE OF IT: an unrecognised name is no proof it came from the subject."""
    return _traces_to_the_subject(node, values, spies, set())


def _traces_to_the_subject(node: ast.expr, values: Dict[str, ast.expr], spies: Set[str], seen: Set[str]) -> bool:
    """One step of the trace. `seen` stops a name bound in terms of itself."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in PATH_CONSTRUCTORS | {"str"}:
            return any(_traces_to_the_subject(a, values, spies, seen) for a in node.args)
        return True
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _traces_to_the_subject(node.left, values, spies, seen)
    if not isinstance(node, ast.Name):
        return False
    if node.id in spies:
        return True
    if node.id in seen or node.id not in values:
        return False
    seen.add(node.id)
    return _traces_to_the_subject(values[node.id], values, spies, seen)


def _produces_a_path(node: ast.expr, sandbox: Set[str], values: Dict[str, ast.expr], spies: Set[str]) -> bool:
    """True when an expression is a path THE CODE UNDER TEST handed back.

    Path-SHAPED (no constant, no `.name` string) and traced to the subject through the unit's own bindings."""
    if isinstance(node, ast.Name):
        return node.id not in sandbox and _came_out_of_the_subject(node, values, spies)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in PATH_CONSTRUCTORS and _came_out_of_the_subject(node, values, spies)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _produces_a_path(node.left, sandbox, values, spies)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_ATTRIBUTES and _produces_a_path(node.value, sandbox, values, spies)
    return False


def _cwd_seam_sealed(unit_node: ast.AST, sandbox: Set[str], module_strings: Dict[str, str]) -> str:
    """The cwd seam this unit seals onto its sandbox, or "".

    The sandbox must be NAMED by the seal: a `Path.cwd` patched to a Mock puts the process nowhere real."""
    for node in patch_calls(unit_node):
        texts = set()
        for argument in node.args:
            texts |= _argument_text(argument)
        texts |= {module_strings[t] for t in texts if t in module_strings}
        if not any(needle in text for text in texts for needle in CWD_SEAM_NEEDLES):
            continue
        if any(_is_sandbox_path(kw.value, sandbox) for kw in node.keywords) or _names_under(node) & sandbox:
            return sorted(texts)[0] if texts else "Path.cwd"
    for node in ast.walk(unit_node):
        if not isinstance(node, ast.Call) or _tail(corpus.dotted_name(node.func)) != "chdir":
            continue
        if node.args and _is_sandbox_path(node.args[0], sandbox):
            return corpus.dotted_name(node.func)
    return ""


def _sandbox_is_furnished(unit_node: ast.AST, sandbox: Set[str]) -> bool:
    """True when the unit creates something INSIDE its sandbox.

    A unit that lays its own marker down stops an upward walk inside the sandbox; the cheapest cure."""
    for node in ast.walk(unit_node):
        if not isinstance(node, ast.Call) or _tail(corpus.dotted_name(node.func)) not in SANDBOX_MARKER_CALLS:
            continue
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if receiver is not None and _is_sandbox_path(receiver, sandbox):
            return True
        if any(_is_sandbox_path(argument, sandbox) for argument in node.args):
            return True
    return False


def _rendered_sandbox_assert(unit: corpus.TestUnit, sandbox: Set[str]) -> Optional[ast.Assert]:
    """The assertion that reads a rendered component off the sandbox, or None."""
    for statement in corpus.asserts_in(unit):
        for child in ast.walk(statement):
            if not isinstance(child, ast.Attribute) or child.attr not in RENDERED_PATH_PARTS:
                continue
            if _is_sandbox_path(child.value, sandbox):
                return statement
    return None


def shallow_sandbox_rows(unit: corpus.TestUnit, module_strings: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Nominations for a sealed cwd whose ancestors are not rooted."""
    sandbox = sandbox_names(unit.node)
    seam = _cwd_seam_sealed(unit.node, sandbox, module_strings or {})
    if not seam or _sandbox_is_furnished(unit.node, sandbox):
        return []
    statement = _rendered_sandbox_assert(unit, sandbox)
    if statement is None:
        return []
    return [
        _finding(
            "SHALLOW_SANDBOX",
            unit,
            statement.lineno,
            f"seals {seam} onto a temp directory and then asserts on a rendered component of it, with "
            f"nothing rooting the ANCESTORS - cwd is sealed one level deep and a production walk upward "
            f"leaves the sandbox. On Windows TEMP lives under the user profile, so the walk can reach the "
            f"profile directory; /tmp has no such ancestor. Patch a seam the module owns by its own name",
        )
    ]


def _finding(species: str, unit: corpus.TestUnit, line: int, detail: str) -> Dict:
    """One row, in the shape every rule in this pack reports."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "detail": detail}


def unit_rows(
    unit: corpus.TestUnit, module_strings: Optional[Dict[str, str]] = None, helpers: Optional[Set[str]] = None
) -> List[Dict]:
    """Every platform-oracle finding in one unit, scoring and nominated alike.

    No `module_strings`/`helpers` gives the reading for a unit standing alone, never a generous one."""
    strings = module_strings or {}
    return (
        listing_order_rows(unit)
        + mode_injector_rows(unit, strings, helpers)
        + oserror_attribute_rows(unit)
        + unresolved_tmp_path_rows(unit)
        + shallow_sandbox_rows(unit, strings)
    )


def _dedupe_by_unit(rows: List[Dict]) -> List[Dict]:
    """One row per unit, first finding kept.

    ONE ROW PER UNIT, ALWAYS, so one loop-heavy test cannot drive the score below zero."""
    kept: List[Dict] = []
    seen: Set[str] = set()
    for row in rows:
        if row["nodeid"] in seen:
            continue
        seen.add(row["nodeid"])
        kept.append(row)
    return kept


def split_rows(rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """(scored, nominated), each deduped to one row per unit.

    Deduped separately: a scored unit's nomination is a place to look, and hiding it would lose it."""
    scored = [r for r in rows if r["species"] in SCORING_SPECIES]
    nominated = [r for r in rows if r["species"] not in SCORING_SPECIES]
    return _dedupe_by_unit(scored), _dedupe_by_unit(nominated)


def find_platform_oracles(scanned: corpus.Corpus) -> List[Dict]:
    """Every platform-dependent verdict in the corpus, in file order."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        strings = module_level_strings(parsed.tree)
        helpers = probe_helpers(parsed.tree)
        for unit in parsed.units:
            rows.extend(unit_rows(unit, strings, helpers))
    return rows


def _named(rows: List[Dict]) -> str:
    """A capped, comma-joined roster of flagged nodeids with their species."""
    shown = ", ".join(f"{r['nodeid']} ({r['species']})" for r in rows[:MAX_REPORTED])
    extra = f" (+{len(rows) - MAX_REPORTED} more)" if len(rows) > MAX_REPORTED else ""
    return shown + extra


def _nomination_check(nominated: List[Dict], total: int) -> Dict:
    """The nominations line: reported, never scored, always passed.

    An arm that would convict correct tests must not move a number (platform_oracle.md)."""
    if not nominated:
        return {
            "name": "Platform nominations",
            "passed": True,
            "message": f"0/{total} test units carry a platform nomination",
        }
    return {
        "name": "Platform nominations",
        "passed": True,
        "message": (
            f"{len(nominated)}/{total} test units are NOMINATED for a platform-dependent verdict "
            f"(reported only - not scored, not counted as failing): " + _named(nominated)
        ),
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests judge the code or judge the host.

    ``bypass_rules`` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    Only the two SCORING species count; nominations ride in their own passed line.
    No tests reports not_applicable: zero tests measured is not zero quality found."""
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # Built before the empty path: a broken only-test-file must never read as no tests.
    unreadable: List[Dict] = []
    if scanned.unparseable:
        unreadable.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present but "
                f"unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Platform-independent verdicts", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    scored, nominated = split_rows(find_platform_oracles(scanned))
    score = int(((total - len(scored)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Platform-independent verdicts",
            "passed": not scored,
            "message": (
                f"{total - len(scored)}/{total} test units decide on the code rather than on the host"
                if not scored
                else (
                    f"{len(scored)}/{total} test units would decide differently on another platform: " + _named(scored)
                )
            ),
        },
        _nomination_check(nominated, total),
    ]
    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": scored,
        "nominations": nominated,
    }
