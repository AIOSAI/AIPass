# =================== AIPass ====================
# Name: platform_oracle_check.py
# Description: v5 - is this test's verdict a fact about the code or about the host
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""Is this test's pass or fail a fact about the code, or a fact about the host?

    files = sorted(p for p in target.rglob("*") if p.is_file())
    assert [f.name for f in files] == ["SKILL.md", "handler.py"]

That list is sorted and it is STILL platform-ordered. `sorted()` over Path
objects uses `PurePath.__lt__`, which is case-SENSITIVE on POSIX and case-FOLDED
under ntpath. POSIX puts `"SKILL.md"` first because `'S' < 'h'`; Windows folds
the case, reads `"handler.md" < "skill.md"`, and hands back the other order. The
production code laid down the same two files on both. The pin is what disagreed.

WHY THIS RULE EXISTS. A CI matrix ran Linux and Windows for the first time after
eight waves of test work had landed overnight on Linux-only verification. Nobody
wrote a bad test; everybody wrote down the only platform they could see. The pack
had no rule for this. Four existing rules mention platform divergence and three of
them mention it only to ACQUIT it - `self_skip` acquits a genuine platform skip,
`empty_parametrize` acquits a matrix that empties on one leg, `assertion_shape`
acquits a separator comparison. `posix_literal` is the only one that convicts, and
it is scoped to exactly one syntactic shape: a rooted literal put through a
resolver. Everything between those two positions was unowned. This rule is that
gap, and it is deliberately about the OUTCOME rather than about the spelling: not
"does this line contain a slash" but "would this assertion have gone the other way
on the other runner".

FIVE SPECIES, AND THE SPLIT BETWEEN THEM IS THE DESIGN. Two score. Three
nominate and are excluded from the number entirely.

  SCORING - LISTING_ORDER. An ordered equality against a list literal whose other
    side was built by a directory listing (`iterdir`, `listdir`, `glob`, `rglob`,
    `scandir`, `os.walk`), with or without `sorted()` applied to Paths. The
    filesystem's own order is arbitrary everywhere; `sorted()` over Paths merely
    replaces it with a DIFFERENT arbitrary order that is not the same on both
    hosts. Acquitted when the order has been taken out of the claim: a
    `sorted(..., key=...)` - any key at all, because any key displaces Path's own
    comparison, and the two spellings seen in practice are `key=str` and
    `key=lambda p: p.name` - or a `set` / `frozenset` / `Counter` on either side,
    or `sorted` textually on BOTH sides, or a one-element literal, where order
    cannot differ.

  SCORING - MODE_INJECTOR. A failure injected by the FILESYSTEM'S MOOD instead of
    at a seam. `chmod` to a read-only mode, `stat.S_IREAD`-style constants with no
    write bit, or a POSIX device-path literal (`/dev/null/...`, `/dev/full`,
    `/proc/...`, `/sys/...`), used to provoke an `OSError` the unit then asserts
    on. Windows ignores POSIX mode bits for the owner and has no `/dev/null`
    directory semantics, so the write SUCCEEDS, no error is raised, and the
    must-warn assertion sees zero calls. Acquitted, always and without exception,
    when the failure is injected at a patched seam - `patch` on `open`,
    `write_text`, `write_bytes`, `os.replace`, `Path.open` with an OSError
    side_effect. That IS the cure this rule teaches, so it must never be the thing
    the rule flags.

  NOMINATE-ONLY - OSERROR_ATTRIBUTE, UNRESOLVED_TMP_PATH, SHALLOW_SANDBOX. Each
    of these three, written as a convicting arm, flags correct tests. An assertion
    on `.errno` is often right. An unresolved `tmp_path` comparison is usually
    right on the host that wrote it and often right everywhere. A patched `cwd`
    with an unrooted ancestor walk is only a defect when production walks up, and
    no reader here can see that it does. So they are reported in their own check
    line, with `passed: True`, and they move NO number: an arm that would convict
    correct tests must not be allowed to move a score, because the first time a
    fleet sees its number drop for a test that was right, the number stops being
    read at all. Reporting them still pays - a nomination is a place to look.

