# =================== AIPass ====================
# Name: one_logger_check.py
# Description: One Logger Standards Checker Handler - prax is the only logging system
# Version: 1.2.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""One Logger Standards Checker Handler

Reference: one_logger.md. Four AST keys, each a logger that is not prax:
K0 stdlib logging, K1 a level-shaped class, K2 a hand-written .log file, K3 a stream-writing log helper.
No bypass row waives a finding; K0 and K1 pass only the files prax's ``LOGGING_ALLOWED`` and
``LOGGER_DOORS`` name, K2 and K3 only what ``logging_allowed.ALLOWED`` names.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards.check_support import read_text, result, tail_name
from aipass.sentry.apps.handlers.aipass_standards.logging_allowed import allowed_by, published_lists
from aipass.sentry.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"
INCLUDE_INIT_FILES = True
ADVISORY = True
CHECKLIST_ADVISES = True

STANDARD = "ONE_LOGGER"
STANDARD_KEY = "one_logger"
LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})
DOORS = "log through prax: from aipass.prax import logger (a loop on the watched log path: aipass.prax trail)"
CURES = {
    "K0": DOORS,
    "K1": f"delete the class and {DOORS}",
    "K2": f"{DOORS}; a record goes through from aipass.prax import append_jsonl; a transcript leaves the .log suffix",
    "K3": f"delete the helper and {DOORS}",
}
_STAMPS = frozenset({"strftime", "isoformat", "now", "utcnow", "ctime"})
_WRITE_FLAGS = ("O_APPEND", "O_WRONLY", "O_RDWR", "O_CREAT")
_HELPER_MAX_STATEMENTS = 6
#: The only calls a write wrapper makes; "" is a call on a call, as in getattr(logger, level)(...).
_HELPER_CALLS = frozenset({"write", "flush", "print", "getattr", "str", "format", "join", ""}) | _STAMPS


def _stdlib_imports(tree: ast.AST) -> List[Tuple[int, str]]:
    """K0: every import of logging or a logging submodule."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [(node.lineno, f"import {a.name}") for a in node.names if a.name.split(".")[0] == "logging"]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "logging" and not node.level:
            hits.append((node.lineno, f"from {node.module} import"))
    return [(line, f"stdlib logging ({what})") for line, what in hits]


def _level_classes(tree: ast.AST) -> List[Tuple[int, str]]:
    """K1: a class defining two or more level methods, whether or not its own body writes."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = {f.name for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
            levels = sorted(LEVELS & methods)
            if len(levels) >= 2:
                hits.append((node.lineno, f"class {node.name} defines {', '.join(levels)}: a logger outside prax"))
    return hits


def _names_a_log(node: ast.AST, names: Set[str], functions: Set[str]) -> bool:
    """Whether an expression holds a .log literal, a name bound to one, or a call to a function returning one."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.endswith(".log"):
            return True
        if isinstance(sub, ast.JoinedStr) and sub.values:
            last = sub.values[-1]
            if isinstance(last, ast.Constant) and str(last.value).endswith(".log"):
                return True
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in functions:
            return True
    return False


def _binds_a_log(node: ast.AST, names: Set[str], functions: Set[str]) -> bool:
    """Add what this one node binds to a .log path; True when it added something."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        fresh = {t.id for t in targets if isinstance(t, ast.Name)} - names
        if fresh and _names_a_log(node.value, names, functions):
            names.update(fresh)
            return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in functions:
        returns = [r.value for r in ast.walk(node) if isinstance(r, ast.Return) and r.value is not None]
        if any(_names_a_log(value, names, functions) for value in returns):
            functions.add(node.name)
            return True
    return False


def _log_names(tree: ast.AST) -> Tuple[Set[str], Set[str]]:
    """Module-wide: the names bound to a .log path and the functions that return one, to a fixpoint."""
    names: Set[str] = set()
    functions: Set[str] = set()
    while any([_binds_a_log(node, names, functions) for node in ast.walk(tree)]):
        pass
    return names, functions


def _mode(call: ast.Call, position: int) -> str:
    """The literal mode argument of an open call, or "" when it is not a literal."""
    mode = call.args[position] if len(call.args) > position else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    return mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) else ""


def _written_path(call: ast.Call) -> ast.AST | None:
    """The path a call opens for writing, or None when it is not a write."""
    func = call.func
    name = tail_name(func)
    if isinstance(func, ast.Name) and name == "open" and call.args:
        return call.args[0] if set(_mode(call, 1)) & set("awx+") else None
    if not isinstance(func, ast.Attribute):
        return None
    owner = func.value.id if isinstance(func.value, ast.Name) else ""
    if name == "open" and owner == "os" and len(call.args) > 1:
        return call.args[0] if any(flag in ast.dump(call.args[1]) for flag in _WRITE_FLAGS) else None
    if name == "open" and owner not in ("os", "io", "builtins"):
        return func.value if set(_mode(call, 0)) & set("awx+") else None
    if name in ("write_text", "write_bytes"):
        return func.value
    return None


