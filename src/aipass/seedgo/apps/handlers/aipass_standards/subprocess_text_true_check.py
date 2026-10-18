# =================== AIPass ====================
# Name: subprocess_text_true_check.py
# Description: Subprocess Text True Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-10-17
# =============================================

"""
Subprocess Text True Standards Checker Handler

Reference: subprocess_text_true.md
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

CALLS: frozenset[str] = frozenset(
    {"subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call", "subprocess.call"}
)

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
    """Check a test file for a text-mode subprocess call that names no encoding."""
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
