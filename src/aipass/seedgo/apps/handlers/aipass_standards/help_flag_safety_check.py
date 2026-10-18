# =================== AIPass ====================
# Name: help_flag_safety_check.py
# Description: Help-Flag Safety Standards Checker Handler
# Version: 1.0.1
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Help-Flag Safety Standards Checker Handler

Reference: help_flag_safety.md
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

# CLI routing conventions live in production code. Test files build argument
# lists as fixtures, never as a command surface a user can type into.
APPLIES_TO = "production"

STANDARD = "HELP_FLAG_SAFETY"
_STANDARD_KEY = "help_flag_safety"

# Dashed forms are unambiguous anywhere on a command line. The bare word is
# included because branches gate on it too, and a gate is a gate.
_HELP_TOKENS = frozenset({"--help", "-h", "help"})

# Names that mean "this call already answered the whole-list question".
# Deliberately verb-led: print_help() prints help, it does not detect it, and
# treating it as a scan is how a checker learns to pass broken code.
_SCAN_VERBS = (
    "wants_help",
    "want_help",
    "has_help",
    "is_help",
    "help_requested",
    "check_help",
    "detect_help",
    "asked_for_help",
)

# Calls that consume arguments without acting on them. Passing the argument
# list to a logger or an error message is not execution, so it does not make
# a stray flag dangerous.
_SINK_HINTS = ("log", "print", "console", "error", "warning", "info", "debug", "critical", "exception")

# Calls that exist to SHOW something. `show_help()`, `usage()` and
# `print_introspection()` are the answer to a help request, never the harm of
# one, so reaching them past a gate is not "the command executed".
_DISPLAY_HINTS = ("help", "usage", "introspection", "header", "banner")

# Calls that compute a value and change nothing: builtins, constructors and the
# string/collection methods a routing function uses to tidy its own input. A
# tail built only from these is not a doing-path, so it is not a violation.
_INERT_CALLS = frozenset(
    {
        "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "frozenset",
        "sorted", "reversed", "enumerate", "range", "zip", "map", "filter",
        "any", "all", "sum", "min", "max", "abs", "round", "repr", "type",
        "isinstance", "hasattr", "getattr",
        "Path", "join", "split", "rsplit", "strip", "lstrip", "rstrip",
        "lower", "upper", "title", "capitalize", "startswith", "endswith",
        "replace", "format", "encode", "decode",
        "get", "keys", "values", "items", "append", "extend", "index", "count", "copy",
    }
)  # fmt: skip

# The router functions an entry point may use to intercept help.
_ROUTER_FUNCS = frozenset({"main", "route_command"})

_ENTRY_FUNC = "handle_command"

_MAX_DELEGATE_DEPTH = 3

# argparse entry points. Called with no explicit list they read sys.argv, so a
# name bound from one carries command-line text just as sys.argv[1:] does.
_ARGPARSE_PARSE = frozenset({"parse_args", "parse_known_args"})

# The two spellings a user can type ANYWHERE on a command line. The bare word
# `help` is deliberately absent: it is legitimate content for a module that
# takes free text, so a standalone screen is not required to catch it.
_DASHED_HELP_TOKENS = frozenset({"--help", "-h"})


def _is_help_constant(node: ast.AST) -> bool:
    """Whether *node* is a string literal that asks for help."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _HELP_TOKENS


def _collection_holds_help(node: ast.AST) -> bool:
    """Whether *node* is a literal collection containing a help token."""
    return isinstance(node, (ast.List, ast.Tuple, ast.Set)) and any(_is_help_constant(e) for e in node.elts)


def _fixed_slot(node: ast.AST) -> Optional[Tuple[str, int]]:
    """Return (sequence_name, index) for ``name[0]``-style access, else None."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, int):
            return (node.value.id, index.value)
    return None


