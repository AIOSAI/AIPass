"""
Log Handler Standards Checker Handler

Validates that all logging handlers use RotatingFileHandler (via prax system_logger).
Plain logging.FileHandler and logging.StreamHandler writing to system_logs/ are prohibited
because they cause unbounded log growth that can crash the entire system.

THE STANDARD:
- All logging MUST use prax RotatingFileHandler (via system_logger import)
- No raw logging.FileHandler writing to log files
- No raw logging.StreamHandler writing to log files
- Prax's own logging infrastructure is exempt (it IS the implementation)
"""

# =================== AIPass ====================
# Name: log_handler_check.py
# Description: Log Handler Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import sys
import re
from pathlib import Path
from typing import Dict, List

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
    Check if module follows log handler standards

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

    if is_bypassed(module_path, 'log_handler', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'LOG_HANDLER'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'LOG_HANDLER'
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
            'standard': 'LOG_HANDLER'
        }

    # Skip files that don't set up logging handlers at all
    has_handler_setup = re.search(
        r'logging\.(FileHandler|StreamHandler)\s*\(|'
        r'\.addHandler\s*\(',
        content
    )
    if not has_handler_setup:
        return {
            'passed': True,
            'checks': [{'name': 'Log handler check', 'passed': True, 'message': 'No log handler setup found (skipped)'}],
            'score': 100,
            'standard': 'LOG_HANDLER'
        }

    # Exempt prax logging infrastructure (it IS the RotatingFileHandler implementation)
    if 'prax' in module_path and ('logging' in module_path or 'setup.py' in module_path or 'terminal' in module_path):
        return {
            'passed': True,
            'checks': [{'name': 'Log handler check', 'passed': True, 'message': 'Prax logging infrastructure (exempt)'}],
            'score': 100,
            'standard': 'LOG_HANDLER'
        }

    # Check 1: No raw logging.FileHandler
    file_handler_check = check_no_raw_file_handler(lines, module_path, bypass_rules=bypass_rules)
    checks.append(file_handler_check)

    # Check 2: No raw logging.StreamHandler for log files
    stream_handler_check = check_no_raw_stream_handler(lines, module_path, content, bypass_rules=bypass_rules)
    if stream_handler_check:
        checks.append(stream_handler_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'LOG_HANDLER'
    }


def check_no_raw_file_handler(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that no raw logging.FileHandler is used.
    Must use RotatingFileHandler instead.
    """
    violations = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments and docstrings
        if stripped.startswith('#'):
            continue

        # Detect logging.FileHandler (but not RotatingFileHandler)
        if re.search(r'logging\.FileHandler\s*\(', line):
            if not is_bypassed(file_path, 'log_handler', i, bypass_rules):
                violations.append(i)

    if violations:
        return {
            'name': 'No raw FileHandler',
            'passed': False,
            'message': f'Raw logging.FileHandler on lines {violations[:5]} - use RotatingFileHandler via prax system_logger'
        }

    return {
        'name': 'No raw FileHandler',
        'passed': True,
        'message': 'No raw logging.FileHandler found'
    }


def check_no_raw_stream_handler(lines: List[str], file_path: str, content: str, bypass_rules: list | None = None) -> Dict | None:
    """
    Check that logging.StreamHandler is not used for log file output.
    StreamHandler attached to loggers that also write to files indicates
    a logging setup that bypasses prax.
    """
    # Only flag StreamHandler if the file also sets up file-based logging
    has_file_logging = bool(re.search(
        r'logging\.(FileHandler|RotatingFileHandler)\s*\(|'
        r'system_logs|\.log["\']',
        content
    ))
    if not has_file_logging:
        return None

    violations = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue

        if re.search(r'logging\.StreamHandler\s*\(', line):
            if not is_bypassed(file_path, 'log_handler', i, bypass_rules):
                violations.append(i)

    if violations:
        return {
            'name': 'No raw StreamHandler with file logging',
            'passed': False,
            'message': f'Raw logging.StreamHandler with file logging on lines {violations[:5]} - use prax system_logger instead'
        }

    return {
        'name': 'No raw StreamHandler with file logging',
        'passed': True,
        'message': 'No raw StreamHandler with file logging found'
    }
