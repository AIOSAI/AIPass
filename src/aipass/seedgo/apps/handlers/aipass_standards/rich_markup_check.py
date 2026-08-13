# =================== AIPass ====================
# Name: rich_markup_check.py
# Description: Rich Markup Standards Checker Handler
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

"""
Rich Markup Standards Checker Handler

Detects literal square-bracket placeholders in console output that Rich
SILENTLY deletes at render time.

THE DEFECT:
Rich reads ``[word]`` in a printed string as a style tag. When the tag is not
a real Rich style, Rich removes it from the rendered output and says nothing --
no error, no gap, no marker. The source string is correct, so every
source-reading audit passes at 100% while the user sees mutilated output::

    console.print("drone @hooks <command> [args...]")   ->  "drone @hooks <command> "
    console.print("monitor run [branches]")             ->  "monitor run "
    console.print("[branch] row")                       ->  " row"

An entire attribution column has been lost this way, invisibly.

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
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

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


def _markup_disabled(node: ast.Call) -> bool:
    """Whether this call passes ``markup=False``, which turns Rich's parser off.

    ``console.print(body, markup=False)`` renders brackets verbatim -- nothing is
    eaten, so there is nothing to flag. This is the correct fix for pass-through
    content an author does not control (@ai_mail routes message bodies this way),
    where escaping is impossible because the text is not the author's to edit.
    Without this guard the checker punishes the sound fix and rewards the escape
    that cannot be applied, which would make the standard actively wrong.
    """
    for keyword in node.keywords:
        if keyword.arg == "markup" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
            return True
    return False


def _is_console_print(node: ast.Call, rich_print_names: set) -> bool:
    """Whether this call renders its arguments through Rich markup."""
    if _markup_disabled(node):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "print"
    if isinstance(func, ast.Name):
        return func.id in rich_print_names
    return False


def _literal_parts(arg: ast.expr) -> Iterator[Tuple[str, int, int]]:
    """Yield ``(text, start_line, end_line)`` for the literal strings in one argument.

    Only literals are inspected -- a runtime value cannot be judged. Three
    shapes carry one:

    - a plain string literal;
    - an f-string, whose literal segments are yielded SEPARATELY. That is what
      makes ``f"count {d['k']} rows"`` structurally safe: the subscript's
      brackets live in a FormattedValue node, never in a literal segment, so
      they can never be mistaken for a tag;
    - ``"...".format(...)``, still a literal template -- and the one shape
      where a tag may legitimately contain a ``{`` placeholder.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        yield arg.value, arg.lineno, arg.end_lineno or arg.lineno
    elif isinstance(arg, ast.JoinedStr):
        for part in arg.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield part.value, part.lineno, part.end_lineno or part.lineno
    elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        yield from _literal_parts(arg.func.value)


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


def _tag_line(source_lines: List[str], start: int, end: int, tag: str) -> int:
    """The source line a tag sits on, for literals that span several lines."""
    for lineno in range(start, min(end, len(source_lines)) + 1):
        if tag in source_lines[lineno - 1]:
            return lineno
    return start


def _scan_source(source: str) -> Tuple[Optional[List[Tuple[str, int]]], Optional[str]]:
    """Find every silently-eaten placeholder in a Python source file.

    Returns:
        ``(violations, error)`` where violations is a list of
        ``(tag_markup, line_number)`` and error is None on success.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[rich_markup] Not parseable as Python, skipped: %s", exc)
        return None, str(exc)

    source_lines = source.splitlines()
    rich_print_names = _rich_print_names(tree)
    violations: List[Tuple[str, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_console_print(node, rich_print_names):
            continue
        # Positional arguments only: `style=`/`sep=`/`end=` carry style names
        # and separators, not markup.
        for arg in node.args:
            for text, start, end in _literal_parts(arg):
                for tag in _eaten_tags(text):
                    violations.append((tag, _tag_line(source_lines, start, end, tag)))

    return violations, None


def _violation_message(violations: List[Tuple[str, int]]) -> str:
    """Name the eaten tokens and where they are, never a bare count.

    The tokens are Rich-escaped because this message is itself displayed with
    ``console.print(f"[dim]{message}[/dim]")`` by the audit -- an unescaped
    ``[args...]`` here would be eaten on its way to the reader, and the
    checker would demonstrate its own defect.
    """
    listed = ", ".join(f"{escape(tag)} on line {line}" for tag, line in violations[:MAX_LISTED])
    remaining = len(violations) - MAX_LISTED
    suffix = f", and {remaining} more" if remaining > 0 else ""
    # "\\[" renders as the literal "\[" the author must type
    return f"{len(violations)} literal placeholder(s) silently eaten by Rich: {listed}{suffix} - escape as \\\\["


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
    Check a Python file for literal placeholders Rich deletes at render time.

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

    violations = [(tag, line) for tag, line in found if not is_bypassed(module_path, "rich_markup", line, bypass_rules)]

    if violations:
        check = (False, "Rich markup placeholders", _violation_message(violations), 0)
    else:
        check = (True, "Rich markup placeholders", "No literal placeholders eaten by Rich markup", 100)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": check[3], "standard": "rich_markup"},
    )

    return _result(*check)
