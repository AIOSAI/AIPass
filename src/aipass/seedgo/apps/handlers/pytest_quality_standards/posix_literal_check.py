# =================== AIPass ====================
# Name: posix_literal_check.py
# Description: v5 - a path claim that is only true on the platform it was written on
# Version: 1.2.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

r"""Does this test hardcode one platform's path shape?

Reference: posix_literal.md"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "posix_literal"

#: Tried in order; a project matching none of them gets a whole-tree walk.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: A `.resolve()` off one of these is pathlib's, which keeps a branch-name resolver sharing the verb out.
PATH_CONSTRUCTORS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

RESOLVER_FUNCTIONS: frozenset = frozenset({"realpath", "abspath"})

#: `os.path`, `posixpath` and `ntpath` end in it; `helper.abspath(...)` is somebody else's method.
RESOLVER_MODULE_SUFFIX: str = "path"

#: `os.path` is an ALIAS that differs per host; these name their dialect, so convicting them convicts the fix.
DIALECT_MODULES: frozenset = frozenset({"ntpath", "posixpath", "macpath"})

RESOLVE_METHOD: str = "resolve"

#: POSIX-LITERAL is arms 1-2; the other three are a Path rendered to text and compared with a slashed literal.
SPECIES_POSIX_LITERAL: str = "POSIX-LITERAL"
SPECIES_RENDERED_PATH: str = "RENDERED-PATH"
SPECIES_RETURNED_PATH: str = "RETURNED-PATH"
SPECIES_REPR_HAYSTACK: str = "REPR-HAYSTACK"

#: RETURNED-PATH is absent: it flags the same shape whether production normalised the separator or not.
SCORING_SPECIES: tuple = (SPECIES_POSIX_LITERAL, SPECIES_RENDERED_PATH, SPECIES_REPR_HAYSTACK)

#: Split by WHO WROTE THE RENDERING DOWN: the test (the row scores) or the code under test (it nominates).
WRITTEN_RENDERINGS: tuple = ("str()", "f-string", "%-format")
RETURNED_PROVENANCES: tuple = ("subscript", "attribute", "call result")

#: Deliberately not `str.isalnum`: a segment carries dots, dashes and underscores.
PATH_SEGMENT_CHARS: frozenset = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")

#: Forward only: a backslash literal is already a Windows claim, which is arms 1-2's drive test.
POSIX_SEPARATOR: str = "/"

#: A URL, an scp-style remote, a pytest nodeid (posix on every platform, by contract).
NON_PATH_MARKERS: tuple = ("://", "@", "::")

#: Covers `.py`, `.json`, `.local`; not `claude-3.5-sonnet`.
MAX_EXTENSION_LENGTH: int = 5

#: A Path handed to any of these comes back in the HOST's dialect.
RENDER_BUILTINS: frozenset = frozenset({"str", "repr", "format", "ascii"})

PATHISH_NAME_TOKENS: tuple = ("path", "dir", "file", "relpath", "root", "src", "dest", "target", "location")

#: Their presence identifies a Path without following where it came from.
PATH_ATTRIBUTES: frozenset = frozenset(
    {
        "parent",
        "parents",
        "name",
        "stem",
        "suffix",
        "suffixes",
        "relative_to",
        "joinpath",
        "resolve",
        "absolute",
        "with_name",
        "with_suffix",
    }
)

#: A path rooted at one of these was derived, not written down.
SANDBOX_FIXTURES: frozenset = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

#: Any of these inside the comparison acquits the site: they are the cure.
POSIX_SPELLING_METHOD: str = "as_posix"
SEPARATOR_ACQUITTALS: frozenset = frozenset(
    {"os.sep", "os.path.sep", "os.path.join", "posixpath.join", "ntpath.join", "os.fspath", "os.path.normpath"}
)

STRING_COMPARISON_METHODS: frozenset = frozenset({"startswith", "endswith"})

#: Rendering a call record runs its arguments through `repr()`, which doubles a backslash.
MOCK_CALL_RECORDS: frozenset = frozenset(
    {"call_args", "call_args_list", "mock_calls", "await_args", "await_args_list", "method_calls"}
)

#: These hold MANY calls and have no `.args`, so the cure indexes first.
MOCK_CALL_LISTS: frozenset = frozenset({"call_args_list", "mock_calls", "await_args_list", "method_calls"})

#: The full list lives in the report artifact.
MAX_REPORTED: int = 12


def is_rooted(text: str) -> bool:
    """True when a string starts at a filesystem root in either dialect.

    Text-shaped because arm 3 asks it of a substring; `C:/tmp` counts by its second and third characters."""
    if not text:
        return False
    if text[0] in ("/", "\\"):
        return True
    return len(text) > 2 and text[0].isalpha() and text[1] == ":" and text[2] in ("/", "\\")


def rooted_literal(node: ast.AST) -> Optional[ast.Constant]:
    """The node itself when it is a string literal that starts at a root."""
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return node if is_rooted(node.value) else None


def _receiver_literal(func: ast.Attribute) -> Optional[ast.Constant]:
    """The rooted literal a `.resolve()` receiver was constructed from.

    Keyed on the RECEIVER, never the method name: `registry.resolve("@canary", ...)` shares the verb."""
    if func.attr != RESOLVE_METHOD:
        return None
    receiver = func.value
    if not isinstance(receiver, ast.Call) or not isinstance(receiver.func, ast.Name):
        return None
    if receiver.func.id not in PATH_CONSTRUCTORS or not receiver.args:
        return None
    return rooted_literal(receiver.args[0])


def _argument_literal(call: ast.Call, func: ast.Attribute) -> Optional[ast.Constant]:
    """The rooted literal an `os.path.realpath`-shaped call was handed."""
    if func.attr not in RESOLVER_FUNCTIONS or not call.args:
        return None
    module = corpus.dotted_name(func.value)
    if not module.endswith(RESOLVER_MODULE_SUFFIX):
        return None
    if module in DIALECT_MODULES:
        return None
    return rooted_literal(call.args[0])


def resolved_literals(unit: corpus.TestUnit) -> List[Tuple[str, int]]:
    """Every rooted literal this unit puts through a resolver.

    The rule's public entry point; the line is the CALL's, the one a reader has to go and look at."""
    found: List[Tuple[str, int]] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        literal = _receiver_literal(node.func)
        if literal is None:
            literal = _argument_literal(node, node.func)
        if literal is not None:
            found.append((str(literal.value), node.lineno))
    return found


def _path_runs(text: str) -> List[str]:
    """Maximal runs of path-segment characters and forward slashes.

    A colon or a space ends a run, so `"File: apps/something.py"` still yields its path."""
    runs: List[str] = []
    current = ""
    for char in text:
        if char in PATH_SEGMENT_CHARS or char == POSIX_SEPARATOR:
            current += char
            continue
        if current:
            runs.append(current)
        current = ""
    if current:
        runs.append(current)
    return runs


def _carries_extension(segment: str) -> bool:
    """True when a segment ends in a plausible file extension.

    Alphabetic and bounded, which tells `gamma.py` from `claude-3.5-sonnet`."""
    if "." not in segment:
        return False
    tail = segment.rsplit(".", 1)[1]
    return 0 < len(tail) <= MAX_EXTENSION_LENGTH and tail.isalpha()


def _reads_as_a_path(run: str) -> bool:
    """True when a run of path characters is evidence of a filesystem path.

    Two segments, then a trailing slash, a second separator, or an extension on the last one."""
    segments = [part for part in run.split(POSIX_SEPARATOR) if part]
    if len(segments) < 2:
        return False
    return run.endswith(POSIX_SEPARATOR) or run.count(POSIX_SEPARATOR) >= 2 or _carries_extension(segments[-1])


def path_run(text: str, allow_rooted: bool) -> Optional[str]:
    """The filesystem path spelled inside a string literal, or None.

    ``allow_rooted`` is False for arm 3 (rooted literals are arms 1-2's) and True for arm 4, where the separator is the hazard."""
    if any(marker in text for marker in NON_PATH_MARKERS):
        return None
    for run in _path_runs(text):
        if not allow_rooted and is_rooted(run):
            continue
        if _reads_as_a_path(run):
            return run
    return None


def relative_path_run(text: str) -> Optional[str]:
    """Arm 3's reading: the RELATIVE path spelled inside a literal, or None."""
    return path_run(text, allow_rooted=False)


def _literal_run(node: ast.AST) -> Optional[str]:
    """The relative path run of a node, when the node is a string literal."""
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return relative_path_run(node.value)


def _is_pathish_name(text: str) -> bool:
    """True when an identifier or dict key says it holds a path."""
    lowered = text.lower()
    return any(token in lowered for token in PATHISH_NAME_TOKENS)


def _pathish_call(node: ast.Call) -> bool:
    """True when a call constructs or manipulates a Path, or renders one."""
    tail = corpus.dotted_name(node.func).rsplit(".", 1)[-1]
    if tail in PATH_CONSTRUCTORS or tail in PATH_ATTRIBUTES:
        return True
    return any(pathish_expression(arg) for arg in node.args)


def _pathish_subscript(node: ast.Subscript) -> bool:
    """True when a subscript's KEY names a path, or its base is path-ish."""
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str) and _is_pathish_name(key.value):
        return True
    return pathish_expression(node.value)


