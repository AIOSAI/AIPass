# =================== AIPass ====================
# Name: help_flag_safety_check.py
# Description: Help-Flag Safety Standards Checker Handler
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""
Help-Flag Safety Standards Checker Handler

THE RULE: a help flag ANYWHERE in the arguments means EXPLAIN, never EXECUTE.

Why this standard exists:
    Every branch probed on 2026-08-13 read help flags at ONE fixed position --
    almost always ``args[0]``. A flag any later in the line was discarded and
    the subcommand ran instead. ``drone @memory rollover push --help``
    performed the fleet-wide ``per_branch`` reset it was being asked to
    describe. One morning of that shape cost a 17-branch config reset, a real
    backup run, a real data cleanup and an enrollment write, and came within a
    keystroke of an external publish. A question must never execute.

WHAT IS FLAGGED (shape (a), the module gate):
    A routing function in ``apps/modules/*.py`` that
      1. gates help at a FIXED POSITION (``args[0] in ("--help", ...)``), and
      2. never scans the whole argument sequence, and
      3. leaves a stray flag somewhere to hide, EITHER by
           3a. CONSUMING arguments as data -- binding, slicing, iterating,
               probing or forwarding them (see find_argument_consumption), OR
           3b. matching the gated position against a SUBCOMMAND WORD and then
               still reaching a call that DOES something (see
               find_positional_dispatch / find_work_call) -- and
      4. is not already protected by its branch's entry-point router.

WHAT IS ALSO FLAGGED (shape (e), no gate at all):
    ``handle_command`` that
      1. dispatches on the ``command`` parameter against a literal word, and
      2. never READS its ``args`` parameter anywhere in the routing closure --
         no subscript, membership test, iteration, len(), forward or
         truthiness test, and
      3. still reaches a work call (see find_unread_args_violation).

    The verb is in the COMMAND slot, so ``drone @branch demo --help`` arrives as
    command="demo", args=["--help"] and the flag is discarded unread. Reported
    by @cli on 2026-08-13. The router exemption does NOT apply: a normalising
    router protects a module by REWRITING its arguments, and this module ignores
    them. Fleet population when the arm was written: 0 of 152 modules.

    3b was added on 2026-08-13 after the value-slot cut proved a systematic
    false negative: @flow's run named 5 modules where a grep found 8, @hooks'
    named 2 where a grep found 9, and one miss was ``sessions reclaim --help``
    stopping live sessions. seedgo's own inbox_audit.py scored 100 while
    ``audit inbox-ids --help`` rglob'd every inbox in the repo -- args[0] there
    is only ever COMPARED, so every consumption probe came back empty. The harm
    is not that the tail becomes data; the harm is that a work call runs.

WHY A SUBCOMMAND WORD IS THE DISCRIMINATOR:
    The router splits ``drone @branch <command> <rest...>``, so a module's
    ``args`` begins at the SECOND word the user typed. If the module dispatches
    on ``command``, then ``args[0]`` is the first thing after it and a
    positional gate genuinely catches ``<command> --help``. If the module
    instead matches ``args[0]`` against a word of its own vocabulary, the user
    must type that word, which pushes any flag to ``args[1]`` -- a position
    nothing in the module reads. That is the whole difference between
    ``drone @cli display demo --help`` (runs the demo) and
    ``drone @daemon update --help`` (explains itself).

WHAT MAKES A MODULE PASS (any one is enough):
    a) whole-sequence scan: ``"--help" in args``
    b) comprehension scan:  ``any(a in ("--help", "-h") for a in args)``
    c) loop scan:           ``for token in args: if token in ("--help", ...)``
    d) helper call:         ``wants_help(args)``
    e) argparse:            ``parse_known_args`` absorbs the flag anywhere
    f) the branch router normalises before the module is ever reached AND the
       module has no standalone ``__main__`` door that hands raw ``sys.argv``
       to ``handle_command`` (see STANDALONE REACHABILITY below)

Shape (b) -- a router that intercepts ``remaining[0]`` only -- is detected, but
as the PRECONDITION above rather than as its own violation. In AIPass a router
may legitimately delegate help handling downstream (that is exactly how
@memory was fixed: the router still reads ``remaining_args[0]``, the modules
scan the whole list), so a positional-only router is a defect only when the
module below it is positional-only too -- and that module is what gets named.

Shape (c) -- a help flag consumed as an ACTION or BRANCH value -- is reported
only where it CO-OCCURS with shape (a), naming the value slot the flag lands
in. It is deliberately NOT detected on its own: "this function has no help
gate at all" is indistinguishable from "this function is not a CLI surface"
without heuristics that would flood the fleet with false positives. Shape (e)
above is the single exception, and it is an exception for one reason: the
function is ``handle_command``, which is a CLI surface by definition in AIPass,
so the surface does not have to be guessed at. For every other function the
limit stands.

One check per file: passed, or failed naming the function, the gate and the
slot the flag would land in.
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


# =============================================================================
# AST PREDICATES
# =============================================================================


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


# =============================================================================
# DETECTION -- the three questions asked of every routing function
# =============================================================================


def find_fixed_gates(func: ast.AST) -> List[Tuple[str, int, int]]:
    """Find help gates pinned to one argument position.

    Args:
        func: Function node to inspect

    Returns:
        List of (sequence_name, index, lineno)
    """
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
    """Return a description of the whole-sequence help scan, or None.

    Every accepted form answers the question "is a help flag ANYWHERE in
    this list?" -- which is the only question that makes the command safe.

    Args:
        func: Function node to inspect

    Returns:
        Human-readable description of the scan, or None if there is none
    """
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
    """Find places where the gated sequence is used as DATA, not as a dispatch key.

    This is the precision cut. A command whose vocabulary is closed -- one that
    only ever compares ``args[0]`` against literal subcommand names -- has
    nowhere for a stray flag to hide, so a positional gate is sufficient for
    it. A command that binds an argument to a value, reads a later position,
    slices, iterates or forwards the list DOES have somewhere to hide, and a
    trailing flag reaches an executing path.

    Args:
        func: Function node to inspect
        sequences: Names of the argument sequences the help gate reads

    Returns:
        List of (kind, detail, lineno)
    """
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


# =============================================================================
# POSITIONAL SUBCOMMAND -- the gated slot is a WORD the user has to type
# =============================================================================
#
# Value-slot consumption is not the only harm. The harm is that a work call
# EXECUTES at all. seedgo's own inbox_audit.py proved it: `audit inbox-ids
# --help` gates on args[0], finds "inbox-ids" there, and runs a repo-wide
# rglob -- yet args[0] is only ever COMPARED, never bound, sliced, iterated or
# forwarded, so every consumption probe came back empty and the file scored 100.
#
# What makes that dangerous, and `drone @x start --help` safe, is whether the
# gated position holds a SUBCOMMAND WORD. If args[0] is matched against a
# non-help literal on the way to work, the user must type that word, which
# pushes any help flag to args[1] -- a position nothing in the module reads. If
# the module dispatches on `command` instead, args[0] IS the first thing typed
# and the gate catches it.


def _literal_strings(node: ast.AST) -> List[str]:
    """Every string literal a comparator holds, bare or inside a collection."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _non_help_literals(node: ast.Compare) -> List[str]:
    """Subcommand words a Compare tests its left operand against, in source order.

    Help tokens are excluded: a gate is a gate, not a dispatch. A collection
    that mixes the two -- ``args[0] in ("scan", "--help")`` -- still counts,
    because "scan" is a word the user can type ahead of the flag. Source order
    is kept so the reported word is the one written first, not the one that
    happens to sort first.
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
    value-slot probe -- that is exactly how @flow's registry_monitor hid.

    Args:
        func: Function node to inspect
        sequences: Names of the argument sequences the help gate reads

    Returns:
        Mapping of local name -> (sequence_name, index) it was bound from
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
    """Where the gated position is matched against a subcommand word.

    Args:
        func: Function node to inspect
        sequences: Names of the argument sequences the help gate reads

    Returns:
        (sequence_name, index, subcommand_word, lineno) for the earliest such
        match, or None if the module never dispatches on a gated position
    """
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
    """The first call below *after_line* that DOES something.

    Display sinks and inert value-builders are excluded -- reaching
    ``print_help()`` or ``len(args)`` past a gate is not "the command ran".
    What is left is a doing-path: the thing the user asked about instead of
    being told about.

    Args:
        func: Function node to inspect
        after_line: Only calls strictly below this line count

    Returns:
        (callee_name, lineno), or None if nothing past the gate executes
    """
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


# =============================================================================
# UNREAD ARGUMENTS -- the verb is in the COMMAND slot and args is never read
# =============================================================================
#
# Both arms above need a fixed-position gate to EXIST before anything fires.
# @cli reported the shape where there is none at all:
#
#     def handle_command(command, args):
#         if command == "demo":
#             run_demo()
#             return True
#         return False
#
# `drone @cli demo --help` arrives as command="demo", args=["--help"]. The verb
# is in the COMMAND slot, so nothing is left for a positional gate to read --
# and `args` is not read at the wrong index, it is never read at all. The router
# did its job here: it rewrote `remaining` to ["--help"] and delegated. The
# module threw the flag away and ran the demo.
#
# This is the one place where "no help gate at all" IS detectable without
# flooding the fleet, and it is detectable for one reason only: the function is
# `handle_command`, which is definitionally a CLI surface in AIPass. The honest
# limit stated elsewhere in this pack -- that "this function has no help gate"
# is indistinguishable from "this function is not a CLI surface" -- is untouched
# for every other function. Here the surface is known by name.
#
# The router exemption deliberately does NOT apply to this arm. A normalising
# router protects a module by REWRITING its arguments to ["--help"]; a module
# that never reads its arguments cannot benefit from a rewrite, so the flag is
# discarded exactly as it was before. Fleet population of this shape when the
# arm was written: 0 of 152 modules (measured by @cli, who fixed theirs first).

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
    """Where the command parameter is matched against a literal word.

    Args:
        func: Function node to inspect
        command_param: Name of the parameter holding the command word

    Returns:
        (subcommand_word, lineno) for the earliest such match, or None
    """
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

    Any read counts -- subscript, membership test, iteration, len(), a forward
    to another call, a bare truthiness test. All of them are Name loads, so one
    predicate covers the lot, and a module that touches its arguments at all is
    judged by the gate arms instead of by this one.

    Args:
        closure: handle_command and the helpers it routes through
        name: Parameter name to look for

    Returns:
        True if the name is loaded anywhere in the closure
    """
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for func in closure
        for node in ast.walk(func)
    )


def find_unread_args_violation(closure: Sequence[ast.AST]) -> Optional[Tuple[str, str, str, int, str, int]]:
    """A command dispatch that ignores its argument list and works anyway.

    Args:
        closure: handle_command and the helpers it routes through

    Returns:
        (function_name, args_param, subcommand_word, dispatch_line, call, call_line),
        or None when any of the four conditions is absent
    """
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


# =============================================================================
# ROUTING CLOSURE -- handle_command plus the private helpers it delegates to
# =============================================================================


def routing_closure(tree: ast.Module) -> List[ast.AST]:
    """Return handle_command and the module-level helpers it routes through.

    Several branches keep ``handle_command`` as a one-line forwarder and put
    the gate in ``_handle_x(args)``. Following those delegates keeps the
    checker honest in both directions: it finds gates that hide one call
    deep, and it credits scans that hide there too.

    Args:
        tree: Parsed module

    Returns:
        List of function nodes forming the module's routing surface
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


# =============================================================================
# CHAIN -- does the branch router normalise before the module is reached?
# =============================================================================


def router_normalises(apps_dir: Path) -> Optional[str]:
    """Whether this branch's entry point scans the whole remaining argument list.

    A router that finds a help flag anywhere and rewrites the arguments to
    ``["--help"]`` before delegating protects every module behind it -- that is
    how @backup, @aipass and @daemon were fixed, and a standard that failed
    its own reference implementations would be wrong.

    Args:
        apps_dir: The branch's apps/ directory

    Returns:
        Description of the protecting scan, or None if the router leaves the
        argument list untouched
    """
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


# =============================================================================
# STANDALONE REACHABILITY -- the second door into handle_command
# =============================================================================
#
# The router exemption assumed a module is only ever reached THROUGH the
# router. It is not. Nearly every module also carries
#
#     if __name__ == "__main__":
#         handle_command(PRIMARY_COMMAND, sys.argv[1:])
#
# which hands raw argv straight to the gate and never touches the router.
# @api proved it live: `python apps/modules/api_key.py get-key openrouter
# --help` still reached the retrieval path with their router already
# normalised. So the exemption may only stand for a module that is NOT
# independently reachable with raw arguments.
#
# A `__main__` block that screens the command line itself keeps the exemption
# -- but it must screen BOTH dashed spellings. A screen for "--help" alone
# still lets `-h` through to the positional gate, which is the same hole in a
# different place.


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

    The block itself plus the bodies of the module-level functions it calls
    (``main()`` most often), depth-limited. ``handle_command`` is deliberately
    NOT followed: its gate is the thing being judged, so crediting it here
    would let a module vouch for itself.

    Args:
        tree: Parsed module

    Returns:
        Statements forming the standalone execution path, empty if there is none
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

    Args:
        scope: Statements of the standalone execution path

    Returns:
        Set of tainted local names
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

    Args:
        scope: Statements of the standalone execution path
        tainted: Names carrying command-line text

    Returns:
        Line number of the offending call, or None
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
    off, leaving only whatever ``add_argument`` declares -- which is how
    @prax's monitor let ``-h`` through to the module gate.
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
    """Help tokens the standalone path itself catches anywhere on the line.

    Args:
        scope: Statements of the standalone execution path

    Returns:
        Set of tokens screened before handle_command is reached
    """
    tokens: Set[str] = _argparse_tokens(scope)
    for node in _walk_all(scope):
        tokens |= _scan_tokens(node)
    return tokens


def standalone_bypasses_router(tree: ast.Module) -> Optional[str]:
    """Whether ``python apps/modules/thing.py ...`` reaches the gate unscreened.

    Args:
        tree: Parsed module

    Returns:
        Description of the unrouted path, or None if there is none
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


# =============================================================================
# RESULT HELPERS
# =============================================================================


def _result(passed: bool, name: str, message: str, score: int) -> Dict:
    """Build the standard single-check result payload."""
    return {
        "passed": passed,
        "checks": [{"name": name, "passed": passed, "message": message}],
        "score": score,
        "standard": STANDARD,
    }


def _skip(message: str) -> Dict:
    """A file this standard has nothing to say about."""
    return _result(True, "Help-flag safety", message, 100)


def _describe_consumption(consumption: Sequence[Tuple[str, str, int]], gate_line: int) -> str:
    """Describe where a stray flag lands, naming a value slot when there is one.

    Sites BELOW the gate are preferred. A routing function often carries
    several independent command paths, and naming a call that sits above the
    gate reads as though the gate were unreachable, which is a different bug
    from the one being reported.
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

    The second harm, and the one the consumption probes could not see: nothing
    binds, slices or forwards the tail, but the gated position still holds a
    word the user must type, and something past the gate still executes.
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
    """The first routing function whose positional gate leaves a doing-path open.

    Args:
        closure: handle_command and the helpers it routes through

    Returns:
        (function_name, gate, harm_description), or None if every gated
        function is closed-vocabulary and inert past its gate
    """
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


# =============================================================================
# ENTRY POINT
# =============================================================================


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that a routing module treats a help flag anywhere as a help request

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip specific violations

    Returns:
        dict: {
            'passed': bool,           # Overall pass/fail
            'checks': [               # Individual check results
                {
                    'name': str,      # Check name
                    'passed': bool,   # Pass/fail
                    'message': str,   # Details
                }
            ],
            'score': int,             # 0-100 percentage
            'standard': str           # Standard name
        }
    """
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
        return _skip("Not a routing module (apps/modules/*.py) -- not applicable")

    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[help_flag_safety] Cannot read %s: %s", path, exc)
        return _result(False, "File readable", f"Error reading file: {exc}", 0)

    if not source.strip():
        return _skip("Empty file skipped")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.info("[help_flag_safety] Skipped %s: SyntaxError during parse", path)
        return _result(False, "File parseable", f"Syntax error: {exc}", 0)

    closure = routing_closure(tree)
    if not closure:
        return _skip("No handle_command() routing function -- not applicable")

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
