# =================== AIPass ====================
# Name: fallback_check.py
# Description: Fallback Standards Checker Handler
# Version: 1.2.0
# Created: 2026-11-14
# Modified: 2026-11-16
# =============================================

"""
Fallback Standards Checker Handler

Reference: fallback.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.bypass.utils import matching_rule
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.aipass_standards.check_support import read_text, result, tail_name

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"
ADVISORY = True
#: checklist prints a hit as [ADVISORY], not [FAIL]: the edit hook shows it without demanding a fix.
CHECKLIST_ADVISES = True

STANDARD = "FALLBACK"
STANDARD_KEY = "fallback"

#: Logger levels a person is meant to read; debug is dropped at the fleet's INFO level, info is routine.
WARNING_LEVELS = frozenset({"warning", "warn", "error", "exception", "critical"})
IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})
#: Types that mean "the bytes were there and could not be used"; FileNotFoundError alone is absence, not corruption.
READ_ERRORS = frozenset(
    {
        "JSONDecodeError",
        "ValueError",
        "OSError",
        "IOError",
        "UnicodeDecodeError",
        "PermissionError",
        "YAMLError",
        "TOMLDecodeError",
        "Exception",
        "BaseException",
    }
)
READ_CALLS = re.compile(
    r"^(open|read|load|loads|safe_load|parse|read_text|read_bytes)$|^(read|load|parse)_|_(json|yaml|toml)$"
)
TOOL_FINDERS = re.compile(r"^(which|find_spec)$|_(bin|binary|executable)$")
IMPORT_CALLS = frozenset({"import_module", "__import__", "find_spec", "spec_from_file_location", "exec_module"})
GATE_WORDS = re.compile(r"check|gate|lint|valid|verif|guard|protect|trust|allow|permit|authori|enforce")
DISGUISES = re.compile(r"best[ _-]effort|graceful|legacy|compat|fall(?:s|ing)?[ _-]?back", re.IGNORECASE)
#: "No such process" answers a signal: the state a kill wanted or a probe asked about, never a stand-in.
SIGNAL_CALLS = frozenset({"kill", "killpg", "_kill", "send_signal"})
#: Calls that put the failure in front of a person: the handler is loud, not a fallback.
SHOWN_BY = frozenset({"print", "echo", "error", "fail", "exit", "_exit", "abort"})

CURE = "raise, or waive this one site with a bypass row (lines or functions) that says why"


def _caught(handler: ast.ExceptHandler) -> set[str]:
    """Last name component of every type the handler catches; {""} for a bare except."""
    if handler.type is None:
        return {""}
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return {tail_name(node) for node in nodes}


def _walk(nodes: List[ast.stmt]):
    """Every node under ``nodes``."""
    return ast.walk(ast.Module(body=nodes, type_ignores=[]))


def _is_loud(handler: ast.ExceptHandler) -> bool:
    """True when the handler raises, exits or shows the failure on a stream."""
    for node in _walk(handler.body):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call) and not _is_log_call(node):
            name = tail_name(node.func)
            if name in SHOWN_BY or (name == "write" and "std" in ast.unparse(node.func)):
                return True
    return False


def _warns(handler: ast.ExceptHandler) -> bool:
    """True when the handler logs at warning level or above."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in WARNING_LEVELS
        and "log" in ast.unparse(node.func.value).lower()
        for node in _walk(handler.body)
    )