def _is_whole_sequence(node: ast.AST) -> bool:
    """Whether *node* names a whole sequence rather than one fixed element."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
        return True
    return isinstance(node, ast.Attribute)


def _compares_against_help(node: ast.Compare) -> bool:
    """Whether a Compare tests something against a help token."""
    for op, comparator in zip(node.ops, node.comparators):
        if isinstance(op, ast.Eq) and _is_help_constant(comparator):
            return True
        if isinstance(op, ast.In) and (_collection_holds_help(comparator) or _is_help_constant(comparator)):
            return True
    return False


def _callee_name(node: ast.Call) -> str:
    """Best-effort name of what a Call invokes."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def find_fixed_gates(func: ast.AST) -> List[Tuple[str, int, int]]:
    """Find help gates pinned to one argument position."""
    gates: List[Tuple[str, int, int]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        slot = _fixed_slot(node.left)
        if slot is not None and _compares_against_help(node):
            gates.append((slot[0], slot[1], node.lineno))
    return gates


def _is_membership_scan(node: ast.Compare) -> bool:
    """``"--help" in args`` -- the flag tested against a whole sequence."""
    if not _is_help_constant(node.left):
        return False
    return any(
        isinstance(op, ast.In) and _is_whole_sequence(comparator) for op, comparator in zip(node.ops, node.comparators)
    )


def _is_comprehension_scan(node: ast.AST) -> bool:
    """``any(a in ("--help", "-h") for a in args)`` and its comprehension kin."""
    if not isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return False
    for generator in node.generators:
        if not _is_whole_sequence(generator.iter):
            continue
        tests = list(generator.ifs)
        if isinstance(node.elt, ast.Compare):
            tests.append(node.elt)
        if any(_is_free_help_test(test) for test in tests):
            return True
    return False


def _is_free_help_test(test: ast.AST) -> bool:
    """A help comparison on a loop variable rather than a pinned position."""
    if not isinstance(test, ast.Compare):
        return False
    return _compares_against_help(test) and _fixed_slot(test.left) is None


def _is_loop_scan(node: ast.AST) -> bool:
    """``for token in args: if token in ("--help", "-h")``."""
    if not isinstance(node, ast.For) or not _is_whole_sequence(node.iter):
        return False
    return any(
        isinstance(inner, ast.Compare) and isinstance(inner.left, ast.Name) and _compares_against_help(inner)
        for inner in ast.walk(node)
    )


def _scan_call_kind(node: ast.Call) -> Optional[str]:
    """Name the whole-list scan a call performs, or None."""
    name = _callee_name(node)
    if name == "parse_known_args":
        return "argparse parse_known_args"
    if any(verb in name.lower() for verb in _SCAN_VERBS):
        return f"{name}()"
    if name == "count" and any(_is_help_constant(a) for a in node.args):
        return "count()"
    return None


def has_whole_list_scan(func: ast.AST) -> Optional[str]:
    """Return a description of the whole-sequence help scan, or None."""
    for node in ast.walk(func):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare) and _is_membership_scan(node):
            return f"membership test at line {line}"
        if _is_comprehension_scan(node):
            return f"comprehension scan at line {line}"
        if _is_loop_scan(node):
            return f"loop scan at line {line}"
        if isinstance(node, ast.Call):
            kind = _scan_call_kind(node)
            if kind:
                return f"{kind} at line {line}"
    return None


def find_argument_consumption(func: ast.AST, sequences: Set[str]) -> List[Tuple[str, str, int]]:
    """Find places where the gated sequence is used as DATA, not as a dispatch key."""
    found: List[Tuple[str, str, int]] = []
    for node in ast.walk(func):
        line = getattr(node, "lineno", 0)
        for probe in _CONSUMPTION_PROBES:
            found.extend(probe(node, sequences, line))
    return found