WHAT ACQUITS, BEYOND THE PER-ARM LISTS ABOVE. Every acquittal in this file runs
toward FEWER flags, which is the safe direction for a rule that accuses.

WHAT THIS FILE CANNOT SEE:

  - IT DOES NOT FOLLOW CALLS. The `chmod` is flagged where it is written; a
    read-only mode applied by a helper, or a listing performed in a fixture, is
    invisible. So is the seam patch that would have acquitted it.
  - IT CANNOT SEE WHERE AN EXCEPTION CAME FROM. `OSERROR_ATTRIBUTE` reads an
    attribute off a name captured by `pytest.raises` or an `except` clause. That
    the exception was raised by a subprocess launch - which is the case where
    Windows leaves `.filename` as None - is not provable from the unit, and that
    unprovability is one of the reasons the arm nominates rather than scores.
  - IT NEVER ASKS THE RUNNING MACHINE. `"/dev/full"` is judged as text and Path
    ordering is judged from the shape of the comparison, never by asking this
    interpreter what it would do. A portability rule that consulted the host would
    report a different standard on every leg of the matrix, which is the exact
    defect it exists to find. It is also why these findings mean the same thing
    run from either runner.
  - IT READS ONE HOP AND STOPS. `files = sorted(...rglob(...))` then a comparison
    naming `files` is resolved, because the row this rule was written for is
    spelled exactly that way. A value that travels through a second function, a
    module-level constant or another file is not followed.
  - A FLAGGED SITE MAY BE PERFECTLY CORRECT for a reason a human can see and this
    reader cannot. It nominates. A human decides.

STDLIB ONLY - `ast`, `pathlib`, `typing`, and the pack's own corpus reader, like
the rest of the pack. That constraint is why the pack lifts onto any project.
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "platform_oracle"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: The two species that move the score. Everything else in this file is
#: reported and deliberately excluded - see the module docstring.
SCORING_SPECIES: tuple = ("LISTING_ORDER", "MODE_INJECTOR")

#: Calls that hand back the contents of a directory. The filesystem's own order
#: is arbitrary on every platform; these are where that arbitrariness enters.
LISTING_CALLS: frozenset = frozenset({"iterdir", "listdir", "glob", "rglob", "scandir", "walk"})

#: Call roots that own a `walk` of their own and mean something else entirely.
#: `ast.walk` is in every checker in this pack and lists no directory.
NOT_LISTING_ROOTS: frozenset = frozenset({"ast", "os.path", "json", "re"})

#: Wrappers that take the order out of an equality. A set does not have one and
#: a Counter does not read one.
UNORDERED_WRAPPERS: frozenset = frozenset({"set", "frozenset", "Counter"})

#: Reads and calls that answer with a STRING rather than with a Path. A sort
#: over these is a plain string sort, which is byte order on every host - it is
#: only `sorted()` over PATH objects that is platform-ordered.
STRING_VALUED_ATTRIBUTES: frozenset = frozenset({"name", "stem", "suffix"})

#: Calls that turn a path into a string, by tail spelling.
STRING_VALUED_CALLS: frozenset = frozenset({"str", "as_posix", "lower", "upper", "casefold", "strip", "format"})

#: Listings that hand back strings to begin with. `os.listdir` already answers
#: with names, so sorting its result is a string sort with nothing to narrow.
STRING_LISTING_CALLS: frozenset = frozenset({"listdir"})

#: Constructors whose first argument is a path.
PATH_CONSTRUCTORS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

#: Path methods that answer with another path, so a sandbox root survives them.
PATH_METHODS: frozenset = frozenset({"joinpath", "with_name", "with_suffix", "expanduser", "resolve", "absolute"})

#: Path attributes that answer with another path. `.name` and `.stem` are absent
#: on purpose - they answer with a string, and a string compared against a
#: string is not the species this rule is looking for.
PATH_ATTRIBUTES: frozenset = frozenset({"parent"})