def _log_writers(tree: ast.AST) -> List[Tuple[int, str]]:
    """K2: a file opened for writing whose path resolves, in this module, to a .log name."""
    names, functions = _log_names(tree)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            path = _written_path(node)
            if path is not None and _names_a_log(path, names, functions):
                hits.append((node.lineno, f"writes a .log file by hand ({ast.unparse(path)[:60]})"))
    return hits


def _stream(call: ast.Call) -> str:
    """'stderr' or 'stdout' for a write to that stream, 'console' for a print to the terminal, else ""."""
    func = call.func
    target = None
    if isinstance(func, ast.Attribute) and func.attr == "write":
        target = func.value
    elif tail_name(func) == "print":
        target = next((k.value for k in call.keywords if k.arg == "file"), None)
        if target is None:
            return "console"
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "sys":
        return target.attr if target.attr in ("stderr", "stdout") else ""
    return ""


def _is_helper_call(call: ast.Call) -> bool:
    """A call a write wrapper may make: a write, a stamp, string work, or a prax logger call."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in ("logger", "console"):
        return True
    return tail_name(func) in _HELPER_CALLS


def _stream_helpers(tree: ast.AST) -> List[Tuple[int, str]]:
    """K3: a write wrapper that sends its message to stderr, or prints it time-stamped.

    stdout is not a log channel here: a CLI's answer and a child's protocol both ride it.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in node.args.args + node.args.kwonlyargs if a.arg not in ("self", "cls")}
        body = node.body[1:] if ast.get_docstring(node) is not None else node.body
        if not params or not body or len(body) > _HELPER_MAX_STATEMENTS:
            continue
        calls = [c for c in ast.walk(node) if isinstance(c, ast.Call)]
        returns_value = any(isinstance(r, ast.Return) and r.value is not None for r in ast.walk(node))
        if returns_value or not all(_is_helper_call(c) for c in calls):
            continue
        stamped = any(tail_name(c.func) in _STAMPS for c in calls)
        for call in calls:
            stream = _stream(call)
            uses_param = any(isinstance(n, ast.Name) and n.id in params for a in call.args for n in ast.walk(a))
            if uses_param and (stream == "stderr" or (stream == "console" and stamped)):
                hits.append((node.lineno, f"function {node.name} writes log lines to {stream} by hand"))
                break
    return hits


def scan(tree: ast.AST) -> List[Tuple[int, str, str]]:
    """Every finding as (line, key, what), in line order."""
    found = [(line, "K0", what) for line, what in _stdlib_imports(tree)]
    found += [(line, "K1", what) for line, what in _level_classes(tree)]
    found += [(line, "K2", what) for line, what in _log_writers(tree)]
    found += [(line, "K3", what) for line, what in _stream_helpers(tree)]
    return sorted(found)


def _refused(message: str) -> Dict:
    """A file this checker could not judge scores 0 and says why."""
    return result(False, [{"name": "One logger", "passed": False, "message": message}], 0, STANDARD)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Convict every logger in a production file that is not prax. ``bypass_rules`` is read by nothing."""
    path = Path(module_path)
    if not path.exists():
        return _refused(f"File not found: {module_path}")
    source = read_text(path, tag=STANDARD_KEY)
    if source is None:
        return _refused(f"Error reading file: {module_path}")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[one_logger] Unparseable %s: %s", module_path, exc)
        return _refused(f"Unparseable source, not judged: {exc}")

    try:
        published = published_lists()
    except ValueError as exc:
        logger.error("[one_logger] %s", exc)
        return _refused(f"Not judged: {exc}")

    checks = []
    for line, key, what in scan(tree):
        why = allowed_by(path, key, published)
        tail = CURES[key] if why is None else f"allowed: {why}"
        checks.append(
            {
                "name": f"One logger {key}",
                "passed": why is not None,
                "key": key,
                "line": line,
                "message": f"{path.name}:{line} {what} - {tail}",
            }
        )
    convicted = [c for c in checks if not c["passed"]]
    if not checks:
        checks = [{"name": "One logger", "passed": True, "message": "No logger but prax"}]
    if convicted:
        json_handler.log_operation("check_completed", {"file": str(module_path), "score": 0, "standard": STANDARD_KEY})
    return result(not convicted, checks, 0 if convicted else 100, STANDARD)