def _is_log_call(node: ast.AST) -> bool:
    """True for a ``<something log>.<level>(...)`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and "log" in ast.unparse(node.func.value).lower()
    )


def _carries(handler: ast.ExceptHandler, gate: bool) -> bool:
    """True when the handler hands the failure on as a value: the exception itself, a reason, a sentinel.

    In a gate, False is a verdict, not a carrier, only when it means "not passed"; that polarity is not judged.
    """
    if _uses_the_exception(handler):
        return True
    answers = [
        n
        for n in _walk(handler.body)
        if isinstance(n, (ast.Return, ast.Assign)) or (isinstance(n, ast.Expr) and not _is_log_call(n.value))
    ]
    return any(_is_a_reason(answer.value, gate) for answer in answers if answer.value is not None)


def _uses_the_exception(handler: ast.ExceptHandler) -> bool:
    """True when the bound exception is used outside a log call."""
    logged = {id(n) for call in _walk(handler.body) if _is_log_call(call) for n in ast.walk(call)}
    return bool(handler.name) and any(
        isinstance(n, ast.Name) and n.id == handler.name and id(n) not in logged for n in _walk(handler.body)
    )


def _is_a_reason(value: ast.expr, gate: bool) -> bool:
    """True when a value says what failed: a non-empty string, an upper-case sentinel, or False outside a gate.

    A value holding True claims success (``result(True, "Not judged")``): its string is a note, not a reason.
    """
    parts = _answer_parts(value)
    if any(isinstance(n, ast.Constant) and n.value is True for n in parts):
        return False
    for n in parts:
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip():
            return True
        if isinstance(n, ast.Constant) and n.value is False and not gate:
            return True
        if isinstance(n, ast.Name) and n.id.isupper() and len(n.id) > 1:
            return True
    return False


def _answer_parts(value: ast.expr) -> List[ast.AST]:
    """The value and its parts, nested: tuple items, dict values, call arguments; never dict keys.

    Nested because a reason often rides in a record: ``[CheckResult("x", FAIL, "unreadable")]``.
    """
    if isinstance(value, (ast.Tuple, ast.List)):
        parts = value.elts
    elif isinstance(value, ast.Dict):
        parts = value.values
    elif isinstance(value, ast.Call):
        parts = [*value.args, *(kw.value for kw in value.keywords)]
    else:
        return [value]
    return [value, *(n for part in parts if part is not None for n in _answer_parts(part))]


def _tries_the_next(handler: ast.ExceptHandler) -> bool:
    """Only continue or break, after warning-level log lines if any: the loop tries its next candidate.

    An info or debug line before the skip is read by nobody, so that skip is still judged.
    """
    *before, last = handler.body
    return (
        isinstance(last, (ast.Continue, ast.Break))
        and all(isinstance(stmt, ast.Expr) and _is_log_call(stmt.value) for stmt in before)
        and (not before or _warns(handler))
    )


def _returns_the_failure(handler: ast.ExceptHandler) -> bool:
    """An import handler that returns the failure to its caller and imports nothing in its place.

    The return must hold the exception or a record with a reason in it: a flag (``X_AVAILABLE = False``),
    a sentinel (``_ALLOW``) or a bare string (``"w0"``) is the stand-in, not a carrier.
    """
    nodes = list(_walk(handler.body))
    if any(
        isinstance(n, (ast.Import, ast.ImportFrom)) or (isinstance(n, ast.Call) and tail_name(n.func) in IMPORT_CALLS)
        for n in nodes
    ):
        return False
    returned = [n.value for n in nodes if isinstance(n, ast.Return) and n.value is not None]
    records = [v for v in returned if isinstance(v, (ast.Tuple, ast.List, ast.Dict, ast.Call))]
    return bool(returned) and (_uses_the_exception(handler) or any(_has_text(v) for v in records))


def _has_text(value: ast.expr) -> bool:
    """A non-empty string among the value's parts, and no True claiming success."""
    parts = _answer_parts(value)
    return not any(isinstance(n, ast.Constant) and n.value is True for n in parts) and any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip() for n in parts
    )


def _calls(try_node: ast.Try, names: frozenset) -> bool:
    """True when the protected block makes a call under one of ``names``."""
    return any(isinstance(node, ast.Call) and tail_name(node.func) in names for node in _walk(try_node.body))


def _reads_a_file(try_node: ast.Try) -> bool:
    """True when the protected block reads bytes from disk."""
    return any(isinstance(node, ast.Call) and READ_CALLS.search(tail_name(node.func)) for node in _walk(try_node.body))


