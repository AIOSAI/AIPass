"""
Log Level Hygiene Standards Checker Handler

Validates that ERROR level is reserved for system failures only,
and WARNING level is used for user input errors instead.

THE STANDARD:
- ERROR = System failures (crashes, timeouts, unhandled exceptions,
  import failures, file I/O errors, connection failures)
- WARNING = User input errors (unknown command, invalid arguments,
  missing required args, bad syntax, typos)
- INFO = Normal operations, successful completions, discoveries
"""

# =================== AIPass ====================
# Name: log_level_check.py
# Description: Log Level Hygiene Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import sys
import re
from pathlib import Path
from typing import Dict, List, Optional

def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed"""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get('standard') and rule.get('standard') != standard:
            continue
        rule_file = rule.get('file', '')
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get('lines', [])
        if rule_lines and line is not None:
            if line in rule_lines:
                return True
        elif not rule_lines:
            return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows log level hygiene standards

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': str
        }
    """
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, 'log_level', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'LOG_LEVEL'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'LOG_LEVEL'
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
            'standard': 'LOG_LEVEL'
        }

    # Only check files that use logger
    has_logger = re.search(r'\blogger\.(error|warning|info|debug)\s*\(', content)
    if not has_logger:
        return {
            'passed': True,
            'checks': [{'name': 'Log level check', 'passed': True, 'message': 'No logger calls found (skipped)'}],
            'score': 100,
            'standard': 'LOG_LEVEL'
        }

    # Check 1: ERROR not used for user input errors
    error_misuse_check = check_error_not_user_input(lines, module_path, bypass_rules=bypass_rules)
    checks.append(error_misuse_check)

    # Check 2: Unknown/unrecognized command patterns use WARNING
    command_routing_check = check_command_routing_level(content, lines, module_path, bypass_rules)
    if command_routing_check:
        checks.append(command_routing_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'LOG_LEVEL'
    }


def _get_non_code_lines(lines: List[str]) -> set:
    """
    Build a set of line numbers that are inside docstrings or comments.

    Uses AST-aware triple-quote counting: if a line has an even number of
    triple-quote delimiters it is self-contained (e.g. single-line docstring
    or string assignment). Only odd counts toggle the in-docstring state.
    """
    skip: set = set()
    in_docstring = False

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        triple_double = stripped.count('"""')
        triple_single = stripped.count("'''")
        total_triple = triple_double + triple_single

        if total_triple > 0 and total_triple % 2 == 1:
            in_docstring = not in_docstring
            skip.add(i)
            continue
        elif total_triple > 0 and total_triple % 2 == 0:
            skip.add(i)
            continue

        if in_docstring or stripped.startswith('#'):
            skip.add(i)

    return skip


def check_error_not_user_input(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that ERROR level is not used for user input validation.

    User input patterns (should be WARNING, not ERROR):
    - "unknown command", "invalid argument", "not found" (for user input),
      "unrecognized", "no such command", "bad syntax", "missing required"
    """
    user_input_patterns = [
        r'unknown\s+command',
        r'unknown\s+action',
        r'unrecognized',
        r'invalid\s+arg',
        r'invalid\s+command',
        r'invalid\s+option',
        r'bad\s+syntax',
        r'no\s+module\s+handled',
        r'not\s+a\s+valid\s+command',
        r'command\s+not\s+(found|recognized|supported)',
    ]

    violations = []
    skip_lines = _get_non_code_lines(lines)

    for i, line in enumerate(lines, 1):
        if i in skip_lines:
            continue

        if re.search(r'logger\.error\s*\(', line):
            line_lower = line.lower()
            for pattern in user_input_patterns:
                if re.search(pattern, line_lower):
                    if not is_bypassed(file_path, 'log_level', i, bypass_rules):
                        violations.append(i)
                    break

    if violations:
        return {
            'name': 'ERROR reserved for system failures',
            'passed': False,
            'message': f'ERROR level used for user input on lines {violations[:5]} - use WARNING level instead'
        }

    return {
        'name': 'ERROR reserved for system failures',
        'passed': True,
        'message': 'ERROR level correctly used for system failures only'
    }


def check_command_routing_level(content: str, lines: List[str], file_path: str, bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check that command routing failures use WARNING, not ERROR.

    Entry points and modules that route commands should log unrecognized
    commands as WARNING (user typed wrong thing) not ERROR (system broke).
    """
    has_command_routing = bool(re.search(r'(route_command|handle_command|args\.command)', content))
    if not has_command_routing:
        return None

    violations = []
    skip_lines = _get_non_code_lines(lines)

    for i, line in enumerate(lines, 1):
        if i in skip_lines:
            continue

        if re.search(r'logger\.error\s*\(', line):
            line_lower = line.lower()
            if re.search(r'(unknown\s+command|unrecognized|not\s+handled|no\s+module\s+handled)', line_lower):
                if not is_bypassed(file_path, 'log_level', i, bypass_rules):
                    violations.append(i)

    if violations:
        return {
            'name': 'Command routing uses WARNING',
            'passed': False,
            'message': f'Command routing failures logged as ERROR on lines {violations[:5]} - should be WARNING'
        }

    return {
        'name': 'Command routing uses WARNING',
        'passed': True,
        'message': 'Command routing failures correctly use WARNING level'
    }