def _subscript_use(node: ast.AST, sequences: Set[str], line: int) -> List[Tuple[str, str, int]]:
    """``args[1]``, ``args[i]`` or ``args[1:]`` -- an operand slot beyond the gate."""
    if not isinstance(node, ast.Subscript):
        return []
    if not isinstance(node.value, ast.Name) or node.value.id not in sequences:
        return []
    name, index = node.value.id, node.slice
    if isinstance(index, ast.Slice):
        return [("slice", f"{name}[:] slice", line)]
    if isinstance(index, ast.Constant):
        if isinstance(index.value, int) and index.value >= 1:
            return [("late-index", f"{name}[{index.value}]", line)]
        return []
    return [("dynamic-index", f"{name}[<var>]", line)]


def _binding_use(node: ast.AST, sequences: Set[str], line: int) -> List[Tuple[str, str, int]]:
    """``target = args[0]`` -- the slot accepts arbitrary text, so a flag can land in it."""
    if not isinstance(node, ast.Assign):
        return []
    value = node.value
    if not isinstance(value, ast.Subscript) or not isinstance(value.value, ast.Name):
        return []
    if value.value.id not in sequences:
        return []
    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
    return [("value-slot", targets[0] if targets else value.value.id, line)]


def _iteration_use(node: ast.AST, sequences: Set[str], line: int) -> List[Tuple[str, str, int]]:
    """``for token in args:`` -- the command reads an open-ended argument list."""
    if not isinstance(node, ast.For):
        return []
    if isinstance(node.iter, ast.Name) and node.iter.id in sequences:
        return [("iterate", f"for ... in {node.iter.id}", line)]
    return []


def _probe_use(node: ast.AST, sequences: Set[str], line: int) -> List[Tuple[str, str, int]]:
    """``"--verbose" in args`` -- the command already expects flags to trail the operands."""
    if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Constant):
        return []
    found: List[Tuple[str, str, int]] = []
    for op, comparator in zip(node.ops, node.comparators):
        if isinstance(op, ast.In) and isinstance(comparator, ast.Name) and comparator.id in sequences:
            found.append(("flag-probe", f"{node.left.value!r} in {comparator.id}", line))
    return found


def _call_use(node: ast.AST, sequences: Set[str], line: int) -> List[Tuple[str, str, int]]:
    """The argument list forwarded to something that acts on it."""
    if not isinstance(node, ast.Call):
        return []
    name = _callee_name(node)
    if name == "len" and any(isinstance(a, ast.Name) and a.id in sequences for a in node.args):
        return [("length", "len(args)", line)]
    if any(hint in name.lower() for hint in _SINK_HINTS):
        return []
    found: List[Tuple[str, str, int]] = []
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        if isinstance(arg, ast.Name) and arg.id in sequences:
            found.append(("forward", f"{name}({arg.id})", line))
            continue
        element_of = _element_source(arg, sequences)
        if element_of:
            found.append(("forward-element", f"{name}({element_of}[...])", line))
    return found


# Each probe self-guards on node type, so the dispatch loop stays flat. An
# if/elif chain here reads as depth-6 nesting to the deep_nesting standard,
# because `elif` is a nested If in the AST -- the checker in this very pack.
_CONSUMPTION_PROBES = (_subscript_use, _binding_use, _iteration_use, _probe_use, _call_use)


def _element_source(arg: ast.AST, sequences: Set[str]) -> Optional[str]:
    """The gated sequence a single-element read comes from, if any."""
    if not isinstance(arg, ast.Subscript) or not isinstance(arg.value, ast.Name):
        return None
    if arg.value.id not in sequences or isinstance(arg.slice, ast.Slice):
        return None
    return arg.value.id