def pathish_expression(node: ast.AST) -> bool:
    """Does this expression look like it is holding a path?

    A reading of SPELLING, not a type inference: a path in `x` is invisible, a hostname in `target` a false positive."""
    if isinstance(node, ast.Call):
        return _pathish_call(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return pathish_expression(node.left) or isinstance(node.right, ast.Constant)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_ATTRIBUTES or _is_pathish_name(node.attr) or pathish_expression(node.value)
    if isinstance(node, ast.Name):
        return node.id in SANDBOX_FIXTURES or _is_pathish_name(node.id)
    if isinstance(node, ast.Subscript):
        return _pathish_subscript(node)
    if isinstance(node, ast.JoinedStr):
        return any(pathish_expression(part.value) for part in node.values if isinstance(part, ast.FormattedValue))
    return False


def _separator_is_spelled_out(node: ast.AST) -> bool:
    """True when the site names the separator instead of assuming one.

    This is the acquittal a flagged site is rewritten INTO, so convicting it would convict the cure."""
    for sub in ast.walk(node):
        if not isinstance(sub, (ast.Name, ast.Attribute)):
            continue
        dotted = corpus.dotted_name(sub)
        if dotted in SEPARATOR_ACQUITTALS or dotted.rsplit(".", 1)[-1] == POSIX_SPELLING_METHOD:
            return True
    return False


def _builds_a_path(unit: corpus.TestUnit) -> bool:
    """Does this unit construct a Path anywhere in its body?

    THE WEAKEST EVIDENCE THIS RULE USES, on purpose: circumstantial, and one reason that half does not score."""
    for node in ast.walk(unit.node):
        if isinstance(node, ast.arg) and node.arg in SANDBOX_FIXTURES:
            return True
        if isinstance(node, ast.Name) and node.id in SANDBOX_FIXTURES:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PATH_CONSTRUCTORS:
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _literal_operand(node.right):
            return True
    return False


def _literal_operand(node: ast.AST) -> bool:
    """True when a node is a plain string literal - a `/` join's right side."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _written_rendering(node: ast.AST) -> str:
    """The rendering the TEST wrote down, or "" when it wrote none.

    The test chose the dialect on this line, so nothing off-screen can make it right: this half scores."""
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in RENDER_BUILTINS:
        return "str()" if node.args and pathish_expression(node.args[0]) else ""
    if isinstance(node, ast.JoinedStr):
        return "f-string" if pathish_expression(node) else ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _literal_operand(node.left):
        return "%-format" if pathish_expression(node.right) else ""
    return ""


def _returned_value(node: ast.AST, builds_path: bool) -> str:
    """How a value CAME BACK from the code under test, or "".

    Rendered somewhere this file cannot read, so the row nominates; ``builds_path`` is the fallback evidence."""
    if isinstance(node, ast.Subscript):
        return "subscript" if builds_path or _pathish_subscript(node) else ""
    if isinstance(node, ast.Attribute) and node.attr not in PATH_ATTRIBUTES:
        return "attribute" if builds_path or _is_pathish_name(node.attr) else ""
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) not in RENDER_BUILTINS:
        return "call result" if builds_path or _is_pathish_name(corpus.dotted_name(node.func)) else ""
    return ""


def _rendered_side(node: ast.AST, builds_path: bool) -> str:
    """How this expression came to be text, named, or "" when it did not.

    The written rendering is asked FIRST: in `str(entry["path"])` the test put the value through the renderer."""
    return _written_rendering(node) or _returned_value(node, builds_path)


def _species_for(provenance: str) -> str:
    """The species a provenance belongs to - scoring, or nominate-only."""
    return SPECIES_RENDERED_PATH if provenance in WRITTEN_RENDERINGS else SPECIES_RETURNED_PATH


def _rendered_partner(sides: List[ast.expr], subject: ast.AST, builds_path: bool) -> str:
    """How some OTHER side of this comparison came to be text, or ""."""
    for other in sides:
        if other is subject:
            continue
        rendering = _rendered_side(other, builds_path)
        if rendering:
            return rendering
    return ""


def _compare_rows(node: ast.Compare, builds_path: bool) -> List[Tuple[str, int, str]]:
    """Every rendered-path row in one comparison.

    `is` is deliberately absent: a string compared with `is` is a different bug."""
    if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
        return []
    if _separator_is_spelled_out(node):
        return []
    sides: List[ast.expr] = [node.left] + list(node.comparators)
    rows: List[Tuple[str, int, str]] = []
    for side in sides:
        run = _literal_run(side)
        rendering = _rendered_partner(sides, side, builds_path) if run else ""
        if run and rendering:
            rows.append((run, node.lineno, rendering))
    return rows


def _string_method_rows(node: ast.Call, builds_path: bool) -> List[Tuple[str, int, str]]:
    """Every rendered-path row in a `startswith` / `endswith` call."""
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in STRING_COMPARISON_METHODS:
        return []
    if not node.args or _separator_is_spelled_out(node):
        return []
    run = _literal_run(node.args[0])
    if run is None:
        return []
    rendering = _rendered_side(node.func.value, builds_path)
    return [(run, node.lineno, rendering)] if rendering else []


def rendered_path_literals(unit: corpus.TestUnit) -> List[Tuple[str, int, str]]:
    """Every rendered path this unit compares with a forward-slashed literal.

    Arm 3's public entry point; rows are deduped by line and run so a chained comparison is one row."""
    builds_path = _builds_a_path(unit)
    found: List[Tuple[str, int, str]] = []
    seen: Set[Tuple[str, int]] = set()
    for node in ast.walk(unit.node):
        for run, line, rendering in _rows_for_node(node, builds_path):
            if (run, line) in seen:
                continue
            seen.add((run, line))
            found.append((run, line, rendering))
    return found


def _rows_for_node(node: ast.AST, builds_path: bool) -> List[Tuple[str, int, str]]:
    """Arm 3's rows for one node - a comparison or a string-method call."""
    if isinstance(node, ast.Compare):
        return _compare_rows(node, builds_path)
    if isinstance(node, ast.Call):
        return _string_method_rows(node, builds_path)
    return []


def _render_targets(node: ast.AST) -> List[ast.expr]:
    """What an expression renders to text, or [] when it renders nothing."""
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in RENDER_BUILTINS:
        return list(node.args)
    if isinstance(node, ast.JoinedStr):
        return [part.value for part in ast.walk(node) if isinstance(part, ast.FormattedValue)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _literal_operand(node.left):
        return [node.right]
    return []


def _iterated_records(node: ast.AST) -> Dict[str, str]:
    """Comprehension variables that iterate a call record directly, and the record.

    `for call in m.call_args_list` renders through `repr()`; `for arg in call.args` is the cure and stays clean."""
    records: Dict[str, str] = {}
    for sub in ast.walk(node):
        if not isinstance(sub, ast.comprehension) or not isinstance(sub.target, ast.Name):
            continue
        if isinstance(sub.iter, ast.Attribute) and sub.iter.attr in MOCK_CALL_RECORDS:
            records[sub.target.id] = ast.unparse(sub.iter)
    return records


def _record_in_target(target: ast.expr, iterated: Dict[str, str]) -> str:
    """The call record one rendered expression holds, or ""."""
    if isinstance(target, ast.Name) and target.id in iterated:
        return iterated[target.id]
    for sub in ast.walk(target):
        if isinstance(sub, ast.Attribute) and sub.attr in MOCK_CALL_RECORDS:
            return ast.unparse(sub)
    return ""


def _renders_a_call_record(node: ast.AST) -> str:
    """The mock call record this expression renders, by source spelling, or "".

    Read ANYWHERE in the expression: a join around the rendering, over a comprehension variable, still counts."""
    iterated = _iterated_records(node)
    for render in ast.walk(node):
        for target in _render_targets(render):
            record = _record_in_target(target, iterated)
            if record:
                return record
    return ""


def _local_bindings(unit: corpus.TestUnit) -> Dict[str, ast.expr]:
    """First value bound to each plain local name in the unit.

    ONE HOP, FIRST BINDING ONLY: a name rebound later keeps its first reading, which under-reports."""
    bindings: Dict[str, ast.expr] = {}
    for node in ast.walk(unit.node):
        name = _bound_name(node)
        if name and name not in bindings and isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value:
            bindings[name] = node.value
    return bindings


def _bound_name(node: ast.AST) -> str:
    """The single plain name a statement assigns to, or ""."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return ""


def _pathish_needle(node: ast.AST, bindings: Dict[str, ast.expr]) -> bool:
    """Is the thing being searched for a path?

    A rooted literal counts here: inside a rendered repr the separator is the hazard, not the root.
    Needle only: a local bound one hop to a path-ish value, or a call whose own name carries a path word."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return path_run(node.value, allow_rooted=True) is not None
    if pathish_expression(node):
        return True
    return any(_names_a_path(target, bindings) for target in _render_targets(node) or [node])


def _names_a_path(node: ast.AST, bindings: Dict[str, ast.expr]) -> bool:
    """A local bound to a path-ish value, or a call whose own name says path."""
    if isinstance(node, ast.Name):
        return node.id in bindings and pathish_expression(bindings[node.id])
    if isinstance(node, ast.Call):
        return _is_pathish_name(corpus.dotted_name(node.func).rsplit(".", 1)[-1])
    return False


def _haystack_rows(node: ast.Compare, bindings: Dict[str, ast.expr]) -> List[Tuple[str, int, str]]:
    """Every repr-haystack row in one `in` / `not in` comparison."""
    if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return []
    if not _pathish_needle(node.left, bindings):
        return []
    needle = ast.unparse(node.left)
    rows: List[Tuple[str, int, str]] = []
    for haystack in node.comparators:
        record = _rendered_record(haystack, bindings)
        if record:
            rows.append((needle, node.lineno, record))
    return rows


def _rendered_record(node: ast.AST, bindings: Dict[str, ast.expr]) -> str:
    """The call record a haystack renders, following one local binding."""
    record = _renders_a_call_record(node)
    if record:
        return record
    if isinstance(node, ast.Name) and node.id in bindings:
        return _renders_a_call_record(bindings[node.id])
    return ""


def repr_haystack_needles(unit: corpus.TestUnit) -> List[Tuple[str, int, str]]:
    """Every path searched for inside a rendered mock call record."""
    bindings = _local_bindings(unit)
    found: List[Tuple[str, int, str]] = []
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Compare):
            found.extend(_haystack_rows(node, bindings))
    return found


def _finding(unit: corpus.TestUnit, line: int, text: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": SPECIES_POSIX_LITERAL,
        "literal": text,
        "reason": (
            f"rooted path literal {text!r} put through a resolver - a rooted literal is "
            f"DRIVE-RELATIVE under ntpath, so this line means something else on the other "
            f"half of the matrix"
        ),
    }


def _rendered_finding(unit: corpus.TestUnit, line: int, text: str, rendering: str) -> Dict:
    """One arm-3 row: a rendered Path compared with a slashed literal.

    The sentence follows the provenance: a returned value is a question about a producer, never an accusation."""
    species = _species_for(rendering)
    if species == SPECIES_RENDERED_PATH:
        reason = (
            f"path literal {text!r} compared against a value this test rendered from a Path "
            f"({rendering}) - str() of a Path spells the separator the HOST's way, so this "
            f"literal is only right on the leg of the matrix it was written on"
        )
    else:
        reason = (
            f"path literal {text!r} compared against a value returned by the code under test "
            f"({rendering}) - NOMINATION ONLY, not scored: whether the producer normalised the "
            f"separator is off-screen. Compare Path to Path, or as_posix() on both sides"
        )
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": species,
        "literal": text,
        "rendering": rendering,
        "reason": reason,
    }


