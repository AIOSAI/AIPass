# =================== AIPass ====================
# Name: named_encoding_check.py
# Description: Named Encoding Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-10-17
# =============================================

"""
Named Encoding Standards Checker Handler

Reference: named_encoding.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "NAMED_ENCODING"
STANDARD_KEY = "named_encoding"

# Where `encoding` sits POSITIONALLY: open(file, mode, buffering, encoding), read_text(encoding),
# write_text(data, encoding). Filling the slot names the encoding.
_ENCODING_SLOT: Dict[str, int] = {"open": 3, "read_text": 0, "write_text": 1}

# The text-mode calls whose encoding argument this rule is about. read_bytes
# and write_bytes are absent on purpose: they have no encoding parameter.
_TEXT_METHODS: frozenset[str] = frozenset({"read_text", "write_text"})

_UTF8_SPELLINGS: frozenset[str] = frozenset({"utf-8", "utf8"})

FIX = 'name encoding="utf-8"; the default is cp1252 on Windows and the product\'s output is not ASCII'


def _keyword(node: ast.Call, name: str) -> ast.keyword | None:
    """The named keyword argument of a call, or None."""
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword
    return None


def _literal_str(node: ast.expr | None) -> str | None:
    """The value of a string literal, or None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _positional(node: ast.Call, index: int) -> ast.expr | None:
    """The positional argument at an index, or None if the call is shorter.

    A ``*args`` splat anywhere before the index makes every later position
    unreadable, so the call is treated as not having filled it -- which is why
    the caller checks ``_has_splat`` before convicting.
    """
    if index < len(node.args):
        return node.args[index]
    return None


def _has_splat(node: ast.Call) -> bool:
    """Whether the call forwards ``*args`` or ``**kwargs``.

    Either can carry the encoding, so nothing about the call can be read with
    confidence and the checker declines rather than guesses.
    """
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        return True
    return any(keyword.arg is None for keyword in node.keywords)


def _open_mode(node: ast.Call) -> Tuple[str | None, bool]:
    """(mode, readable) for an ``open`` call -- default "r" when unstated."""
    keyword = _keyword(node, "mode")
    if keyword is not None:
        value = _literal_str(keyword.value)
        return (value, value is not None)
    positional = _positional(node, 1)
    if positional is None:
        return ("r", True)
    value = _literal_str(positional)
    return (value, value is not None)


def _encoding_argument(node: ast.Call, shape: str) -> Tuple[ast.expr | None, bool]:
    """(the encoding expression, whether one was given) for a call."""
    keyword = _keyword(node, "encoding")
    if keyword is not None:
        return (keyword.value, True)
    positional = _positional(node, _ENCODING_SLOT[shape])
    if positional is not None:
        return (positional, True)
    return (None, False)


def _shape(node: ast.Call) -> str | None:
    """Which of the three calls this is, or None for anything else."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return "open"
    if isinstance(func, ast.Attribute) and func.attr in _TEXT_METHODS:
        return func.attr
    return None


def _is_text_call(node: ast.Call, shape: str) -> bool:
    """Whether this call reads or writes TEXT, and can therefore be judged."""
    if shape != "open":
        return True
    mode, readable = _open_mode(node)
    if not readable or mode is None:
        return False
    return "b" not in mode


def _describe(shape: str) -> str:
    """How a hit names itself in the report."""
    if shape == "open":
        return "open() without encoding"
    return f"{shape}() without encoding"


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, name, fix) for every unnamed encoding in one test file.

    A file that does not parse yields nothing: ruff already convicts the syntax error.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[named_encoding] Unparseable, nothing scanned: %s", exc)
        return []

    hits: List[Tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        shape = _shape(node)
        if shape is None or _has_splat(node) or not _is_text_call(node, shape):
            continue
        _expression, named = _encoding_argument(node, shape)
        if not named:
            hits.append((node.lineno, _describe(shape), FIX))
    return sorted(hits)


def named_other_encodings(source: str) -> List[Tuple[int, str]]:
    """(line, encoding) for every call that names an encoding other than utf-8.

    Counted, never convicted: a latin-1 test has to name latin-1, and the count keeps that visible.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        shape = _shape(node)
        if shape is None or _has_splat(node) or not _is_text_call(node, shape):
            continue
        expression, named = _encoding_argument(node, shape)
        if not named:
            continue
        spelling = _literal_str(expression)
        if spelling is None:
            continue
        if spelling.lower().replace("_", "-") not in _UTF8_SPELLINGS:
            found.append((node.lineno, spelling))
    return sorted(found)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[named_encoding] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Named encoding", "passed": passed, "message": message}]


def _clean_message(others: List[Tuple[int, str]]) -> str:
    """What a passing file says, carrying the deliberate non-utf-8 count."""
    if not others:
        return "Every text read and write names an encoding"
    spellings = ", ".join(sorted({spelling for _line, spelling in others}))
    subject = "call names" if len(others) == 1 else "calls name"
    return f"Every text read and write names an encoding ({len(others)} {subject} {spellings}, which the rule allows)"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for a file read or write with no encoding named."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    hits = [h for h in scan(source) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, _clean_message(named_other_encodings(source))), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(f"{path.name}:{line} {name} - {fix}" for line, name, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