#: Fixture names whose value pytest creates and removes.
SANDBOX_FIXTURES: frozenset = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

#: Calls that mint a temporary directory outside the pytest fixture. The row
#: this rule was written for uses `tempfile.TemporaryDirectory`, not `tmp_path`,
#: and the hazard is identical: the Windows runner's TEMP is an 8.3 short name.
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

#: Calls that normalise a path against the real filesystem. Either side of a
#: comparison carrying one of these has already taken the cure.
RESOLVING_CALLS: frozenset = frozenset({"resolve", "absolute", "realpath", "samefile", "readlink", "canonicalize"})

#: Path prefixes that only exist, and only misbehave, on POSIX. `/dev/null`
#: EXACTLY is absent on purpose: as a sink it is correct and common. It is
#: `/dev/null/something` - null used as a DIRECTORY - that provokes the ENOTDIR
#: this arm is about, and Windows has no such semantics to provoke.
DEVICE_PATH_PREFIXES: tuple = ("/dev/null/", "/dev/full", "/dev/zero/", "/proc/", "/sys/")

#: The owner write bit. A mode literal without it is a read-only mode.
OWNER_WRITE_BIT: int = 0o200

#: Seams a test can patch to make a write fail on every platform equally. A
#: patch on one of these is the cure, so it acquits unconditionally.
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

#: Exception types an injected filesystem failure is asserted through.
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

#: Attribute reads that show a unit is asserting on a FAILURE rather than on a
#: value. A mock's warning counter is how the row this arm was written for
#: proves the write went wrong.
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

#: Exception attributes whose value is filled by the operating system rather
#: than by the code under test.
OSERROR_ATTRIBUTES: frozenset = frozenset({"filename", "filename2", "strerror", "errno", "winerror"})

#: What each of those attributes actually does on the other leg of the matrix.
#: Spelled out per attribute because "it differs" is not a finding a reader can
#: act on, and the cure is different for each.
OSERROR_ATTRIBUTE_HAZARD: Dict[str, str] = {
    "filename": (
        "a Windows subprocess launch raises FileNotFoundError with filename=None ([WinError 2]) while POSIX fills it in"
    ),
    "filename2": "the second filename is filled by POSIX rename/link failures and is None under Windows",
    "strerror": "the message text comes from the platform C library and is not the same string on both",
    "errno": "Windows translates its own error codes into errno, and the translation is not one to one",
    "winerror": "winerror does not exist on a POSIX OSError at all - reading it raises AttributeError",
}

#: Calls that seal the working directory. Sealing `cwd` does not seal what is
#: ABOVE it, which is the whole of the SHALLOW_SANDBOX species.
CWD_SEAM_NEEDLES: tuple = ("Path.cwd", "os.getcwd", "getcwdb", "pathlib.Path.cwd")

#: Path methods that put a file or directory INSIDE the sandbox. A unit that
#: furnishes its sandbox is not relying on what an ancestor happens to hold.
SANDBOX_MARKER_CALLS: frozenset = frozenset({"mkdir", "touch", "write_text", "write_bytes", "symlink_to", "makedirs"})

#: Rendered path components. Asserting on one of these after sealing `cwd` is
#: asserting on which directory production decided to stop at.
RENDERED_PATH_PARTS: frozenset = frozenset({"name", "stem", "parts", "parent"})

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message printing hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# READING - BINDINGS, ROOTS, PATCHES
# =============================================================================


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

    `with tempfile.TemporaryDirectory() as td` is here beside plain assignment
    because the row that named UNRESOLVED_TMP_PATH is spelled that way, and a
    reader that only walked `Assign` would have called it clean. Split across
    two helpers rather than an elif chain: an `elif` is an `If` inside the
    previous one's `orelse`, so a four-way chain reads as four levels of nesting
    to this repo's own deep_nesting rule, which convicted the first version.
    """
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

    ONE MECHANISM, THREE ARMS. `sorted(...rglob(...))` bound to `files`, a
    tempdir bound to `td`, an `__cause__` bound to `cause` - all three are the
    same shape, and writing the loop once is what keeps the three arms from
    disagreeing about what "derived from" means. It never leaves the unit, never
    resolves an import and never executes anything.
    """
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

    A path, not a string read off one. `tmp_path.name` is a string and is not
    accepted here, because a string compared against a string is a different
    question than a path compared against a path.
    """
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

    Seeded with the pytest fixture names themselves: a unit naming `tmp_path`
    means the fixture, and there is no other thing it could mean.
    """
    seeds = set(SANDBOX_FIXTURES)
    return seeds | _grow(unit_node, lambda value, bound: _is_sandbox_path(value, seeds | bound))