def _haystack_finding(unit: corpus.TestUnit, line: int, needle: str, record: str) -> Dict:
    """One arm-4 row: a path searched for inside a rendered call record.

    A `call_args_list` has no `.args`, so the cure names an index first."""
    index = "[i]" if record.rsplit(".", 1)[-1] in MOCK_CALL_LISTS else ""
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": SPECIES_REPR_HAYSTACK,
        "literal": needle,
        "record": record,
        "reason": (
            f"{needle} is searched for inside a rendered {record} - str() of a mock call "
            f"record runs its arguments through repr(), which DOUBLES a backslash separator, "
            f"so even a correctly built expected string is not in there. Assert on "
            f"{record}{index}.args[n] or .kwargs instead, never on a rendered repr"
        ),
    }


def find_rooted_literals(scanned: corpus.Corpus) -> List[Dict]:
    """Every resolved rooted literal in the corpus, unit order preserved."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for text, line in resolved_literals(unit):
            rows.append(_finding(unit, line, text))
    return rows


def find_rendered_paths(scanned: corpus.Corpus) -> List[Dict]:
    """Every rendered path compared with a slashed literal - arm 3."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for text, line, rendering in rendered_path_literals(unit):
            rows.append(_rendered_finding(unit, line, text, rendering))
    return rows


