# =================== AIPass ====================
# Name: trigger_check.py
# Description: Trigger Standards Checker Handler
# Version: 1.0.1
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
Trigger Standards Checker Handler

Reference: trigger.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import matching_rule
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

# Production only: a test deleting its own temp file is not a system state change,
# and a test that fired real events would pollute the bus for everyone else.
APPLIES_TO = "production"

BYPASS_CATEGORIES = {
    "handler_layer": "Function in handlers/ layer (orchestrator fires instead)",
    "initialization": "One-time setup/config creation",
    "internal_ops": "Same-module internal operation",
    "high_frequency": "Would create event spam",
    "utility": "Helper called by event-firing function",
}


def is_handler_layer(file_path: str) -> bool:
    """Check if file is in the handlers/ layer

    The calling module fires; a handler firing too would double-fire.
    """
    return "/handlers/" in file_path or "\\handlers\\" in file_path


def is_trigger_handler(file_path: str) -> bool:
    """Check if file is a trigger event handler"""
    return "trigger" in file_path and "handlers/events" in file_path


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows Trigger standards"""
    checks = []
    path = Path(module_path)

    # File-wide gate, so no line= is passed: forwarding one would advertise scope
    # support to the inert-rule map that no caller exercises.
    rule = matching_rule(module_path, "trigger", bypass_rules=bypass_rules)
    if rule is not None:
        category, reason = rule.get("category"), rule.get("reason")
        bypass_msg = "Standard bypassed via .seedgo/bypass.json"
        if category:
            bypass_msg += f" [category: {category}]"
        if reason:
            bypass_msg += f" - {reason}"
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": bypass_msg}],
            "score": 100,
            "standard": "TRIGGER",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "TRIGGER",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "TRIGGER",
        }

    is_handler = is_trigger_handler(module_path)

    if is_handler:
        logger_check = check_no_logger_imports(content, lines, module_path)
        checks.append(logger_check)

    if is_handler:
        print_check = check_no_print_statements(content, lines, module_path)
        checks.append(print_check)

    trigger_import_check = check_trigger_import_pattern(content, lines, module_path)
    if trigger_import_check:
        checks.append(trigger_import_check)

    if is_handler:
        naming_check = check_handler_naming(content, lines, module_path)
        if naming_check:
            checks.append(naming_check)

    # The trigger branch is the event bus itself; handler-layer files are fired for by their module.
    if "trigger/" not in module_path and "trigger\\" not in module_path:
        if is_handler_layer(module_path):
            checks.append(
                {
                    "name": "Missing trigger events",
                    "passed": True,
                    "message": "Handler layer file - module orchestrator fires events (auto-bypass: handler_layer)",
                }
            )
        else:
            event_pattern_check = check_missing_trigger_events(content, lines, module_path)
            if event_pattern_check:
                checks.append(event_pattern_check)

    if not checks:
        return {
            "passed": True,
            "checks": [{"name": "Trigger check", "passed": True, "message": "No trigger patterns to check"}],
            "score": 100,
            "standard": "TRIGGER",
        }

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "trigger"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "TRIGGER"}


def check_no_logger_imports(_content: str, lines: List[str], _module_path: str) -> Dict:
    """
    Check that trigger handlers don't import Prax logger

    Logger imports in handlers recurse: logger -> trigger -> handler -> logger.
    """
    violations = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        if "from prax" in stripped and "logger" in stripped:
            violations.append(i)
        elif "import prax" in stripped and "logger" in stripped:
            violations.append(i)
        elif "system_logger" in stripped and "import" in stripped:
            violations.append(i)

    if violations:
        return {
            "name": "No logger imports",
            "passed": False,
            "message": f"Handler imports Prax logger (causes recursion) on lines {violations[:3]}",
        }

    return {"name": "No logger imports", "passed": True, "message": "Handler correctly has no Prax logger imports"}


def check_no_print_statements(_content: str, lines: List[str], _module_path: str) -> Dict:
    """
    Check that trigger handlers don't use print()

    Handlers must be silent - events are logged by trigger.fire()
    """
    violations = []
    in_main_block = False
    main_block_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if line.strip() else 0

        # Track __main__ blocks (print OK there for testing)
        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue

        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        if in_main_block:
            continue

        if stripped.startswith("#"):
            continue

        if re.search(r"(?<![.\w])print\s*\(", line):
            violations.append(i)

    if violations:
        return {
            "name": "No print statements",
            "passed": False,
            "message": f"Handler uses print() (must be silent) on lines {violations[:3]}",
        }

    return {"name": "No print statements", "passed": True, "message": "Handler correctly has no print statements"}


def _is_trigger_branch(file_path: str) -> bool:
    """Check if a file belongs to the trigger branch itself.

    It defines trigger.fire(), so it must not be required to import itself.
    """
    normalized = file_path.replace("\\", "/")
    return "/trigger/apps/" in normalized


def check_trigger_import_pattern(content: str, _lines: List[str], _module_path: str) -> Optional[Dict]:
    """Check for correct trigger import patterns"""
    if "trigger" not in content.lower():
        return None

    if _is_trigger_branch(_module_path):
        return {
            "name": "Trigger import pattern",
            "passed": True,
            "message": "Trigger branch file — self-reference, import not required",
        }

    has_trigger_import = False
    has_trigger_fire = "trigger.fire(" in content

    valid_patterns = [
        r"from\s+aipass\.trigger\.apps\.modules\.core\s+import\s+trigger\b",
        r"from\s+aipass\.trigger\.apps\.modules\s+import\s+(?:core|trigger)\b",
    ]

    for pattern in valid_patterns:
        if re.search(pattern, content):
            has_trigger_import = True
            break

    if "_trigger" in content and "trigger.apps.modules.core" in content:
        has_trigger_import = True

    if has_trigger_fire and not has_trigger_import:
        return {
            "name": "Trigger import pattern",
            "passed": False,
            "message": "Uses trigger.fire() but missing proper import",
        }

    if has_trigger_import:
        return {"name": "Trigger import pattern", "passed": True, "message": "Correct trigger import pattern"}

    return None


def check_handler_naming(_content: str, lines: List[str], _module_path: str) -> Optional[Dict]:
    """
    Check that handler functions follow naming convention

    Pattern: handle_{event_name}(**kwargs)
    """
    handler_functions = []
    bad_handlers = []

    for i, line in enumerate(lines, 1):
        match = re.match(r"^def\s+(\w+)\s*\(", line)
        if match:
            func_name = match.group(1)
            if func_name.startswith("_"):
                continue
            if "handle" in func_name.lower():
                handler_functions.append(func_name)
                if not func_name.startswith("handle_"):
                    bad_handlers.append(func_name)

    if not handler_functions:
        return None

    if bad_handlers:
        return {
            "name": "Handler naming",
            "passed": False,
            "message": f"Handler functions should be handle_{{event}}: {bad_handlers}",
        }

    return {
        "name": "Handler naming",
        "passed": True,
        "message": f"Handler functions correctly named: {handler_functions}",
    }


def _fires_trigger(node: ast.AST) -> bool:
    """Whether this AST subtree contains a trigger.fire(...) call.

    A nested def counts as its parent's fire. The receiver is matched by name
    because the bus is reached as ``trigger``, ``_trigger`` and ``get_trigger()``.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "fire":
            try:
                receiver = ast.unparse(sub.func.value)
            except Exception as e:  # pragma: no cover - unparse is total on parsed trees
                logger.info("[trigger_check] could not unparse fire receiver: %s", e)
                receiver = ""
            if "trigger" in receiver.lower():
                return True
    return False