def _argument_text(argument: ast.expr) -> Set[str]:
    """The seam names one patch argument names, as text.

    An f-string is read piece by piece - `patch(f"{MOD}.open")` names both the
    constant tail and the name holding the module path, and either half may be
    the one an acquittal needs to match.
    """
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

    A LOCAL ALIAS COUNTS, and it had to. The rows that named SHALLOW_SANDBOX are
    written `from unittest.mock import patch as _patch` because the unit already
    takes a `monkeypatch` fixture and the author wanted the two spellings to
    read apart. A reader keyed on the exact name `patch` saw no seal at all and
    called both rows clean. `endswith("_patch")` catches the alias without
    catching `dispatch`, which a bare `endswith("patch")` would.
    """
    tail = _tail(dotted)
    if tail in {"setattr", "delattr"}:
        return dotted.startswith("monkeypatch.")
    return tail in {"patch", "object", "dict"} or tail.endswith("_patch")


def module_level_strings(tree: ast.Module) -> Dict[str, str]:
    """Module-level names bound to a plain string literal.

    The other half of the one hop. `LOGGER_PATCH = "...telegram_response.logger"`
    at the top of a file, named by every `patch()` below it - and a rule reading
    literals only would judge that patch by the constant's NAME.
    """
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

    Deliberately TEXT rather than resolved objects: a rule that resolved patch
    targets would be importing the branch under audit. `module_strings` defaults
    to none so a caller holding no tree gets the literal-only reading rather
    than a silently generous one.
    """
    known = module_strings or {}
    targets: Set[str] = set()
    for node in patch_calls(unit_node):
        for argument in node.args:
            for text in _argument_text(argument):
                targets.add(text)
                if text in known:
                    targets.add(known[text])
    return targets