def _shape(handler: ast.ExceptHandler, try_node: ast.Try, function: str, lines: List[str]) -> Optional[str]:
    """The fallback shape this handler takes, or None when it is not one."""
    if not handler.body or _is_loud(handler):
        return None
    caught = _caught(handler)
    if caught == {"ProcessLookupError"} and _calls(try_node, SIGNAL_CALLS):
        return None
    if caught & IMPORT_ERRORS or _calls(try_node, IMPORT_CALLS):
        # A module skipped with only a log line loses its commands: only a bare skip tries the next.
        bare_skip = all(isinstance(stmt, (ast.Continue, ast.Break)) for stmt in handler.body)
        return None if bare_skip or _returns_the_failure(handler) else "import-failure stand-in"
    if _tries_the_next(handler):
        return None
    gate = bool(GATE_WORDS.search(function.lower()))
    if _carries(handler, gate):
        return None
    if caught & (READ_ERRORS | {""}) and _reads_a_file(try_node):
        return "unreadable file read as a default"
    if gate:
        return f"check that cannot run reads as passed ({function})"
    # shortcut: a missing binary also raises FileNotFoundError; a run() beside a loads() reads as absence.
    # Split if one shows.
    if caught == {"FileNotFoundError"} and _reads_a_file(try_node):
        return None  # absence, not corruption: the documented default for a file that is not there
    # The comment over the try names the fallback as often as the handler does.
    above = lines[max(0, try_node.lineno - 3) : try_node.lineno]
    span = "\n".join([function, *above, *lines[handler.lineno - 1 : (handler.end_lineno or handler.lineno)]])
    word = DISGUISES.search(span)
    if word:
        return f"fallback disguised as '{word.group(0).lower()}'"
    if not _warns(handler):
        return "default with no warning-level log"
    return None


def _missing_tool_passes(function: ast.AST) -> List[int]:
    """Lines of ``if not tool:`` returns, where tool came from shutil.which or find_spec."""
    tools = {
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and TOOL_FINDERS.search(tail_name(node.value.func))
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    hits = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If) or not tools:
            continue
        test = ast.unparse(node.test)
        names_a_tool = any(re.search(rf"\bnot {t}\b|\b{t} is None\b", test) for t in tools)
        if (
            names_a_tool
            and isinstance(node.body[-1], ast.Return)
            and not (node.body[-1].value is not None and _is_a_reason(node.body[-1].value, gate=True))
            and not any(isinstance(n, ast.Raise) for n in _walk(node.body))
        ):
            hits.append(node.lineno)
    return hits


def scan(tree: ast.AST, source: str) -> List[Tuple[int, str, str]]:
    """(line, shape, enclosing function) for every fallback in a module."""
    lines = source.splitlines()
    hits: List[Tuple[int, str, str]] = []
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner = {}
    for function in functions:
        for node in ast.walk(function):
            owner[id(node)] = function.name
        hits.extend((line, "a missing tool reads as passed", function.name) for line in _missing_tool_passes(function))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            function = owner.get(id(handler), "<module>")
            shape = _shape(handler, node, function, lines)
            if shape:
                hits.append((handler.lineno, shape, function))
    return sorted(set(hits))


def _waived(module_path: str, line: int, function: str, bypass_rules: list | None) -> bool:
    """True when a rule pinned to this site waives it; a whole-file rule never does."""
    rule = matching_rule(module_path, STANDARD_KEY, line, bypass_rules, function)
    return rule is not None and bool(rule.get("lines") or rule.get("functions"))


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list."""
    return [{"name": "Fallback", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for fallbacks: a failure answered with a stand-in instead of an error."""
    path = Path(module_path)
    if not path.exists():
        return result(False, _one_check(False, f"File not found: {module_path}"), 0, STANDARD)
    source = read_text(path, tag=STANDARD_KEY, errors="ignore")
    if source is None:
        return result(False, _one_check(False, f"Error reading file: {module_path}"), 0, STANDARD)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[fallback] Unparseable %s: %s", module_path, exc)
        return result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100, STANDARD)

    hits = [hit for hit in scan(tree, source) if not _waived(module_path, hit[0], hit[2], bypass_rules)]
    if not hits:
        return result(True, _one_check(True, "No unwaived fallback"), 100, STANDARD)
    detail = "\n".join(f"{path.name}:{line} {shape} - {CURE}" for line, shape, _ in hits)
    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)}
    )
    return result(False, _one_check(False, detail), 0, STANDARD)