def _called_names(node: ast.AST) -> set:
    """Every name this subtree calls, attribute calls reduced to the attribute."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _function_index(content: str) -> Optional[List[Dict]]:
    """Every def in the module with its line span and whether it satisfies the standard.

    ``satisfied``: the function fires in its own body or calls, in ONE hop, a
    same-module function that does; delegation to a local firer is correct code.
    None when the file does not parse: the caller falls back to the file-level flag.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as e:
        logger.info("[trigger_check] unparseable module, falling back to file-level flag: %s", e)
        return None

    functions: List[Dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "start": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno) or node.lineno,
                    "fires": _fires_trigger(node),
                    "calls": _called_names(node),
                }
            )

    firers = {f["name"] for f in functions if f["fires"]}
    for f in functions:
        f["satisfied"] = f["fires"] or bool(f["calls"] & firers)
    return functions


def _function_at(functions: Optional[List[Dict]], line: int) -> Optional[Dict]:
    """The function whose ``def`` is on this line, if any.

    None when the regex matched something that is not a real def -- a string,
    a comment, a docstring example. Those keep the file-level answer.
    """
    if functions is None:
        return None
    for f in functions:
        if f["start"] == line:
            return f
    return None


def _enclosing_function(functions: Optional[List[Dict]], line: int) -> Optional[Dict]:
    """The innermost function containing this line, or None at module level."""
    if functions is None:
        return None
    best = None
    for f in functions:
        if f["start"] <= line <= f["end"] and (best is None or f["start"] > best["start"]):
            best = f
    return best


