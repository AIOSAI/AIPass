# =================== AIPass ====================
# Name: log_visibility_check.py
# Description: Log Visibility Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Log Visibility Standards Checker Handler

Validates that logging output reaches system_logs/ for Prax monitor visibility.

TWO CHECKS:
1. ALL files using logging.getLogger() must also import prax system_logger
   (No handler exemption — unified Prax logging everywhere)
2. ANY file that creates logging.FileHandler writing to local paths (logs/,
   not system_logs/) creates blind spots invisible to Prax monitor

Prax logging infrastructure and test files are exempt from both checks.
"""

import sys
import re
from pathlib import Path
from typing import Dict, List
from aipass.seedgo.apps.handlers.json import json_handler

# Patterns built via concatenation to avoid self-detection by checkers
_GETLOGGER_PAT = r'logging' + r'\.getLogger\s*\('
_FILEHANDLER_PAT = r'logging' + r'\.FileHandler\s*\('
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
    Check if module's logging is visible to Prax monitor (system_logs/).

    Two checks:
    1. Modules using getLogger must also import prax system_logger
    2. Any file creating FileHandler to local paths creates blind spots

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict with passed, checks, score, standard
    """
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, 'log_visibility', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'LOG_VISIBILITY'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'LOG_VISIBILITY'
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
            'standard': 'LOG_VISIBILITY'
        }

    # Exempt prax logging infrastructure (it IS the implementation)
    if _is_prax_logging_infra(module_path):
        return {
            'passed': True,
            'checks': [{'name': 'Log visibility', 'passed': True, 'message': 'Prax logging infrastructure (exempt)'}],
            'score': 100,
            'standard': 'LOG_VISIBILITY'
        }

    # Exempt test files
    if path.name.startswith('test_') or path.name.endswith('_test.py') or '/tests/' in module_path:
        return {
            'passed': True,
            'checks': [{'name': 'Log visibility', 'passed': True, 'message': 'Test file (exempt)'}],
            'score': 100,
            'standard': 'LOG_VISIBILITY'
        }

    has_getlogger = bool(re.search(_GETLOGGER_PAT, content))
    has_filehandler = bool(re.search(_FILEHANDLER_PAT, content))

    # If file doesn't use logging at all, skip
    if not has_getlogger and not has_filehandler:
        return {
            'passed': True,
            'checks': [{'name': 'Log visibility', 'passed': True, 'message': 'No logging usage found (skipped)'}],
            'score': 100,
            'standard': 'LOG_VISIBILITY'
        }

    # CHECK 1: ALL files using getLogger must have prax import
    # (No handler exemption — unified Prax logging everywhere)
    if has_getlogger:
        check1 = _check_prax_import(lines, content, module_path, bypass_rules)
        checks.append(check1)

    # CHECK 2: ANY file creating FileHandler to local paths = blind spot
    if has_filehandler:
        check2 = _check_local_filehandler(lines, module_path, bypass_rules)
        checks.append(check2)

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "log_visibility"})
    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'LOG_VISIBILITY'
    }


def _is_prax_logging_infra(file_path: str) -> bool:
    """Check if file is part of prax logging infrastructure"""
    if 'prax' not in file_path:
        return False
    # Prax logging handlers and setup
    if '/logging/' in file_path or '/logger' in file_path:
        return True
    # Prax logger module
    if 'logger.py' in file_path:
        return True
    return False


def _check_prax_import(lines: List[str], content: str, file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check 1: Files using stdlib getLogger must also import prax system_logger.
    Applies to ALL files — no handler exemption.
    """
    has_prax_import = bool(re.search(
        r'from\s+aipass\.prax\.apps\.modules\.logger\s+import',
        content
    ))

    if has_prax_import:
        return {
            'name': 'Prax logger imported',
            'passed': True,
            'message': 'File imports prax system_logger alongside stdlib getLogger'
        }

    # Find violation lines
    violation_lines = _find_pattern_lines(
        lines, _GETLOGGER_PAT, file_path, bypass_rules
    )

    if violation_lines:
        return {
            'name': 'Prax logger imported',
            'passed': False,
            'message': f'stdlib getLogger() on lines {violation_lines[:5]} without prax system_logger import'
        }

    return {
        'name': 'Prax logger imported',
        'passed': True,
        'message': 'No stdlib getLogger() violations'
    }


def _check_local_filehandler(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check 2: Any file creating logging.FileHandler to local paths = blind spot.
    Applies to ALL files including handlers. No exemptions.
    If FileHandler points to system_logs/, it's visible. Otherwise it's blind.
    """
    # Find FileHandler creation lines
    violation_lines = _find_pattern_lines(
        lines, _FILEHANDLER_PAT, file_path, bypass_rules
    )

    if not violation_lines:
        return {
            'name': 'No local FileHandler',
            'passed': True,
            'message': 'No local-only FileHandler creating blind logs'
        }

    # Check if any FileHandler points to system_logs (which would be OK)
    # If ALL FileHandlers point to system_logs, pass
    blind_lines = []
    for line_num in violation_lines:
        # Check surrounding context (FileHandler path might be on previous/same line)
        context_start = max(0, line_num - 4)
        context_end = min(len(lines), line_num + 2)
        context = '\n'.join(lines[context_start:context_end])

        if 'system_logs' in context or 'system_log' in context:
            continue  # This FileHandler writes to system_logs — visible
        blind_lines.append(line_num)

    if blind_lines:
        return {
            'name': 'No local FileHandler',
            'passed': False,
            'message': f'FileHandler to local logs on lines {blind_lines[:5]} — invisible to Prax monitor'
        }

    return {
        'name': 'No local FileHandler',
        'passed': True,
        'message': 'FileHandler writes to system_logs (visible)'
    }


def _find_pattern_lines(lines: List[str], pattern: str, file_path: str, bypass_rules: list | None = None) -> List[int]:
    """Find lines matching a pattern, excluding docstrings and comments."""
    violation_lines = []
    in_docstring = False
    docstring_char = None

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                docstring_char = stripped[:3]
                if stripped.count(docstring_char) == 1:
                    in_docstring = True
                continue
        else:
            if docstring_char and docstring_char in stripped:
                in_docstring = False
            continue

        # Skip comments
        if stripped.startswith('#'):
            continue

        if re.search(pattern, line):
            if not is_bypassed(file_path, 'log_visibility', i, bypass_rules):
                violation_lines.append(i)

    return violation_lines