def find_repr_haystacks(scanned: corpus.Corpus) -> List[Dict]:
    """Every path searched for inside a rendered call record - arm 4."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for needle, line, record in repr_haystack_needles(unit):
            rows.append(_haystack_finding(unit, line, needle, record))
    return rows


def find_violations(scanned: corpus.Corpus) -> List[Dict]:
    """Every finding in the corpus, grouped by arm.

    ARM ORDER, NOT SOURCE ORDER: a reader wants each arm's rows together; the score dedupes by nodeid anyway."""
    return find_rooted_literals(scanned) + find_rendered_paths(scanned) + find_repr_haystacks(scanned)


def split_rows(rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """(scored, nominated), split by species and NOT deduped.

    NOT DEDUPED, unlike `platform_oracle`: every line is a fix; the dedupe happens at `flagged_nodeids`."""
    scored = [row for row in rows if row["species"] in SCORING_SPECIES]
    nominated = [row for row in rows if row["species"] not in SCORING_SPECIES]
    return scored, nominated


def _nomination_check(nominated: List[Dict], total: int) -> Dict:
    """The nominations line: reported, never scored, always passed.

    An arm that would convict correct code must not move a number (posix_literal.md)."""
    units = flagged_nodeids(nominated)
    if not units:
        return {
            "name": "Path provenance nominations",
            "passed": True,
            "message": f"0/{total} test units carry a path-provenance nomination",
        }
    overflow = f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else ""
    return {
        "name": "Path provenance nominations",
        "passed": True,
        "message": (
            f"{len(units)}/{total} test units compare a path literal with a value RETURNED by the "
            f"code under test (reported only - not scored, not counted as failing): "
            + ", ".join(units[:MAX_REPORTED])
            + overflow
        ),
    }


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING, so one loop-heavy test cannot drive it below zero."""
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def _flagged_message(rows: List[Dict], units: List[str], total: int) -> str:
    """The check line, naming what was actually found rather than a guess.

    Arms 1-2 alone keep the resolver sentence; any rendering row widens it to the claim all four arms share."""
    species = {row["species"] for row in rows}
    if species == {SPECIES_POSIX_LITERAL}:
        head = f"{len(units)}/{total} test units put a rooted path literal through a resolver: "
    else:
        head = f"{len(units)}/{total} test units spell a path in one platform's dialect: "
    overflow = f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else ""
    return head + ", ".join(units[:MAX_REPORTED]) + overflow


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests hardcode one platform's root.

    ``bypass_rules`` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    RETURNED-PATH rides in its own passed nominations line, outside the score.
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
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Path dialect literals", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    scored, nominated = split_rows(find_violations(scanned))
    units = flagged_nodeids(scored)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Path dialect literals",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units keep their path claims off a single dialect"
                if not units
                else _flagged_message(scored, units, total)
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
