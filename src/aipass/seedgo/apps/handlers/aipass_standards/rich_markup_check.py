# =================== AIPass ====================
# Name: rich_markup_check.py
# Description: Rich Markup Standards Checker Handler
# Version: 2.0.2
# Created: 2026-08-11
# Modified: 2026-10-24
# =============================================

"""
Rich Markup Standards Checker Handler

Reference: rich_markup.md
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

AUDIT_SCOPE = "all_files"

# Production only: a test file renders nothing a user reads, and tests build broken markup as fixtures.
APPLIES_TO = "production"

MAX_LISTED = 5

# ``obj.print(...)`` reaches Rich's markup parser in every shape; a BARE ``print(...)`` is stdlib and renders
# no markup, so a bare name only counts when the module bound it from Rich itself.
_RICH_PRINT_SOURCES = ("rich", "rich.console")

#: The two families, kept apart so each carries its own cure in the message.
EATEN = "eaten"
DISARMED = "disarmed"


class Finding(NamedTuple):
    """One reported token.

    ``print_line`` differs from ``line`` when the literal was followed from a constant or a return.
    """

    kind: str
    tag: str
    line: int
    print_line: int


def _rich_print_names(tree: ast.AST) -> set:
    """Names bound to Rich's markup-rendering ``print`` in this module.

    ``from rich import print`` shadows the builtin with a markup renderer, so from that line on a bare
    ``print("[branch]")`` loses the token; without that import the call is stdlib and prints it verbatim.
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

    ``markup=False`` is right for pass-through content and an unstyled pre-formatted block, wrong for a
    styled line (it prints the tags). ``markup=`` handed a non-constant returns None: the call is left alone.
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

    A name bound twice (reassigned, rebound under ``global``, shadowed by an import) is dropped, not guessed.
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

    A ``return`` inside a nested ``def``, ``lambda`` or ``class`` belongs to that body and is not entered.
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

    Only literals are read: plain strings, f-string literal segments (so a subscript's brackets never read
    as a tag), ``"...".format(...)`` templates and ``+`` concatenation; with *constants* and *functions*
    supplied, one hop to a module-level literal or a local function's returned literals.
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

    Following is switched OFF for the re-entered expression: one hop, no chain, like the pack's other resolvers.
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

    Mirrors ``rich.markup.render``: the tag text is partitioned on ``=`` and the style string Rich would
    build is handed to Rich's own parser.
    """
    name, equals, parameters = tag_text.partition("=")
    style = str(Tag(name, parameters if equals else None))
    try:
        Style.parse(style)
    except StyleSyntaxError as exc:
        # Not a swallowed failure: this exception IS the oracle's answer, logged so a verdict is traceable.
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

    With the parser off a real style prints as ``[green]`` and a hand-escaped ``\\[count]`` prints its
    backslash. A lone closing tag is not counted: ``[/usr/bin]`` is far more often a path.
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

    Positional arguments only: ``style=``/``sep=``/``end=`` carry style names and separators, not markup.
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

    Findings are deduplicated (a helper printed from two call sites carries a token once), ordered by line.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
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

    The tokens are Rich-escaped because the audit displays this message with ``console.print``: an
    unescaped ``[args...]`` would be eaten on its way to the reader.
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


def _declined(result: Dict) -> Dict:
    """Mark a single-check result as a file this standard does not judge (out of the row's average)."""
    result["checks"][0]["declined"] = True
    return result


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for markup Rich loses at render time."""
    path = Path(module_path)

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
        return _declined(_result(True, "Rich markup placeholders", f"Not parseable as Python, skipped: {error}", 100))

    # Either line a followed literal touches (the token's or the print's) may carry the bypass.
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
