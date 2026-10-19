# =================== AIPass ====================
# Name: prose_lines.py
# Description: Which source lines are prose (docstrings, comment lines) and which are code
# Version: 1.0.0
# Created: 2026-10-17
# Modified: 2026-10-18
# =============================================

"""Which 1-based lines of a Python source are prose and which are code, for the line-based checkers."""

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import FrozenSet, Set

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


class UnparseableSource(ValueError):
    """The source does not parse, so no line can be called prose or code."""


@dataclass(frozen=True)
class LineKinds:
    """The line sets of one source text; every number is a 1-based line."""

    docstrings: FrozenSet[int]
    comments: FrozenSet[int]
    string_bodies: FrozenSet[int]
    line_count: int

    @property
    def prose(self) -> FrozenSet[int]:
        """Docstring lines and comment-only lines."""
        return self.docstrings | self.comments

    @property
    def text_only(self) -> FrozenSet[int]:
        """Prose plus string-literal continuation lines: no call, import or def starts on any of them."""
        return self.prose | self.string_bodies

    @property
    def code(self) -> FrozenSet[int]:
        """Every line that is not prose, blank lines included."""
        return frozenset(range(1, self.line_count + 1)) - self.prose


def _byte_prefix(line: str, col: int) -> str:
    """The text before ``col``, which ast counts in UTF-8 bytes."""
    return line.encode("utf-8")[:col].decode("utf-8", errors="ignore")


def _byte_suffix(line: str, col: int) -> str:
    """The text from ``col`` on, which ast counts in UTF-8 bytes."""
    return line.encode("utf-8")[col:].decode("utf-8", errors="ignore")


def _docstring_lines(tree: ast.Module, lines: list) -> Set[int]:
    found: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_OWNERS) or not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)):
            continue
        if not isinstance(first.value.value, str) or first.end_lineno is None or first.end_col_offset is None:
            continue
        start, end = first.lineno, first.end_lineno
        span = set(range(start, end + 1))
        # `def f(): """doc"""` shares its line with code, and that line stays code.
        if _byte_prefix(lines[start - 1], first.col_offset).strip():
            span.discard(start)
        tail = _byte_suffix(lines[end - 1], first.end_col_offset).strip()
        if tail and not tail.startswith("#"):
            span.discard(end)
        found |= span
    return found


def _token_lines(source: str) -> tuple:
    """Comment-only lines, and the continuation lines of every string token spanning several lines."""
    comments: Set[int] = set()
    bodies: Set[int] = set()
    fstring_starts: list = []
    fstring_start = getattr(tokenize, "FSTRING_START", -1)
    fstring_end = getattr(tokenize, "FSTRING_END", -1)
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT and not tok.line[: tok.start[1]].strip():
            comments.add(tok.start[0])
        elif tok.type == fstring_start:
            fstring_starts.append(tok.start[0])
        elif tok.type in (tokenize.STRING, fstring_end):
            first = fstring_starts.pop() if tok.type == fstring_end and fstring_starts else tok.start[0]
            bodies.update(range(first + 1, tok.end[0] + 1))
    return comments, bodies


def classify(source: str) -> LineKinds:
    """Sort every line of ``source``; raises UnparseableSource when it does not parse.

    A docstring is the string-constant first statement of a module, class or function, every line of it.
    A comment line is one whose text starts with ``#``; a comment after code leaves the line code.
    Any other string literal, triple-quoted or not, is code.
    """
    lines = source.split("\n")
    try:
        tree = ast.parse(source)
        comments, bodies = _token_lines(source)
    except (SyntaxError, ValueError, tokenize.TokenError) as exc:
        logger.info("prose_lines: unparseable, no line sorted: %s", exc)
        json_handler.log_operation("prose_lines_unparseable", {"error": str(exc)})
        raise UnparseableSource(str(exc)) from exc
    docstrings = _docstring_lines(tree, lines)
    return LineKinds(
        docstrings=frozenset(docstrings),
        comments=frozenset(comments),
        string_bodies=frozenset(bodies - docstrings),
        line_count=len(lines),
    )


def prose_lines(source: str) -> FrozenSet[int]:
    """Docstring and comment-only lines of ``source``; raises UnparseableSource."""
    return classify(source).prose


def hash_lines(source: str) -> FrozenSet[int]:
    """Lines whose text starts with ``#``: the only prose a caller can name in a source that does not parse."""
    return frozenset(i for i, line in enumerate(source.split("\n"), 1) if line.strip().startswith("#"))