def _literal_strings(node: ast.AST) -> List[str]:
    """Every string literal a comparator holds, bare or inside a collection."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _non_help_literals(node: ast.Compare) -> List[str]:
    """Subcommand words a Compare tests its left operand against, in source order.

    Help tokens are excluded; a mixed collection still counts, and source order is kept so
    the reported word is the one written first.
    """
    words: List[str] = []
    for op, comparator in zip(node.ops, node.comparators):
        if not isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            continue
        words.extend(value for value in _literal_strings(comparator) if value not in _HELP_TOKENS)
    return words


def _first_fixed_read(value: ast.AST, sequences: Set[str]) -> Optional[Tuple[str, int]]:
    """The fixed slot of a gated sequence read anywhere inside an expression."""
    for sub in ast.walk(value):
        slot = _fixed_slot(sub)
        if slot is not None and slot[0] in sequences:
            return slot
    return None


def slot_bound_names(func: ast.AST, sequences: Set[str]) -> Dict[str, Tuple[str, int]]:
    """Names carrying a fixed-position read of a gated sequence.

    ``subcommand = args[0] if args else "status"`` binds args[0] through an
    IfExp, which is not an Assign-from-Subscript and so is invisible to the
    value-slot probe.
    """
    bound: Dict[str, Tuple[str, int]] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        slot = _first_fixed_read(value, sequences)
        if slot is None:
            continue
        for target in targets:
            bound.update({sub.id: slot for sub in ast.walk(target) if isinstance(sub, ast.Name)})
    return bound


def find_positional_dispatch(func: ast.AST, sequences: Set[str]) -> Optional[Tuple[str, int, str, int]]:
    """Where the gated position is matched against a subcommand word."""
    bound = slot_bound_names(func, sequences)
    found: List[Tuple[str, int, str, int]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        slot = _fixed_slot(node.left)
        if slot is None or slot[0] not in sequences:
            slot = bound.get(node.left.id) if isinstance(node.left, ast.Name) else None
        if slot is None:
            continue
        words = _non_help_literals(node)
        if words:
            found.append((slot[0], slot[1], words[0], node.lineno))
    return min(found, key=lambda item: item[3]) if found else None


def _is_display_call(name: str) -> bool:
    """Whether a call name means "show text" rather than "do something"."""
    lowered = name.lower()
    return any(hint in lowered for hint in _SINK_HINTS + _DISPLAY_HINTS)


def find_work_call(func: ast.AST, after_line: int) -> Optional[Tuple[str, int]]:
    """The first call below *after_line* that DOES something."""
    found: List[Tuple[int, str]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        line = getattr(node, "lineno", 0)
        name = _callee_name(node)
        if line <= after_line or not name or name in _INERT_CALLS or _is_display_call(name):
            continue
        found.append((line, name))
    if not found:
        return None
    line, name = min(found)
    return (name, line)


# handle_command(command, args) -- the fleet-wide signature the router calls.
_COMMAND_PARAM_INDEX = 0
_ARGS_PARAM_INDEX = 1


def _positional_params(func: ast.AST) -> List[str]:
    """Names of a function's positional parameters, in declaration order."""
    spec = getattr(func, "args", None)
    if spec is None:
        return []
    return [arg.arg for arg in list(spec.posonlyargs) + list(spec.args)]


def find_command_dispatch(func: ast.AST, command_param: str) -> Optional[Tuple[str, int]]:
    """Where the command parameter is matched against a literal word."""
    found: List[Tuple[int, str]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == command_param):
            continue
        words = _non_help_literals(node)
        if words:
            found.append((node.lineno, words[0]))
    if not found:
        return None
    line, word = min(found)
    return (word, line)


def reads_sequence(closure: Sequence[ast.AST], name: str) -> bool:
    """Whether *name* is READ anywhere in the routing closure.

    Any read counts; every read is a Name load, so one predicate covers the lot.
    """
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for func in closure
        for node in ast.walk(func)
    )


def find_unread_args_violation(closure: Sequence[ast.AST]) -> Optional[Tuple[str, str, str, int, str, int]]:
    """A command dispatch that ignores its argument list and works anyway."""
    if not closure or getattr(closure[0], "name", "") != _ENTRY_FUNC:
        return None
    entry = closure[0]
    params = _positional_params(entry)
    if len(params) <= _ARGS_PARAM_INDEX:
        return None
    args_param = params[_ARGS_PARAM_INDEX]
    if reads_sequence(closure, args_param):
        return None
    dispatch = find_command_dispatch(entry, params[_COMMAND_PARAM_INDEX])
    if dispatch is None:
        return None
    word, dispatch_line = dispatch
    work = find_work_call(entry, dispatch_line)
    if work is None:
        return None
    call, call_line = work
    return (_ENTRY_FUNC, args_param, word, dispatch_line, call, call_line)