# =============================================================================
# SCORING ARM 1 - LISTING_ORDER
# =============================================================================


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

    A DICT AND NOT A SET, because the value is what the finding has to print.
    The row this arm was written for binds `files` from the rglob and then walks
    it again as `for f in files`, so a set-valued reading had two names to
    choose from and named the loop variable - a reader told the other side "came
    from f" has been told nothing. The listing's own spelling travels with the
    name instead.
    """
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

    TWO WAYS TO TAKE PATH COMPARISON OUT OF A SORT, and the second one is the
    narrowing this arm needed. `PurePath.__lt__` is case-SENSITIVE on POSIX and
    case-FOLDED under ntpath, so `sorted()` over PATH OBJECTS is where the
    divergence enters. `sorted(p.name for p in d.glob(...))` never touches that
    comparison at all - it sorts strings, byte order, the same list on every
    host. Measured before this narrowing: 5 LISTING_ORDER rows fleet-wide, of
    which 4 were @memory sorting `.name` off a glob - and two of those four are
    that branch's own case-folding pins, which handle both hosts in an
    `if len(entries) == 1:` and are the most portable code in the corpus. After:
    1 row, the one this rule was written for.

    Any KEY acquits too, and that is a statement about what a key DOES rather
    than a convenience: supplying one displaces `PurePath.__lt__` entirely. The
    spellings that appear in real cures are `key=str` and `key=lambda p: p.name`;
    a key that sorts by size is just as deterministic, and this rule has no
    business preferring one.
    """
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

    THE HOP COUNTS FOR THE NEUTRAL SORT AND NOT FOR THE BOTH-SIDES RULE, on
    purpose. A sort that never used Path comparison, one hop away, really did
    fix the order the comparison reads. A `sorted()` on the LITERAL side alone
    did not: the listing side is still in Path order, the literal side is now in
    string order, and the two agree on exactly one platform. So the both-sides
    acquittal is textual, and it is the stricter reading precisely where being
    strict is right.
    """
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


# =============================================================================
# SCORING ARM 2 - MODE_INJECTOR
# =============================================================================


def _mode_spellings(node: ast.expr) -> Set[str]:
    """Every `S_I*` name in a mode expression, dotted or bare.

    ITS OWN READER, AND THE MEASUREMENT SAYS WHY. `_names_under` collects bare
    names and dotted CALL targets, which is what its seven other readers want. A
    mode constant is neither: `stat.S_IREAD` is a plain attribute, and read
    through `_names_under` the whole expression came back as the single name
    "stat". Measured before this reader, on two units differing only in spelling:
    `target.chmod(S_IREAD | S_IRGRP)` scored 0 and
    `target.chmod(stat.S_IREAD | stat.S_IRGRP)` scored 100 - the dotted form,
    which is the one this rule's own text prints, was the one that got away.
    """
    found: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return {name for name in found if name.startswith("S_I")}


def _readonly_mode(node: ast.expr) -> str:
    """How this mode expression removes the write bit, or "".

    A bare int is read against the owner write bit; a `stat.S_I*` expression is
    read by its NAMES - dotted or bare, see `_mode_spellings` - and any name
    carrying a W is a write bit that keeps the mode writable. `isinstance(True, int)` is true in Python, so booleans are
    refused by name rather than silently read as mode 1.
    """
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

    The mode is the LAST positional argument in both spellings - `os.chmod(p, m)`
    and `p.chmod(m)` - so one read covers both without asking which one this is.
    """
    if _tail(corpus.dotted_name(node.func)) != "chmod" or not node.args:
        return ""
    mode = _readonly_mode(node.args[-1])
    return f"chmod to {mode}" if mode else ""


def _device_literal(node: ast.AST) -> str:
    """The POSIX-only device path this node writes down, or "".

    `/dev/null` EXACTLY is not here. As a sink it is correct, common and
    portable through `os.devnull`. It is `/dev/null/something` - null used as a
    DIRECTORY, which is an ENOTDIR that only POSIX has to give - that this arm
    is about.
    """
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

    Two spellings, and the second is the one the row that named this arm uses.
    A `pytest.raises(OSError)` is the obvious form. A mock logger's
    `warning.call_count` is the form a unit takes when production is supposed to
    REPORT the failure instead of raising it - which is exactly the claim that
    silently inverts when the write succeeds.
    """
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

    THE ONE ACQUITTAL THAT IS NOT NEGOTIABLE. Injecting at the seam is the cure
    this arm teaches, so an arm that could flag the cure would be teaching a
    rewrite into something it also flags. Read from the patch TARGET's last
    dotted segment, and from a `side_effect=` naming an OS error, because those
    are the two halves of the spelling.
    """
    for text in patched_targets(unit_node, module_strings):
        if _tail(text) in WRITE_SEAMS:
            return text
    for node in patch_calls(unit_node):
        for keyword in node.keywords:
            if keyword.arg == "side_effect" and _names_under(keyword.value) & OSERROR_TYPES:
                return "side_effect on a patched seam"
    return ""