def check_missing_trigger_events(content: str, lines: List[str], _module_path: str) -> Optional[Dict]:
    """
    Detect event-like patterns that should use trigger.fire() but don't.

    The exemption is per function body: a fire in A never exempts B. Pattern 10's
    unit is the enclosing function; module level and unparseable files stay file-level.
    """
    violations = []
    has_trigger_fire = "trigger.fire(" in content
    functions = _function_index(content)

    def find_pattern_lines(pattern: str, inline: bool = False) -> List[int]:
        """Lines matching pattern whose OWN function does not fire.

        inline=False anchors on the def line the regex matched; inline=True
        (Pattern 10) anchors on the innermost function enclosing the line.
        """
        matched_lines = []
        for i, line in enumerate(lines, 1):
            if not re.search(pattern, line):
                continue
            owner = _enclosing_function(functions, i) if inline else _function_at(functions, i)
            if not (owner["satisfied"] if owner else has_trigger_fire):
                matched_lines.append(i)
        return matched_lines

    # Pattern 1: watchdog FileSystemEventHandler. The class marker gates the file;
    # the exemption is per METHOD, so on_created firing does not excuse on_deleted.
    if "FileSystemEventHandler" in content:
        event_methods = ["on_created", "on_deleted", "on_modified", "on_moved"]
        for method in event_methods:
            pattern = rf"def\s+{method}\s*\("
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f"FileSystemEventHandler.{method}() on lines {matched}")

    lifecycle_patterns = [
        (r"def\s+create_\w+\s*\(", "create_*"),
        (r"def\s+close_\w+\s*\(", "close_*"),
        (r"def\s+delete_\w+\s*\(", "delete_*"),
        (r"def\s+restore_\w+\s*\(", "restore_*"),
    ]

    for pattern, func_type in lifecycle_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_type} function on lines {matched}")

    messaging_patterns = [
        (r"def\s+deliver_\w+\s*\(", "deliver_*"),
        (r"def\s+send_(?!notification)\w+\s*\(", "send_*"),  # Exclude send_notification
    ]

    for pattern, func_type in messaging_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_type} function on lines {matched}")

    state_patterns = [
        (r"def\s+mark_as_\w+\s*\(", "mark_as_*"),
        (r"def\s+archive_\w+\s*\(", "archive_*"),
    ]

    for pattern, func_type in state_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_type} function on lines {matched}")

    registry_patterns = [
        (r"def\s+save_registry\s*\(", "save_registry"),
        (r"def\s+add_registry_entry\s*\(", "add_registry_entry"),
        (r"def\s+remove_registry_entry\s*\(", "remove_registry_entry"),
        (r"def\s+sync_\w*registry\s*\(", "sync_*registry"),
        (r"def\s+update_registry\s*\(", "update_registry"),
        (r"def\s+synchronize_registry\s*\(", "synchronize_registry"),
        (r"def\s+ping_registry\s*\(", "ping_registry"),
    ]

    for pattern, func_name in registry_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_name} on lines {matched}")

    central_patterns = [
        (r"def\s+update_central\s*\(", "update_central"),
        (r"def\s+write_central\w*\s*\(", "write_central_*"),
        (r"def\s+push_to_central\s*\(", "push_to_central"),
        (r"def\s+aggregate_central\s*\(", "aggregate_central"),
    ]

    for pattern, func_name in central_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_name} on lines {matched}")

    repair_patterns = [
        (r"def\s+_?auto_close_\w+\s*\(", "auto_close_*"),
        (r"def\s+recover_\w+\s*\(", "recover_*"),
        (r"def\s+_?heal_\w+\s*\(", "heal_*"),
    ]

    for pattern, func_name in repair_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_name} on lines {matched}")

    cleanup_patterns = [
        (r"def\s+cleanup_\w+\s*\(", "cleanup_*"),
        (r"def\s+backup_\w+\s*\(", "backup_*"),
    ]

    for pattern, func_name in cleanup_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_name} on lines {matched}")

    lifecycle_system_patterns = [
        (r"def\s+initialize_\w+_system\s*\(", "initialize_*_system"),
        (r"def\s+shutdown_\w+_system\s*\(", "shutdown_*_system"),
    ]

    for pattern, func_name in lifecycle_system_patterns:
        matched = find_pattern_lines(pattern)
        if matched:
            violations.append(f"{func_name} on lines {matched}")

    # Pattern 10: Inline .unlink()/.rename(); no def to anchor on, so the unit is the enclosing function.
    unlink_lines = find_pattern_lines(r"\.\s*unlink\s*\(", inline=True)
    if unlink_lines:
        violations.append(f".unlink() file deletion on lines {unlink_lines}")

    rename_lines = find_pattern_lines(r"\.\s*rename\s*\(", inline=True)
    if rename_lines:
        violations.append(f".rename() file move on lines {rename_lines}")

    if not violations:
        return None

    return {
        "name": "Missing trigger events",
        "passed": False,
        "message": f"Missing trigger.fire(): {'; '.join(violations)}",
    }
