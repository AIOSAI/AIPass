# =================== AIPass ====================
# Name: trigger_check.py
# Description: Trigger Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Trigger Standards Checker Handler

Validates compliance with AIPass Trigger event bus standards:
- Correct import patterns for trigger
- No logger imports in event handlers
- No print statements in event handlers
- Proper event naming conventions

Valid bypass categories for .seedgo/bypass.json:
- handler_layer: Function in handlers/ layer (orchestrator fires instead)
- initialization: One-time setup/config creation
- internal_ops: Same-module internal operation
- high_frequency: Would create event spam
- utility: Helper called by event-firing function
"""

import re
from pathlib import Path
from typing import Dict, List, Optional
from aipass.seedgo.apps.handlers.json import json_handler

# Valid bypass categories for trigger standard
BYPASS_CATEGORIES = {
    'handler_layer': 'Function in handlers/ layer (orchestrator fires instead)',
    'initialization': 'One-time setup/config creation',
    'internal_ops': 'Same-module internal operation',
    'high_frequency': 'Would create event spam',
    'utility': 'Helper called by event-firing function',
}


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> tuple[bool, str | None, str | None]:
    """Check if a violation should be bypassed

    Args:
        file_path: Path to file being checked
        standard: Standard name (e.g., 'trigger')
        line: Optional specific line number
        bypass_rules: List of bypass rules from .seedgo/bypass.json

    Returns:
        tuple: (is_bypassed: bool, category: str | None, reason: str | None)
            - category is the bypass category if bypassed (handler_layer, initialization, etc.)
            - reason is the human-readable bypass reason
    """
    if not bypass_rules:
        return False, None, None
    for rule in bypass_rules:
        if rule.get('standard') and rule.get('standard') != standard:
            continue
        rule_file = rule.get('file', '')
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get('lines', [])
        if rule_lines and line is not None:
            if line in rule_lines:
                category = rule.get('category')
                reason = rule.get('reason')
                return True, category, reason
        elif not rule_lines:
            category = rule.get('category')
            reason = rule.get('reason')
            return True, category, reason
    return False, None, None


def is_handler_layer(file_path: str) -> bool:
    """Check if file is in the handlers/ layer

    Handler layer functions are typically called by modules which fire events.
    The handler itself shouldn't fire - that would be double-firing.
    """
    return '/handlers/' in file_path or '\\handlers\\' in file_path


def is_trigger_handler(file_path: str) -> bool:
    """Check if file is a trigger event handler"""
    return 'trigger' in file_path and 'handlers/events' in file_path


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows Trigger standards

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules for specific violations

    Returns:
        dict: {
            'passed': bool,
            'checks': [...],
            'score': int,
            'standard': str
        }
    """
    checks = []
    path = Path(module_path)

    # Check if entire standard is bypassed
    bypassed, category, reason = is_bypassed(module_path, 'trigger', bypass_rules=bypass_rules)
    if bypassed:
        bypass_msg = 'Standard bypassed via .seedgo/bypass.json'
        if category:
            bypass_msg += f' [category: {category}]'
        if reason:
            bypass_msg += f' - {reason}'
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': bypass_msg}],
            'score': 100,
            'standard': 'TRIGGER'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'TRIGGER'
        }

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return {
            'passed': False,
            'checks': [{'name': 'File readable', 'passed': False, 'message': f'Error reading file: {e}'}],
            'score': 0,
            'standard': 'TRIGGER'
        }

    is_handler = is_trigger_handler(module_path)

    # Check 1: For trigger handlers - no logger imports
    if is_handler:
        logger_check = check_no_logger_imports(content, lines, module_path)
        checks.append(logger_check)

    # Check 2: For trigger handlers - no print statements
    if is_handler:
        print_check = check_no_print_statements(content, lines, module_path)
        checks.append(print_check)

    # Check 3: For any file using trigger - correct import pattern
    trigger_import_check = check_trigger_import_pattern(content, lines, module_path)
    if trigger_import_check:
        checks.append(trigger_import_check)

    # Check 4: For trigger handlers - handler function naming
    if is_handler:
        naming_check = check_handler_naming(content, lines, module_path)
        if naming_check:
            checks.append(naming_check)

    # Check 5: Detect event patterns that should use trigger.fire() but don't
    # Skip trigger branch itself (it's the event bus)
    # Skip handler layer files - they are called by modules which fire events (handler_layer bypass category)
    if 'trigger/' not in module_path and 'trigger\\' not in module_path:
        if is_handler_layer(module_path):
            # Handler layer auto-bypass - modules fire events, not handlers
            checks.append({
                'name': 'Missing trigger events',
                'passed': True,
                'message': 'Handler layer file - module orchestrator fires events (auto-bypass: handler_layer)'
            })
        else:
            event_pattern_check = check_missing_trigger_events(content, lines, module_path)
            if event_pattern_check:
                checks.append(event_pattern_check)

    # If no checks apply, file is compliant
    if not checks:
        return {
            'passed': True,
            'checks': [{'name': 'Trigger check', 'passed': True, 'message': 'No trigger patterns to check'}],
            'score': 100,
            'standard': 'TRIGGER'
        }

    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "trigger"})
    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'TRIGGER'
    }


