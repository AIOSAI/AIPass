# =================== AIPass ====================
# Name: subprocess_text_true_check.py
# Description: Subprocess Text True Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Subprocess Text True Standards Checker Handler

``named_encoding``'s hazard one pipe over. ``subprocess.run(..., text=True)``
with no ``encoding=`` decodes the child's stdout and stderr (and encodes
``input=``) with ``locale.getpreferredencoding(False)``: UTF-8 on this fleet's
Linux and macOS hosts, cp1252 on Windows. A child that prints a box character
or an em dash then raises UnicodeDecodeError in the Windows lane, a failure of
the TEST and not of the product. ``named_encoding`` judges ``open``,
``read_text`` and ``write_text`` only; it never looks at a subprocess call.

  ``backup/tests/test_dead_cwd_imports.py`` (7b51d118, lines 224, 706, 797,
  852): four ``subprocess.run(..., capture_output=True, text=True)`` calls
  that read a child interpreter's report with no encoding named.

THE SHAPE. A call to ``subprocess.run``, ``Popen``, ``check_output``,
``check_call`` or ``call`` with ``text=True`` or ``universal_newlines=True``
(the literal ``True``) and no ``encoding=`` keyword, or ``encoding=None``,
which is the locale again. The hit is reported on the ``text=`` line.
``errors=`` alone does not cure it: it names the error handler, not the codec.
Names resolve through the file's own imports, anywhere in the file:
``import subprocess as sp`` and ``from subprocess import run`` are followed.

NOT CONVICTED, each for its reason:
  * ``encoding=`` given with any other value: the encoding is named. It
    implies text mode on its own, so ``text=True`` beside it is harmless.
  * ``text=False``, or no flag at all: bytes, nothing to decode.
  * ``text=flag`` where flag is not a literal: whether it is text mode cannot
    be read from the statement.
  * A ``**kwargs`` splat: it can carry the encoding.
  * A mock's ``assert_called_once_with(..., text=True)``, a helper that wraps
    subprocess (its own call inside is judged, its callers are not), and the
    same words inside a string: none of them is a subprocess call.
  * ``getoutput`` / ``getstatusoutput``: always text, no flag to read. Zero
    in the fleet's tests.

CHECK FIRST (2026-09-25, before the rule landed). 598 test files under the
pack's applicability, 127 subprocess calls (run 118, Popen 9): 115 convicted
in 52 files across 18 branches -- memory 3 files / 21, aipass 6 / 15, skills
3 / 10, api 5 / 8, prax 4 / 8, spawn 2 / 8, drone 5 / 7, seedgo 6 / 6,
ai_mail 2 / 5, flow 2 / 5, hooks 3 / 5, backup 1 / 4, devpulse 2 / 4, cli
3 / 3, commons 1 / 2, daemon 2 / 2, canary 1 / 1, trigger 1 / 1. Every one
is ``subprocess.run`` with ``text=True``; universal_newlines 0, Popen 0.
Compliant: 1 call names an encoding (encoding only, no flag), 0 pair it with
``text=True``. Non-literal flags 0, splats 0. The model file
``tests/test_readme_update.py`` scores 100.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "SUBPROCESS_TEXT_TRUE"
STANDARD_KEY = "subprocess_text_true"

#: The subprocess calls that take a text flag, by canonical dotted name.
CALLS: frozenset[str] = frozenset(
    {"subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call", "subprocess.call"}
)

#: The two spellings of text mode.
FLAGS: Tuple[str, ...] = ("text", "universal_newlines")

CURE = 'pass encoding="utf-8" (and errors= if the child may print bytes that are not utf-8)'
WHY = "decodes with the locale encoding, cp1252 on Windows"


def _bindings(node: ast.AST) -> List[Tuple[str, str]]:
    """(local name, dotted name) pairs one import statement binds."""
    if isinstance(node, ast.Import):
        pairs: List[Tuple[str, str]] = []
        for alias in node.names:
            head = alias.name.split(".")[0]
            pairs.append((alias.asname, alias.name) if alias.asname else (head, head))
        return pairs
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [(alias.asname or alias.name, f"{node.module}.{alias.name}") for alias in node.names]
    return []


def aliases(tree: ast.AST) -> Dict[str, str]:
    """Local name -> dotted name, from every import in the file, local ones included."""
    return {local: full for node in ast.walk(tree) for local, full in _bindings(node)}


def dotted(expr: ast.AST, bound: Dict[str, str]) -> str | None:
    """The canonical dotted name of a Name/Attribute chain, through the file's imports."""
    if isinstance(expr, ast.Name):
        return bound.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        head = dotted(expr.value, bound)
        return f"{head}.{expr.attr}" if head else None
    return None


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    """The named keyword argument of a call, or None."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword
    return None


def _text_flag(call: ast.Call) -> ast.keyword | None:
    """The ``text=True`` / ``universal_newlines=True`` keyword, literal True only."""
    for flag in FLAGS:
        keyword = _keyword(call, flag)
        if keyword is not None and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
            return keyword
    return None


def _names_encoding(call: ast.Call) -> bool:
    """Whether ``encoding=`` is given as something other than the literal None."""
    keyword = _keyword(call, "encoding")
    if keyword is None:
        return False
    return not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)


def scan(tree: ast.AST) -> List[Tuple[int, str, str]]:
    """(line of the flag, call, flag) for every text-mode subprocess call with no encoding."""
    bound = aliases(tree)
    hits: List[Tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func, bound)
        if name not in CALLS or any(keyword.arg is None for keyword in node.keywords):
            continue
        flag = _text_flag(node)
        if flag is None or _names_encoding(node):
            continue
        hits.append((getattr(flag, "lineno", node.lineno), name, str(flag.arg)))
    return sorted(hits)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[subprocess_text_true] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Subprocess text true", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for a text-mode subprocess call that names no encoding.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[subprocess_text_true] Unparseable %s: %s", module_path, exc)
        return _result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100)

    hits = [hit for hit in scan(tree) if not is_bypassed(module_path, STANDARD_KEY, hit[0], bypass_rules)]
    if not hits:
        return _result(True, _one_check(True, "Every text-mode subprocess call names an encoding"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per hit would hide the rest.
    detail = "\n".join(
        f"{path.name}:{line} {name}({flag}=True) without encoding - {WHY}; {CURE}" for line, name, flag in hits
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