def mode_injector_rows(unit: corpus.TestUnit, module_strings: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Findings for a failure injected by the filesystem's mood, not at a seam."""
    injectors = _injectors_in(unit.node)
    if not injectors or not _asserts_on_failure(unit):
        return []
    if _seam_injects_the_failure(unit.node, module_strings or {}):
        return []
    line, described = injectors[0]
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


# =============================================================================
# NOMINATE-ONLY ARM 3 - OSERROR_ATTRIBUTE
# =============================================================================


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

    The hop is what reaches the row: `cause = exc_info.value.__cause__` puts the
    OS-filled exception in a SECOND name, and the assertion is written against
    that one.
    """
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

    THE ATTRIBUTE IS ONLY OS-FILLED WHEN THE OS FILLED IT. A stand-in the unit
    installs and then raises from - `raise OSError(errno.EXDEV, "invalid
    cross-device link")` inside a monkeypatched `os.replace` - puts the test's
    OWN literal in `.errno`, and a literal is the same number on every platform
    because the test wrote it down. `side_effect=OSError(...)` on a patch is the
    same thing spelled shorter. Measured over the four rows this arm found: two
    of them - @spawn's and @seedgo's atomic-write retry pins - are exactly this
    shape, and both are portable code. The other two capture an exception the
    host raised, and they stay.

    The nested `def` is reached because it is defined inside the unit, so the
    unit's own walk descends into it. A raise in a helper in another file is
    not seen, which is the same limit every rule in this pack publishes.
    """
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


# =============================================================================
# NOMINATE-ONLY ARM 4 - UNRESOLVED_TMP_PATH
# =============================================================================


def _carries_a_resolver(node: ast.AST) -> bool:
    """True when any call under a node normalises a path against the filesystem."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _tail(corpus.dotted_name(child.func)) in RESOLVING_CALLS:
            return True
    return False


def _sandbox_is_resolved_once(unit_node: ast.AST, sandbox: Set[str]) -> bool:
    """True when the unit rebinds a sandbox name through a resolver.

    `tmp_path = tmp_path.resolve()` as the first line is the template's cure,
    and after it every later comparison in the unit is already resolved without
    saying so on its own line. Reading only the comparison would flag the unit
    that took the cure.
    """
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

    Exactly one side has to be sandbox-derived. Both sides sandbox-derived is a
    test comparing its own arithmetic and carries no claim about the code, and
    neither side sandbox-derived is not this species at all.
    """
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

    `email, cwd = guard_mod._resolve_caller()` binds BOTH names to the call, and
    a reader that only understood a bare Name target could not say where `cwd`
    came from. Six of the rows measured for this arm are spelled that way.
    """
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

    A stand-in the unit installs and production then calls receives its
    arguments FROM production. `def counting_stat(self, ...)` compared against a
    `tmp_path`-built file is asking what path production stat-ed, which is the
    species exactly - if production resolves before it stats, the two sides are
    one file under two spellings.
    """
    found: Set[str] = set()
    for node in ast.walk(unit_node):
        if node is unit_node or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        arguments = node.args
        found |= {a.arg for a in arguments.args + arguments.posonlyargs + arguments.kwonlyargs}
    return found


def _came_out_of_the_subject(node: ast.expr, values: Dict[str, ast.expr], spies: Set[str]) -> bool:
    """True when a value can be traced to something the unit did not build.

    POSITIVE EVIDENCE, NOT THE ABSENCE OF IT. The first version asked only "is
    this name NOT sandbox-derived", which is a different question and answers
    yes for anything the reader failed to recognise. Measured over 84 rows: 82
    trace to a call the subject made, 1 is a parameter production hands to a
    spy, and 1 is a path the TEST built through a `for parent in [current,
    *current.parents]` loop and then compared against its own `parent_dir`. That
    last one cannot drift on a short name - neither side ever went through
    production's resolver, so both are the same unresolved text - and it is the
    only row this narrowing removes.
    """
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

    Two conditions, and the second is the one that makes the arm's own sentence
    true. It has to be path-SHAPED - a constant is refused above, and a `.name`
    read is refused because it is a string and a string carries no short-name
    hazard. And it has to have COME FROM the subject, traced through the unit's
    own bindings, rather than merely failing to look like the sandbox.
    """
    if isinstance(node, ast.Name):
        return node.id not in sandbox and _came_out_of_the_subject(node, values, spies)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in PATH_CONSTRUCTORS and _came_out_of_the_subject(node, values, spies)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _produces_a_path(node.left, sandbox, values, spies)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_ATTRIBUTES and _produces_a_path(node.value, sandbox, values, spies)
    return False


# =============================================================================
# NOMINATE-ONLY ARM 5 - SHALLOW_SANDBOX
# =============================================================================


def _cwd_seam_sealed(unit_node: ast.AST, sandbox: Set[str], module_strings: Dict[str, str]) -> str:
    """The cwd seam this unit seals onto its sandbox, or "".

    The sandbox has to be NAMED by the seal. A `patch("pathlib.Path.cwd")` with
    a Mock return value is a different test entirely - it never puts the process
    anywhere real, so no ancestor walk can escape into the user's profile.
    """
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

    A unit that lays down its own marker is not relying on what an ancestor
    happens to hold, so an upward walk stops inside the sandbox and the render
    is the sandbox's own name. That is the acquittal, and it is also the cheapest
    cure available to a flagged site.
    """
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


# =============================================================================
# ANALYSIS
# =============================================================================


def _finding(species: str, unit: corpus.TestUnit, line: int, detail: str) -> Dict:
    """One row, in the shape every rule in this pack reports."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "detail": detail}


def unit_rows(unit: corpus.TestUnit, module_strings: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Every platform-oracle finding in one unit, scoring and nominated alike.

    `module_strings` defaults to none deliberately: a caller holding no tree
    gets the reading for a unit standing alone, which is the pre-acquittal
    reading, rather than a silently generous one.
    """
    strings = module_strings or {}
    return (
        listing_order_rows(unit)
        + mode_injector_rows(unit, strings)
        + oserror_attribute_rows(unit)
        + unresolved_tmp_path_rows(unit)
        + shallow_sandbox_rows(unit, strings)
    )


def _dedupe_by_unit(rows: List[Dict]) -> List[Dict]:
    """One row per unit, first finding kept.

    ONE ROW PER UNIT, ALWAYS. A unit carrying two species is one unit a reader
    has to go and look at; counting the findings would let a single loop-heavy
    test drive a project's score below zero, and a score that can go negative is
    one nobody believes twice.
    """
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

    DEDUPED SEPARATELY, AND THAT IS THE POINT OF THE SPLIT. A unit that scores
    for a LISTING_ORDER and also carries an UNRESOLVED_TMP_PATH nomination
    appears in both lines, because the second line is not a penalty - it is a
    place to look, and hiding it behind the first would lose it.
    """
    scored = [r for r in rows if r["species"] in SCORING_SPECIES]
    nominated = [r for r in rows if r["species"] not in SCORING_SPECIES]
    return _dedupe_by_unit(scored), _dedupe_by_unit(nominated)


def find_platform_oracles(scanned: corpus.Corpus) -> List[Dict]:
    """Every platform-dependent verdict in the corpus, in file order."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        strings = module_level_strings(parsed.tree)
        for unit in parsed.units:
            rows.extend(unit_rows(unit, strings))
    return rows


def _named(rows: List[Dict]) -> str:
    """A capped, comma-joined roster of flagged nodeids with their species."""
    shown = ", ".join(f"{r['nodeid']} ({r['species']})" for r in rows[:MAX_REPORTED])
    extra = f" (+{len(rows) - MAX_REPORTED} more)" if len(rows) > MAX_REPORTED else ""
    return shown + extra


def _nomination_check(nominated: List[Dict], total: int) -> Dict:
    """The nominations line: reported, never scored, always passed.

    PASSED TRUE AND OUTSIDE THE NUMBER, and the docstring of this module says
    why at length: each of these three arms, written to convict, flags correct
    tests. An arm that would convict correct tests must not move a number. The
    first time a fleet watches its score drop for a test that was right, the
    score stops being read - and then the arms that ARE sound stop being read
    with it.
    """
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


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests judge the code or judge the host.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to be
            excused from. Wiring a bypass before the standard can fail would be
            granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory. The score counts the two SCORING species only; the three
        nominate-only species are reported in their own check line, with
        passed True, and are excluded from both the score and the failing count.
        A project with no tests reports not_applicable rather than a number,
        because zero tests measured is not zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. A project whose only test file has a syntax error must never report
    # what a project with no tests at all reports.
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