def check_no_logger_imports(_content: str, lines: List[str], _module_path: str) -> Dict:
    """
    Check that trigger handlers don't import Prax logger

    Logger imports in handlers cause infinite recursion:
    logger -> trigger -> handler -> logger -> ...
    """
    violations = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue

        # Check for prax logger imports
        if 'from prax' in stripped and 'logger' in stripped:
            violations.append(i)
        elif 'import prax' in stripped and 'logger' in stripped:
            violations.append(i)
        elif 'system_logger' in stripped and 'import' in stripped:
            violations.append(i)

    if violations:
        return {
            'name': 'No logger imports',
            'passed': False,
            'message': f'Handler imports Prax logger (causes recursion) on lines {violations[:3]}'
        }

    return {
        'name': 'No logger imports',
        'passed': True,
        'message': 'Handler correctly has no Prax logger imports'
    }


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

        if stripped.startswith('#'):
            continue

        # Check for print statements
        if re.search(r'(?<![.\w])print\s*\(', line):
            violations.append(i)

    if violations:
        return {
            'name': 'No print statements',
            'passed': False,
            'message': f'Handler uses print() (must be silent) on lines {violations[:3]}'
        }

    return {
        'name': 'No print statements',
        'passed': True,
        'message': 'Handler correctly has no print statements'
    }


def _is_trigger_branch(file_path: str) -> bool:
    """Check if a file belongs to the trigger branch itself.

    The trigger module is the source of trigger.fire() — it defines the
    event bus rather than consuming it, so it must not be required to
    import itself.
    """
    # Normalise Windows separators for a single check
    normalized = file_path.replace('\\', '/')
    # Match anything under the trigger branch's own tree
    return '/trigger/apps/' in normalized