def routing_closure(tree: ast.Module) -> List[ast.AST]:
    """Return handle_command and the module-level helpers it routes through.

    Branches often keep ``handle_command`` as a one-line forwarder with the gate in
    ``_handle_x(args)``; following delegates finds gates and credits scans that hide there.
    """
    top_level = {
        node.name: node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    entry = top_level.get(_ENTRY_FUNC)
    if entry is None:
        return []

    closure: List[ast.AST] = [entry]
    seen = {_ENTRY_FUNC}
    frontier: List[ast.AST] = [entry]
    for _ in range(_MAX_DELEGATE_DEPTH):
        next_frontier: List[ast.AST] = []
        for func in frontier:
            for node in ast.walk(func):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                name = node.func.id
                if name in seen or name not in top_level:
                    continue
                if not (name.startswith("_") or name.startswith("handle")):
                    continue
                seen.add(name)
                closure.append(top_level[name])
                next_frontier.append(top_level[name])
        frontier = next_frontier
        if not frontier:
            break
    return closure


def router_normalises(apps_dir: Path) -> Optional[str]:
    """Whether this branch's entry point scans the whole remaining argument list."""
    if not apps_dir.is_dir():
        return None
    for entry_point in sorted(apps_dir.glob("*.py")):
        if entry_point.name == "__init__.py":
            continue
        try:
            tree = ast.parse(entry_point.read_text(encoding="utf-8"), filename=str(entry_point))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            logger.info("[help_flag_safety] Cannot read router %s: %s", entry_point, exc)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in _ROUTER_FUNCS:
                continue
            scan = has_whole_list_scan(node)
            if scan:
                return f"{entry_point.name}:{node.name}() {scan}"
    return None


def _walk_all(nodes: Sequence[ast.AST]) -> Iterator[ast.AST]:
    """Walk every node of every statement in *nodes*."""
    for node in nodes:
        yield from ast.walk(node)


def _is_main_guard(node: ast.If) -> bool:
    """Whether *node* is ``if __name__ == "__main__":``."""
    if not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    if not (isinstance(test.left, ast.Name) and test.left.id == "__name__"):
        return False
    return any(
        isinstance(op, ast.Eq) and isinstance(cmp_, ast.Constant) and cmp_.value == "__main__"
        for op, cmp_ in zip(test.ops, test.comparators)
    )


def standalone_scope(tree: ast.Module) -> List[ast.stmt]:
    """Return every statement reachable from ``if __name__ == "__main__":``.

    ``handle_command`` is deliberately not followed: its gate is the thing being judged,
    so crediting it here would let a module vouch for itself.
    """
    guards = [node for node in ast.iter_child_nodes(tree) if isinstance(node, ast.If) and _is_main_guard(node)]
    if not guards:
        return []
    guard = guards[0]
    top_level = {
        node.name: node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    scope: List[ast.stmt] = list(guard.body)
    seen: Set[str] = {_ENTRY_FUNC}
    frontier: List[ast.stmt] = list(guard.body)
    for _ in range(_MAX_DELEGATE_DEPTH):
        following: List[ast.stmt] = []
        for node in _walk_all(frontier):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name in seen or name not in top_level:
                continue
            seen.add(name)
            following.extend(top_level[name].body)
        if not following:
            break
        scope.extend(following)
        frontier = following
    return scope


def _reads_argv(node: ast.AST) -> bool:
    """Whether an expression draws from the command line."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "argv":
            return True
        if isinstance(sub, ast.Call) and _callee_name(sub) in _ARGPARSE_PARSE and not sub.args:
            return True
    return False


def _names_used(node: ast.AST) -> Set[str]:
    """Every plain name read anywhere inside an expression."""
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


def _assignments(scope: Sequence[ast.stmt]) -> Iterator[Tuple[List[ast.expr], ast.expr]]:
    """Yield (targets, value) for every assignment in *scope* that has a value."""
    for node in _walk_all(scope):
        if isinstance(node, ast.Assign):
            yield (list(node.targets), node.value)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            yield ([node.target], node.value)


def argv_tainted_names(scope: Sequence[ast.stmt]) -> Set[str]:
    """Names on the standalone path that carry command-line text.

    ``args = sys.argv[1:]``, ``rest = [a for a in sys.argv[1:] if ...]`` and
    ``parsed, extra = parser.parse_known_args()`` all bind argv. Chains are
    followed to a fixpoint so a value renamed twice is still recognised.
    """
    tainted: Set[str] = set()
    for _ in range(_MAX_DELEGATE_DEPTH):
        before = len(tainted)
        for targets, value in _assignments(scope):
            if not (_reads_argv(value) or (_names_used(value) & tainted)):
                continue
            for target in targets:
                tainted.update(sub.id for sub in ast.walk(target) if isinstance(sub, ast.Name))
        if len(tainted) == before:
            break
    return tainted


def routes_raw_argv(scope: Sequence[ast.stmt], tainted: Set[str]) -> Optional[int]:
    """Line of the standalone ``handle_command`` call carrying argv, if any.

    A call passing a literal list -- ``handle_command(cmd, ["--help"])`` -- is
    normalised, not raw, and is not reported.
    """
    for node in _walk_all(scope):
        if not isinstance(node, ast.Call) or _callee_name(node) != _ENTRY_FUNC:
            continue
        passed = list(node.args) + [kw.value for kw in node.keywords]
        if any(_reads_argv(arg) or (_names_used(arg) & tainted) for arg in passed):
            return node.lineno
    return None


def _help_constants(node: ast.AST) -> Set[str]:
    """Every help token literal appearing inside a node."""
    return {str(sub.value) for sub in ast.walk(node) if isinstance(sub, ast.Constant) and _is_help_constant(sub)}


def _scan_tokens(node: ast.AST) -> Set[str]:
    """Help tokens a single whole-sequence scan actually tests for."""
    if isinstance(node, ast.Compare) and _is_membership_scan(node):
        return _help_constants(node.left)
    if _is_comprehension_scan(node) or _is_loop_scan(node):
        return _help_constants(node)
    if isinstance(node, ast.Call):
        return _scan_call_tokens(node)
    return set()


def _scan_call_tokens(node: ast.Call) -> Set[str]:
    """Help tokens a scanning CALL covers. argparse is scored separately."""
    name = _callee_name(node)
    if name in _ARGPARSE_PARSE or not _scan_call_kind(node):
        return set()
    if name == "count":
        return _help_constants(node)
    # A named predicate -- wants_help(argv) -- answers the whole question.
    return set(_DASHED_HELP_TOKENS)


def _argparse_tokens(scope: Sequence[ast.stmt]) -> Set[str]:
    """Help tokens argparse screens on the standalone path.

    A default parser absorbs both dashed forms. ``add_help=False`` turns that
    off, leaving only whatever ``add_argument`` declares.
    """
    nodes = [node for node in _walk_all(scope) if isinstance(node, ast.Call)]
    if not any(_callee_name(node) in _ARGPARSE_PARSE for node in nodes):
        return set()
    disabled = any(
        kw.arg == "add_help" and isinstance(kw.value, ast.Constant) and kw.value.value is False
        for node in nodes
        for kw in node.keywords
    )
    tokens: Set[str] = set() if disabled else set(_DASHED_HELP_TOKENS)
    for node in nodes:
        if _callee_name(node) == "add_argument":
            # Positional args only: the help= text is prose, not a flag name.
            tokens |= {str(a.value) for a in node.args if isinstance(a, ast.Constant) and _is_help_constant(a)}
    return tokens


def screened_help_tokens(scope: Sequence[ast.stmt]) -> Set[str]:
    """Help tokens the standalone path itself catches anywhere on the line."""
    tokens: Set[str] = _argparse_tokens(scope)
    for node in _walk_all(scope):
        tokens |= _scan_tokens(node)
    return tokens


def standalone_bypasses_router(tree: ast.Module) -> Optional[str]:
    """Whether ``python apps/modules/thing.py ...`` reaches the gate unscreened.

    Returns a description of the unrouted path, or None if there is none.
    """
    scope = standalone_scope(tree)
    if not scope:
        return None
    line = routes_raw_argv(scope, argv_tainted_names(scope))
    if line is None:
        return None
    missing = sorted(_DASHED_HELP_TOKENS - screened_help_tokens(scope))
    if not missing:
        return None
    return (
        f"__main__ hands raw sys.argv to {_ENTRY_FUNC}() at line {line} without screening "
        f"{' or '.join(missing)}, so `python <this module> <arg> --help` never reaches the router"
    )


def _result(passed: bool, name: str, message: str, score: int) -> Dict:
    """Build the standard single-check result payload."""
    return {
        "passed": passed,
        "checks": [{"name": name, "passed": passed, "message": message}],
        "score": score,
        "standard": STANDARD,
    }


def _skip(message: str) -> Dict:
    """A file this standard judged and found nothing to convict."""
    return _result(True, "Help-flag safety", message, 100)


def _decline(message: str) -> Dict:
    """A file this standard does not judge: out of the row's average."""
    result = _skip(message)
    result["checks"][0]["declined"] = True
    return result


def _describe_consumption(consumption: Sequence[Tuple[str, str, int]], gate_line: int) -> str:
    """Describe where a stray flag lands, naming a value slot when there is one.

    Sites below the gate are preferred: naming a call above it reads as though the gate
    were unreachable, which is a different bug.
    """
    below = [c for c in consumption if c[2] > gate_line] or list(consumption)
    value_slots = [c for c in below if c[0] == "value-slot"]
    if value_slots:
        _, detail, lineno = value_slots[0]
        return f"the flag lands in the '{detail}' value slot (line {lineno})"
    _, detail, lineno = below[0]
    return f"remaining arguments reach '{detail}' (line {lineno})"


def _describe_execution(func: ast.AST, sequences: Set[str], gate_line: int) -> Optional[str]:
    """Describe the subcommand word that hides the flag and the call that then runs.

    Nothing binds, slices or forwards the tail, but the gated position holds a word the user
    must type, and something past the gate still executes.
    """
    dispatch = find_positional_dispatch(func, sequences)
    if dispatch is None:
        return None
    sequence, index, word, dispatch_line = dispatch
    work = find_work_call(func, gate_line)
    if work is None:
        return None
    call, call_line = work
    return (
        f"the subcommand word '{word}' occupies {sequence}[{index}] (line {dispatch_line}), "
        f"the flag goes unread at {sequence}[{index + 1}:], {call}() is reached (line {call_line})"
    )


def _describe_unread_args(violation: Tuple[str, str, str, int, str, int]) -> str:
    """Describe a command dispatch that never looks at its argument list."""
    func_name, args_param, word, dispatch_line, call, call_line = violation
    return (
        f"{func_name}() dispatches on the command word '{word}' (line {dispatch_line}) and never reads "
        f"'{args_param}' anywhere in its routing closure -- no position is gated because no position is "
        f"read, so a help flag after the command word is discarded, {call}() is reached (line {call_line}) "
        "and the command EXECUTES instead of explaining itself. A normalising router cannot help here: it "
        f"rewrites '{args_param}', and '{args_param}' is exactly what this module ignores."
    )


def _find_violation(closure: Sequence[ast.AST]) -> Optional[Tuple[str, Tuple[str, int, int], str]]:
    """The first routing function whose positional gate leaves a doing-path open."""
    for func in closure:
        gates = find_fixed_gates(func)
        if not gates:
            continue
        name = getattr(func, "name", "?")
        sequences = {gate[0] for gate in gates}
        gate_line = gates[0][2]
        consumption = find_argument_consumption(func, sequences)
        if consumption:
            return (name, gates[0], _describe_consumption(consumption, gate_line))
        execution = _describe_execution(func, sequences, gate_line)
        if execution:
            return (name, gates[0], execution)
    return None


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that a routing module treats a help flag anywhere as a help request"""
    path = Path(module_path)
    posix_path = path.as_posix()

    if is_bypassed(posix_path, _STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, "Bypassed", "Standard bypassed via .seedgo/bypass.json", 100)

    if not path.exists():
        return _result(False, "File exists", f"File not found: {module_path}", 0)

    # Only apps/modules/*.py is scored. Entry points are READ (see
    # router_normalises) but never blamed: in AIPass the router is allowed to
    # delegate help handling to the modules below it.
    if path.name == "__init__.py" or path.parent.name != "modules" or path.parent.parent.name != "apps":
        return _decline("Not a routing module (apps/modules/*.py) -- not applicable")

    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[help_flag_safety] Cannot read %s: %s", path, exc)
        return _result(False, "File readable", f"Error reading file: {exc}", 0)

    if not source.strip():
        return _decline("Empty file skipped")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.info("[help_flag_safety] Skipped %s: SyntaxError during parse", path)
        return _result(False, "File parseable", f"Syntax error: {exc}", 0)

    closure = routing_closure(tree)
    if not closure:
        return _decline("No handle_command() routing function -- not applicable")

    for func in closure:
        scan = has_whole_list_scan(func)
        if scan:
            name = getattr(func, "name", "?")
            json_handler.log_operation("check_completed", {"file": posix_path, "score": 100, "standard": _STANDARD_KEY})
            return _skip(f"{name}() scans the whole argument list -- {scan}")

    violation = _find_violation(closure)
    if violation is None:
        # No gate anywhere -- so there is no gate for the router exemption below
        # to protect, and it is deliberately not consulted for this arm: a module
        # that never reads its arguments cannot be saved by rewriting them.
        unread = find_unread_args_violation(closure)
        if unread is not None:
            json_handler.log_operation("check_completed", {"file": posix_path, "score": 0, "standard": _STANDARD_KEY})
            return _result(False, "Help-flag safety", _describe_unread_args(unread), 0)
        json_handler.log_operation("check_completed", {"file": posix_path, "score": 100, "standard": _STANDARD_KEY})
        return _skip(
            "No fixed-position help gate guarding an argument-consuming or executing path, "
            "and no command dispatch that ignores its arguments"
        )

    # The router only protects a module the router is the only way into. A
    # __main__ block that dispatches raw argv is a second door past it.
    protection = router_normalises(path.parent.parent)
    bypass = standalone_bypasses_router(tree) if protection else None
    if protection and bypass is None:
        json_handler.log_operation("check_completed", {"file": posix_path, "score": 100, "standard": _STANDARD_KEY})
        return _skip(f"Positional gate, but the branch router normalises first -- {protection}")

    func_name, gate, where = violation
    sequence, index, gate_line = gate
    unrouted = f" The branch router normalises, but {bypass}." if bypass else ""
    json_handler.log_operation("check_completed", {"file": posix_path, "score": 0, "standard": _STANDARD_KEY})
    return _result(
        False,
        "Help-flag safety",
        (
            f"{func_name}() gates help at {sequence}[{index}] only (line {gate_line}) and no layer scans the "
            f"rest -- a help flag after the first argument is not seen, so {where} and the command EXECUTES "
            f"instead of explaining itself.{unrouted}"
        ),
        0,
    )
