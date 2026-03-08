"""
Error Handling Standards Checker Handler

Validates module compliance with AIPass 3-tier logging standards.
Checks Prax imports in modules/handlers, logger calls in handlers.
"""

# =================== AIPass ====================
# Name: error_handling_check.py
# Description: Error Handling Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import re
from pathlib import Path
from typing import Dict, List

def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed"""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        # Must match standard
        if rule.get('standard') and rule.get('standard') != standard:
            continue
        # Must match file (check if rule file path is in the full path)
        rule_file = rule.get('file', '')
        if rule_file and rule_file not in file_path:
            continue
        # Check line-specific bypass
        rule_lines = rule.get('lines', [])
        if rule_lines and line is not None:
            if line in rule_lines:
                return True
        elif not rule_lines:
            return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows 3-tier error handling standards

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,           # Overall pass/fail
            'checks': [               # Individual check results
                {
                    'name': str,      # Check name
                    'passed': bool,   # Pass/fail
                    'message': str,   # Details
                }
            ],
            'score': int,             # 0-100 percentage
            'standard': str           # Standard name
        }
    """
    checks = []
    path = Path(module_path)

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, 'error_handling', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'ERROR_HANDLING'
        }

    # Validate file exists
    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'ERROR_HANDLING'
        }

    # Read file
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return {
            'passed': False,
            'checks': [{'name': 'File readable', 'passed': False, 'message': f'Error reading file: {e}'}],
            'score': 0,
            'standard': 'ERROR_HANDLING'
        }

    # Determine file type
    is_handler = '/handlers/' in module_path
    is_module = '/modules/' in module_path
    is_entry_point = path.name.endswith('.py') and '/apps/' in module_path and path.parent.name == 'apps'

    # Check 1: Modules MUST import Prax
    if is_module:
        prax_import_check = check_module_has_prax(content, module_path, bypass_rules)
        checks.append(prax_import_check)

    # Check 2: Handlers MUST NOT use stdlib logging.getLogger
    if is_handler:
        no_stdlib_check = check_handler_no_stdlib_logging(content, module_path, bypass_rules)
        checks.append(no_stdlib_check)

    # Check 4: Modules should have error logging
    if is_module:
        error_logging_check = check_module_error_logging(content)
        checks.append(error_logging_check)

    # Check 5: Modules - ERROR vs WARNING usage
    if is_module:
        error_warning_check = check_error_vs_warning_usage(lines, module_path, bypass_rules)
        checks.append(error_warning_check)

    # If not module or handler, skip checks
    if not is_module and not is_handler and not is_entry_point:
        return {
            'passed': True,
            'checks': [{'name': 'Error handling check', 'passed': True, 'message': 'Not a module or handler (skipped)'}],
            'score': 100,
            'standard': 'ERROR_HANDLING'
        }

    # Calculate score
    if not checks:
        return {
            'passed': True,
            'checks': [{'name': 'Error handling check', 'passed': True, 'message': 'No checks applicable'}],
            'score': 100,
            'standard': 'ERROR_HANDLING'
        }

    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'ERROR_HANDLING'
    }


def check_module_has_prax(content: str, file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that modules import Prax logger

    Modules MUST import Prax for business logging
    """
    has_prax_import = (
        'from aipass.prax import logger' in content
        or 'from aipass.prax import' in content and 'logger' in content
        or 'from aipass.prax.apps.modules.logger import system_logger' in content
    )

    if has_prax_import:
        return {
            'name': 'Module Prax import',
            'passed': True,
            'message': 'Module imports Prax logger (required for business logging)'
        }
    else:
        # Check if bypassed (whole file bypass for this check)
        if is_bypassed(file_path, 'error_handling', None, bypass_rules):
            return {
                'name': 'Module Prax import',
                'passed': True,
                'message': 'Module Prax import check bypassed'
            }
        return {
            'name': 'Module Prax import',
            'passed': False,
            'message': 'Module MUST import Prax: from aipass.prax import logger'
        }


def check_handler_no_stdlib_logging(content: str, file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that handlers do NOT use stdlib logging.getLogger().

    Handlers should use Prax system_logger instead. stdlib logging
    creates blind spots invisible to Prax monitor.
    """
    lines = content.split('\n')
    stdlib_lines = []

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings
        if '"""' in line or "'''" in line:
            in_docstring = not in_docstring
            continue

        # Skip if in docstring or comment
        if in_docstring or stripped.startswith('#'):
            continue

        # Check for stdlib logging.getLogger usage
        if re.search(r'logging\.getLogger\s*\(', line):
            if not is_bypassed(file_path, 'error_handling', i, bypass_rules):
                stdlib_lines.append(i)

    if stdlib_lines:
        return {
            'name': 'Handler stdlib logging',
            'passed': False,
            'message': f'Handler uses stdlib logging.getLogger() on lines {stdlib_lines[:3]} — use Prax system_logger instead'
        }
    else:
        return {
            'name': 'Handler stdlib logging',
            'passed': True,
            'message': 'Handler correctly avoids stdlib logging.getLogger()'
        }


def check_module_error_logging(content: str) -> Dict:
    """
    Check that modules have Prax logger available for error logging.

    Entry point @track_operation handles exception catching.
    Modules just need Prax import (checked separately).
    This check passes if Prax is imported - modules CAN log but aren't required to.
    """
    has_prax_import = 'from aipass.prax import logger' in content or (
        'from aipass.prax import' in content and 'logger' in content
    ) or 'from aipass.prax.apps.modules.logger import system_logger' in content

    if has_prax_import:
        return {
            'name': 'Module error logging',
            'passed': True,
            'message': 'Module has Prax logger available (entry point handles exceptions)'
        }
    else:
        # No Prax import - this is caught by check_module_has_prax
        # Still pass here to avoid double-flagging
        return {
            'name': 'Module error logging',
            'passed': True,
            'message': 'Module error logging deferred to Prax import check'
        }


def check_error_vs_warning_usage(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that logger.error() is used for system failures, not user input validation.

    User input validation (should be WARNING):
    - "not found", "invalid", "required", "missing", "does not exist"

    System failures (should be ERROR):
    - File I/O errors, crashes, dependency failures
    """
    # Patterns that indicate user input validation (should be warning, not error)
    user_input_patterns = [
        r'not\s+found',
        r'invalid',
        r'\brequired\b',
        r'\bmissing\b',
        r'does\s+not\s+exist',
        r'unable\s+to\s+find',
        r'no\s+such',
        r'doesn\'t\s+exist',
        r'not\s+exist',
    ]

    violations = []

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings
        if '"""' in line or "'''" in line:
            in_docstring = not in_docstring
            continue

        # Skip if in docstring or comment
        if in_docstring or stripped.startswith('#'):
            continue

        # Look for logger.error() calls
        if re.search(r'logger\.error\s*\(', line):
            # Check if the message contains user input patterns
            line_lower = line.lower()
            for pattern in user_input_patterns:
                if re.search(pattern, line_lower):
                    # Check if bypassed
                    if not is_bypassed(file_path, 'error_handling', i, bypass_rules):
                        violations.append(i)
                    break

    if violations:
        return {
            'name': 'ERROR vs WARNING usage',
            'passed': False,
            'message': f'logger.error() used for user input validation on lines {violations[:5]} - use logger.warning() instead'
        }
    else:
        return {
            'name': 'ERROR vs WARNING usage',
            'passed': True,
            'message': 'logger.error() correctly used for system failures only'
        }