def check_trigger_import_pattern(content: str, _lines: List[str], _module_path: str) -> Optional[Dict]:
    """
    Check for correct trigger import patterns

    Valid patterns:
    - from trigger import trigger
    - from trigger.apps.modules.core import trigger
    """
    # Only check files that use trigger
    if 'trigger' not in content.lower():
        return None

    # The trigger branch IS the event bus — it cannot import itself
    if _is_trigger_branch(_module_path):
        return {
            'name': 'Trigger import pattern',
            'passed': True,
            'message': 'Trigger branch file — self-reference, import not required'
        }

    # Check if trigger is imported
    has_trigger_import = False
    has_trigger_fire = 'trigger.fire(' in content

    # Valid import patterns (with optional aipass. prefix)
    valid_patterns = [
        r'from\s+(?:aipass\.)?trigger\s+import\s+trigger',
        r'from\s+(?:aipass\.)?trigger\.apps\.modules\.core\s+import\s+trigger',
        r'from\s+(?:aipass\.)?trigger\.apps\.modules\.core\s+import\s+trigger\s+as\s+\w+',
    ]

    for pattern in valid_patterns:
        if re.search(pattern, content):
            has_trigger_import = True
            break

    # Also check lazy-load pattern
    if '_trigger' in content and 'trigger.apps.modules.core' in content:
        has_trigger_import = True

    if has_trigger_fire and not has_trigger_import:
        return {
            'name': 'Trigger import pattern',
            'passed': False,
            'message': 'Uses trigger.fire() but missing proper import'
        }

    if has_trigger_import:
        return {
            'name': 'Trigger import pattern',
            'passed': True,
            'message': 'Correct trigger import pattern'
        }

    return None


def check_handler_naming(_content: str, lines: List[str], _module_path: str) -> Optional[Dict]:
    """
    Check that handler functions follow naming convention

    Pattern: handle_{event_name}(**kwargs)
    """
    handler_functions = []
    bad_handlers = []

    for i, line in enumerate(lines, 1):
        # Look for function definitions
        match = re.match(r'^def\s+(\w+)\s*\(', line)
        if match:
            func_name = match.group(1)
            # Skip private/internal functions
            if func_name.startswith('_'):
                continue
            # Check if it's a handler function
            if 'handle' in func_name.lower():
                handler_functions.append(func_name)
                # Check naming pattern
                if not func_name.startswith('handle_'):
                    bad_handlers.append(func_name)

    if not handler_functions:
        return None

    if bad_handlers:
        return {
            'name': 'Handler naming',
            'passed': False,
            'message': f'Handler functions should be handle_{{event}}: {bad_handlers}'
        }

    return {
        'name': 'Handler naming',
        'passed': True,
        'message': f'Handler functions correctly named: {handler_functions}'
    }


