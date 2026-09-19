# =================== AIPass ====================
# Name: rich_markup_check.py
# Description: Rich Markup Standards Checker Handler
# Version: 2.0.0
# Created: 2026-08-11
# Modified: 2026-09-15
# =============================================

"""
Rich Markup Standards Checker Handler

Detects two render-time losses in console output: placeholders Rich SILENTLY
deletes, and style tags ``markup=False`` prints as raw text.

THE DEFECT:
Rich reads ``[word]`` in a printed string as a style tag. When the tag is not
a real Rich style, Rich removes it from the rendered output and says nothing --
no error, no gap, no marker. The source string is correct, so every
source-reading audit passes at 100% while the user sees mutilated output::

    console.print("drone @hooks <command> [args...]")   ->  "drone @hooks <command> "
    console.print("monitor run [branches]")             ->  "monitor run "
    console.print("[branch] row")                       ->  " row"

An entire attribution column has been lost this way, invisibly.

THE RULE THIS ENFORCES -- ESCAPE THE DATA, DO NOT DISARM THE LINE
(``src/aipass/cli/docs/rich_markup.md``, adopted 2026-09-15):

  - ``rich.markup.escape()`` is per-value and COMPOSES: a styled label beside a
    literal placeholder both come out right, and it is the only spelling that
    can be applied to a value that arrives at runtime.
  - ``markup=False`` is per-call and ABSOLUTE. It is correct for exactly one
    case -- a block of pre-formatted text carrying no styling, printed verbatim.
    Used on a styled line it does not merely fail to help: it PRINTS THE TAGS.
    That is the second family this file reports.
  - A hand-written ``\\[`` is what ``escape()`` emits and it does work while the
    parser is on. It is not credited as the cure: the message prescribes
    ``escape()``, and under ``markup=False`` the backslash itself reaches the
    terminal, which is reported.

THE ORACLE:
The checker never guesses which brackets Rich will eat. It reuses Rich's own
machinery so it cannot drift from Rich's real behaviour:

1. ``rich.markup.RE_TAGS`` -- the exact regex Rich uses to find tags. This is
   what makes ``[1,2,3]``, ``[42, 78]``, ``L[42]``, ``[]`` and ``[ spaced ]``
   mechanically safe rather than special-cased: Rich's own regex does not
   match them, so they reach the terminal untouched.
2. ``rich.style.Style.parse()`` on the style string Rich itself would build
   (``rich.markup.Tag`` partitions on ``=``). Parses -> real style, the author
   meant it. Raises ``StyleSyntaxError`` -> literal text, silently eaten.

Closing tags are excluded: a mismatched ``[/usr/bin]`` raises MarkupError,
which is loud and already caught by tests. This standard is only about the
silent losses.

FOLLOWING A LITERAL TO ITS PRINT SITE -- ONE HOP, ONE FILE
v1 read the PRINT SITE only. drone's per-verb git help page therefore scored
100 while eating its own placeholders: the page is a literal RETURNED by
``get_help()`` and printed by ``print_help()``, so the print site carried no
literal at all to read. @trigger hit the same gap in its second variant. Two
shapes are now followed, both inside ONE file and both ONE hop:

  - a module-level constant assigned exactly one string literal, printed by
    name -- ``console.print(BANNER)``;
  - a module-level function whose ``return`` statements carry literals, called
    at the print site -- ``console.print(get_help())``.

Concatenation (``+``) is read through at both levels, because a help page is
usually a run of adjacent literals with one call spliced into it.

WHAT THIS RULE DELIBERATELY DOES NOT CLAIM, all of it toward FEWER flags:

  - IT DOES NOT CROSS THE FILE BOUNDARY. A literal assembled in module A and
    printed in module B is invisible. Following imports would need a
    whole-branch call graph, and the resolution guesses (re-exports, adapters,
    ``getattr`` dispatch) are exactly where false positives breed. drone's real
    cross-module help path ``get_module_help -> drone.py`` is a miss here, by
    choice, and is stated rather than guessed at.
  - IT DOES NOT CHAIN HOPS. A followed function that returns another local
    call -- ``return HEAD + _door_help() + TAIL`` -- has HEAD and TAIL read and
    ``_door_help()`` left alone. One hop, like the pack's other resolvers.
  - IT DOES NOT READ FLOW. A local variable inside a function, an ``append``
    loop, ``"".join(parts)``, ``%`` formatting, a dict or list of literals
    indexed at the print site: none are followed. Each needs intra-procedural
    flow analysis to say WHICH literal arrives, and a rule that guesses that
    would nominate lines nobody can act on.
  - A NAME BOUND TWICE IS NOT FOLLOWED. If a module-level constant or function
    name is rebound anywhere in the file, the binding at the print site is not
    provable and the name is dropped.
  - ``markup=`` PASSED A NON-CONSTANT is not read at all: the call is skipped
    in both families, because whether the parser runs is unknown.
  - A HAND-ESCAPED LITERAL AT A NORMAL PRINT SITE IS NOT FLAGGED. ``\\[count]``
    really does reach the terminal intact; a scored, gating standard does not
    fail working code over a source-spelling preference. The message stops
    prescribing it -- that is the whole of the demotion.
  - THE ``markup=False`` FAMILY CANNOT READ INTENT. A pre-formatted block that
    happens to contain a token Rich would have parsed as a real style
    (``[dim]`` quoted inside documentation, say) is reported. It nominates. A
    human decides.
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple

from rich.errors import StyleSyntaxError
from rich.markup import RE_TAGS, Tag, escape
from rich.style import Style

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: every .py file (any file can print to a console)
AUDIT_SCOPE = "all_files"

# Production only: a test file renders nothing a user reads, and tests
# legitimately build broken markup as fixtures -- this very standard's suite
# does exactly that.
APPLIES_TO = "production"

# How many eaten tokens to name before the message says "and N more"
MAX_LISTED = 5

# A literal string reaches Rich's markup parser when it is printed by a Rich
# console. ``obj.print(...)`` is that call in every shape it takes
# (``console.print``, ``self.console.print``, ``rich.print``). A BARE
# ``print(...)`` is stdlib and renders NO markup -- flagging it would be a
# false positive on the exact string families this standard must not touch --
# so a bare name only counts when the module bound it from Rich itself.
_RICH_PRINT_SOURCES = ("rich", "rich.console")

#: The two families, kept apart so each carries its own cure in the message.
EATEN = "eaten"
DISARMED = "disarmed"


class Finding(NamedTuple):
    """One reported token.

    Attributes:
        kind: ``EATEN`` or ``DISARMED``.
        tag: The token as the author typed it, e.g. ``[args...]``.
        line: The line the literal sits on -- where the token lives.
        print_line: The line of the ``print`` that renders it. Equal to
            ``line`` for a literal written at the print site; different when
            the literal was followed from a constant or a return.
    """

    kind: str
    tag: str
    line: int
    print_line: int


def _rich_print_names(tree: ast.AST) -> set:
    """Names bound to Rich's markup-rendering ``print`` in this module.

    ``from rich import print`` shadows the builtin with a markup renderer, so
    from that line on a bare ``print("[branch]")`` loses the token. Without
    that import the same call is stdlib and prints the brackets verbatim.
    """
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module not in _RICH_PRINT_SOURCES:
            continue
        for alias in node.names:
            if alias.name == "print":
                names.add(alias.asname or alias.name)
    return names


def _markup_setting(node: ast.Call) -> Optional[bool]:
    """Whether Rich's parser runs for this call: True on, False off, None unknown.

    ``console.print(body, markup=False)`` renders brackets verbatim -- nothing
    is eaten. That is the correct treatment for pass-through content an author
    does not control (@ai_mail routes message bodies this way) and for a
    pre-formatted block with no styling (drone's returned help page). It is the
    WRONG treatment for a styled line, where it prints the tags, which is why
    the two families exist rather than one guard.

    ``markup=`` handed a name or an expression returns None: whether the parser
    runs cannot be read, so the call is left alone in both directions.
    """
    for keyword in node.keywords:
        if keyword.arg != "markup":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool):
            return keyword.value.value
        return None
    return True


def _is_console_print(node: ast.Call, rich_print_names: set) -> bool:
    """Whether this call hands its arguments to a Rich console."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "print"
    if isinstance(func, ast.Name):
        return func.id in rich_print_names
    return False


def _bound_names(node: ast.AST) -> Tuple[str, ...]:
    """The names this single node binds -- assignment, definition or import."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return (node.id,)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return tuple((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return ()


def _binding_counts(tree: ast.AST) -> Dict[str, int]:
    """How many times each name is bound anywhere in the module.

    A name bound once is a name whose value at the print site is readable. A
    name bound twice -- reassigned in a branch, rebound under ``global``,
    shadowed by an import -- is not, and is dropped rather than guessed at.
    """
    counts: Dict[str, int] = {}
    for node in ast.walk(tree):
        for name in _bound_names(node):
            counts[name] = counts.get(name, 0) + 1
    return counts


def _module_constants(tree: ast.Module) -> Dict[str, ast.expr]:
    """Module-level names assigned exactly one expression, for one-hop reads."""
    counts = _binding_counts(tree)
    constants: Dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            constants[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            constants[node.target.id] = node.value
    return {name: value for name, value in constants.items() if counts.get(name, 0) == 1}


def _module_functions(tree: ast.Module) -> Dict[str, ast.AST]:
    """Module-level functions defined exactly once, for one-hop return reads."""
    counts = _binding_counts(tree)
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and counts.get(node.name, 0) == 1
    }


def _returned_exprs(func: ast.AST) -> Iterator[ast.expr]:
    """Every expression this function returns, excluding nested definitions.

    A ``return`` inside a nested ``def``, ``lambda`` or ``class`` belongs to
    that body, not to this one, so those subtrees are not entered.
    """
    stack: List[ast.AST] = list(getattr(func, "body", []))
    while stack:
        node = stack.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Return):
            if node.value is not None:
                yield node.value
            continue
        stack.extend(ast.iter_child_nodes(node))


def _literal_parts(
    arg: ast.expr,
    constants: Optional[Dict[str, ast.expr]] = None,
    functions: Optional[Dict[str, ast.AST]] = None,
) -> Iterator[Tuple[str, int, int]]:
    """Yield ``(text, start_line, end_line)`` for the literals reachable from one argument.

    Only literals are inspected -- a runtime value cannot be judged. Read
    directly:

    - a plain string literal;
    - an f-string, whose literal segments are yielded SEPARATELY. That is what
      makes ``f"count {d['k']} rows"`` structurally safe: the subscript's
      brackets live in a FormattedValue node, never in a literal segment, so
      they can never be mistaken for a tag;
    - ``"...".format(...)``, still a literal template -- and the one shape
      where a tag may legitimately contain a ``{`` placeholder;
    - ``a + b`` concatenation, read through on both sides, because a help page
      is usually a run of adjacent literals with a call spliced into it.

    Read by following, only when *constants* and *functions* are supplied, and
    then only ONE hop -- the followed expression is re-entered with following
    switched off:

    - ``console.print(BANNER)`` -> the module-level literal BANNER holds;
    - ``console.print(get_help())`` -> the literals ``get_help`` returns.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        yield arg.value, arg.lineno, arg.end_lineno or arg.lineno
        return
    if isinstance(arg, ast.JoinedStr):
        for part in arg.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield part.value, part.lineno, part.end_lineno or part.lineno
        return
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        yield from _literal_parts(arg.left, constants, functions)
        yield from _literal_parts(arg.right, constants, functions)
        return
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        yield from _literal_parts(arg.func.value, constants, functions)
        return
    yield from _followed_parts(arg, constants, functions)


def _followed_parts(
    arg: ast.expr,
    constants: Optional[Dict[str, ast.expr]],
    functions: Optional[Dict[str, ast.AST]],
) -> Iterator[Tuple[str, int, int]]:
    """The one hop: a module-level constant read by name, or a local call's returns.

    The followed expression is re-entered with following switched OFF, so a
    returned ``HEAD + _door_help() + TAIL`` yields HEAD and TAIL and stops at
    ``_door_help()``. One hop, no chain -- the same shape the pack's other
    name resolvers use, and for the same reason: hop two is where a rule
    starts reporting lines nobody can trace back.
    """
    if constants is not None and isinstance(arg, ast.Name):
        value = constants.get(arg.id)
        if value is not None:
            yield from _literal_parts(value)
        return
    if functions is None or not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Name):
        return
    target = functions.get(arg.func.id)
    if target is None:
        return
    for returned in _returned_exprs(target):
        yield from _literal_parts(returned)


def _is_eaten(tag_text: str) -> bool:
    """Whether Rich will silently delete this tag instead of styling with it.

    Mirrors ``rich.markup.render``: the tag text is partitioned on ``=`` into a
    name and parameters, and the style string Rich would build from them is
    handed to Rich's own parser.
    """
    name, equals, parameters = tag_text.partition("=")
    style = str(Tag(name, parameters if equals else None))
    try:
        Style.parse(style)
    except StyleSyntaxError as exc:
        # Not a swallowed failure -- this exception IS the oracle's answer.
        # Recorded rather than dropped so a surprising verdict is traceable.
        logger.info("[rich_markup] Rich rejects %r as a style: %s", style, exc)
        return True
    return False


def _eaten_tags(text: str) -> List[str]:
    """Every tag in *text* that Rich consumes without it being a real style."""
    eaten: List[str] = []
    for match in RE_TAGS.finditer(text):
        _full_text, escapes, tag_text = match.groups()

        # Odd backslash count -> Rich emits the tag as literal text (the fix)
        if len(escapes) % 2 == 1:
            continue
        # Closing tags fail LOUDLY (MarkupError) when they do not match
        if tag_text.startswith("/"):
            continue
        # A .format()/template placeholder is filled in before Rich sees it
        if "{" in tag_text:
            continue
        if _is_eaten(tag_text):
            eaten.append(f"[{tag_text}]")
    return eaten


def _disarmed_tokens(text: str) -> List[str]:
    """Every token in *text* that ``markup=False`` puts on the terminal raw.

    With the parser off the whole string is literal, which is right for a
    pre-formatted block and wrong for anything the author styled:

    - a tag Rich WOULD have rendered as a style now prints as ``[green]``;
    - a hand-escaped ``\\[count]`` now prints its BACKSLASH too, because the
      escape only means anything to the parser that is no longer running. That
      is the concrete sense in which a hand-escape is not a spelling to rely
      on -- it is a cure with a precondition.

    A closing tag on its own is not counted: ``[/usr/bin]`` is a path far more
    often than it is an author's styling.
    """
    disarmed: List[str] = []
    for match in RE_TAGS.finditer(text):
        _full_text, escapes, tag_text = match.groups()
        if len(escapes) % 2 == 1:
            disarmed.append(f"\\[{tag_text}]")
            continue
        if tag_text.startswith("/") or "{" in tag_text:
            continue
        if not _is_eaten(tag_text):
            disarmed.append(f"[{tag_text}]")
    return disarmed


def _tag_line(source_lines: List[str], start: int, end: int, tag: str) -> int:
    """The source line a tag sits on, for literals that span several lines."""
    for lineno in range(start, min(end, len(source_lines)) + 1):
        if tag in source_lines[lineno - 1]:
            return lineno
    return start


def _scan_call(
    node: ast.Call,
    source_lines: List[str],
    constants: Dict[str, ast.expr],
    functions: Dict[str, ast.AST],
) -> Iterator[Finding]:
    """Every finding one Rich print call is responsible for.

    Positional arguments only: ``style=``/``sep=``/``end=`` carry style names
    and separators, not markup.
    """
    markup = _markup_setting(node)
    if markup is None:
        return
    kind = EATEN if markup else DISARMED
    read = _eaten_tags if markup else _disarmed_tokens
    for arg in node.args:
        for text, start, end in _literal_parts(arg, constants, functions):
            for tag in read(text):
                yield Finding(kind, tag, _tag_line(source_lines, start, end, tag), node.lineno)


def _scan_source(source: str) -> Tuple[Optional[List[Finding]], Optional[str]]:
    """Find every render-time loss in a Python source file.

    Returns:
        ``(findings, error)`` where error is None on success. Findings are
        deduplicated -- a helper printed from two call sites carries the same
        token once -- and ordered by the line the author reads.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[rich_markup] Not parseable as Python, skipped: %s", exc)
        return None, str(exc)

    source_lines = source.splitlines()
    rich_print_names = _rich_print_names(tree)
    constants = _module_constants(tree)
    functions = _module_functions(tree)

    seen: Dict[Tuple[str, str, int], Finding] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_console_print(node, rich_print_names):
            continue
        for finding in _scan_call(node, source_lines, constants, functions):
            seen.setdefault((finding.kind, finding.tag, finding.line), finding)

    return sorted(seen.values(), key=lambda f: (f.line, f.tag, f.kind)), None


def _where(finding: Finding) -> str:
    """Where a token lives, and -- when it was followed -- where it is printed."""
    if finding.print_line == finding.line:
        return f"{escape(finding.tag)} on line {finding.line}"
    return f"{escape(finding.tag)} on line {finding.line} (printed on line {finding.print_line})"


def _listing(findings: List[Finding]) -> str:
    """Up to MAX_LISTED tokens named, with the remainder counted, never hidden."""
    listed = ", ".join(_where(finding) for finding in findings[:MAX_LISTED])
    remaining = len(findings) - MAX_LISTED
    return f"{listed}, and {remaining} more" if remaining > 0 else listed


def _violation_message(findings: List[Finding]) -> str:
    """Name the lost tokens and where they are, never a bare count.

    The tokens are Rich-escaped because this message is itself displayed with
    ``console.print(f"[dim]{message}[/dim]")`` by the audit -- an unescaped
    ``[args...]`` here would be eaten on its way to the reader, and the
    checker would demonstrate its own defect.

    The cure named is ``escape()``, per value. ``markup=False`` is named only
    as what it is actually for: an unstyled block printed verbatim.
    """
    parts = []
    eaten = [f for f in findings if f.kind == EATEN]
    disarmed = [f for f in findings if f.kind == DISARMED]
    if eaten:
        parts.append(
            f"{len(eaten)} literal placeholder(s) silently eaten by Rich: {_listing(eaten)}"
            " - escape the value with rich.markup.escape(), or print an unstyled block with markup=False"
        )
    if disarmed:
        parts.append(
            f"{len(disarmed)} token(s) printed raw by markup=False: {_listing(disarmed)}"
            " - markup=False disarms the whole line; escape the value instead"
        )
    return "; ".join(parts)


def _result(passed: bool, name: str, message: str, score: int) -> Dict:
    """Build a single-check result payload in the pack's standard shape."""
    return {
        "passed": passed,
        "checks": [{"name": name, "passed": passed, "message": message}],
        "score": score,
        "standard": "RICH_MARKUP",
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check a Python file for markup Rich loses at render time.

    Args:
        module_path: Path to the Python file to check.
        bypass_rules: Optional list of bypass rules to skip certain checks.

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': 'RICH_MARKUP'
        }
    """
    path = Path(module_path)

    # -- Bypass entire standard for this file --
    if is_bypassed(module_path, "rich_markup", bypass_rules=bypass_rules):
        return _result(True, "Bypassed", "Standard bypassed via .seedgo/bypass.json", 100)

    if not path.exists():
        return _result(False, "File exists", f"File not found: {module_path}", 0)

    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("Cannot read %s: %s", path, exc)
        return _result(False, "File readable", f"Error reading file: {exc}", 0)

    found, error = _scan_source(source)

    if found is None:
        # Unparseable Python is the diagnostics lane's finding, not this one.
        return _result(True, "Rich markup placeholders", f"Not parseable as Python, skipped: {error}", 100)

    # A followed literal has two lines an author might reasonably silence: the
    # one the token sits on and the one that prints it. Either bypass works --
    # the generous direction, and the only one that does not depend on knowing
    # which end of the hop the rule reported from.
    violations = [
        finding
        for finding in found
        if not is_bypassed(module_path, "rich_markup", finding.line, bypass_rules)
        and not is_bypassed(module_path, "rich_markup", finding.print_line, bypass_rules)
    ]

    if violations:
        check = (False, "Rich markup placeholders", _violation_message(violations), 0)
    else:
        check = (True, "Rich markup placeholders", "No literal placeholders eaten by Rich markup", 100)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": check[3], "standard": "rich_markup"},
    )

    return _result(*check)