def check_missing_trigger_events(content: str, lines: List[str], _module_path: str) -> Optional[Dict]:
    """
    Detect event-like patterns that should use trigger.fire() but don't.

    Catches:
    - watchdog FileSystemEventHandler with on_created/on_deleted/on_modified
    - Lifecycle functions in modules AND handlers
    - Email/messaging patterns (deliver_*, send_*)
    - State change patterns (mark_*)

    Returns violations with line numbers for easy navigation.
    """
    violations = []
    has_trigger_fire = 'trigger.fire(' in content

    def find_pattern_lines(pattern: str) -> List[int]:
        """Find all line numbers where pattern matches"""
        matched_lines = []
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                matched_lines.append(i)
        return matched_lines

    # Pattern 1: watchdog FileSystemEventHandler without trigger
    if 'FileSystemEventHandler' in content and not has_trigger_fire:
        event_methods = ['on_created', 'on_deleted', 'on_modified', 'on_moved']
        for method in event_methods:
            pattern = rf'def\s+{method}\s*\('
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'FileSystemEventHandler.{method}() on lines {matched}')

    # Pattern 2: Lifecycle functions - check BOTH modules AND handlers
    # These are significant state changes that other systems care about
    lifecycle_patterns = [
        (r'def\s+create_\w+\s*\(', 'create_*'),
        (r'def\s+close_\w+\s*\(', 'close_*'),
        (r'def\s+delete_\w+\s*\(', 'delete_*'),
        (r'def\s+restore_\w+\s*\(', 'restore_*'),
    ]

    if not has_trigger_fire:
        for pattern, func_type in lifecycle_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_type} function on lines {matched}')

    # Pattern 3: Email/messaging patterns (common in ai_mail, other branches)
    messaging_patterns = [
        (r'def\s+deliver_\w+\s*\(', 'deliver_*'),
        (r'def\s+send_(?!notification)\w+\s*\(', 'send_*'),  # Exclude send_notification
    ]

    if not has_trigger_fire:
        for pattern, func_type in messaging_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_type} function on lines {matched}')

    # Pattern 4: State change patterns (mark_as_*, archive_*)
    state_patterns = [
        (r'def\s+mark_as_\w+\s*\(', 'mark_as_*'),
        (r'def\s+archive_\w+\s*\(', 'archive_*'),
    ]

    if not has_trigger_fire:
        for pattern, func_type in state_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_type} function on lines {matched}')

    # Pattern 5: Registry/JSON update patterns (significant state changes)
    # These modify shared state that other systems care about
    registry_patterns = [
        (r'def\s+save_registry\s*\(', 'save_registry'),
        (r'def\s+add_registry_entry\s*\(', 'add_registry_entry'),
        (r'def\s+remove_registry_entry\s*\(', 'remove_registry_entry'),
        (r'def\s+sync_\w*registry\s*\(', 'sync_*registry'),
        (r'def\s+update_registry\s*\(', 'update_registry'),
        (r'def\s+synchronize_registry\s*\(', 'synchronize_registry'),
        (r'def\s+ping_registry\s*\(', 'ping_registry'),
    ]

    if not has_trigger_fire:
        for pattern, func_name in registry_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_name} on lines {matched}')

    # Pattern 6: Central file operations (cross-branch shared state)
    central_patterns = [
        (r'def\s+update_central\s*\(', 'update_central'),
        (r'def\s+write_central\w*\s*\(', 'write_central_*'),
        (r'def\s+push_to_central\s*\(', 'push_to_central'),
        (r'def\s+aggregate_central\s*\(', 'aggregate_central'),
    ]

    if not has_trigger_fire:
        for pattern, func_name in central_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_name} on lines {matched}')

    # Pattern 7: Auto-repair and recovery operations
    repair_patterns = [
        (r'def\s+_?auto_close_\w+\s*\(', 'auto_close_*'),
        (r'def\s+recover_\w+\s*\(', 'recover_*'),
        (r'def\s+_?heal_\w+\s*\(', 'heal_*'),
    ]

    if not has_trigger_fire:
        for pattern, func_name in repair_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_name} on lines {matched}')

    # Pattern 8: Cleanup and backup operations (state deletion/preservation)
    cleanup_patterns = [
        (r'def\s+cleanup_\w+\s*\(', 'cleanup_*'),
        (r'def\s+backup_\w+\s*\(', 'backup_*'),
    ]

    if not has_trigger_fire:
        for pattern, func_name in cleanup_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_name} on lines {matched}')

    # Pattern 9: System lifecycle (initialize/shutdown entire systems)
    lifecycle_system_patterns = [
        (r'def\s+initialize_\w+_system\s*\(', 'initialize_*_system'),
        (r'def\s+shutdown_\w+_system\s*\(', 'shutdown_*_system'),
    ]

    if not has_trigger_fire:
        for pattern, func_name in lifecycle_system_patterns:
            matched = find_pattern_lines(pattern)
            if matched:
                violations.append(f'{func_name} on lines {matched}')

    # Pattern 10: Inline filesystem operations (method calls, not function defs)
    # These directly modify filesystem state - file deletions and moves
    if not has_trigger_fire:
        # .unlink() - file deletion
        unlink_lines = find_pattern_lines(r'\.\s*unlink\s*\(')
        if unlink_lines:
            violations.append(f'.unlink() file deletion on lines {unlink_lines}')

        # .rename() - file move/rename
        rename_lines = find_pattern_lines(r'\.\s*rename\s*\(')
        if rename_lines:
            violations.append(f'.rename() file move on lines {rename_lines}')

    if not violations:
        return None

    return {
        'name': 'Missing trigger events',
        'passed': False,
        'message': f'Missing trigger.fire(): {"; ".join(violations)}'
    }
