"""
Permission Flags Standards Checker Handler

Validates that only the approved permission bypass pattern is used.
The ONLY acceptable permission flag is '--permission-mode bypassPermissions'.
Any other permission bypass pattern (e.g., --dangerously-skip-permissions,
--skip-permissions, --no-permissions) is a violation.

THE STANDARD:
- '--permission-mode bypassPermissions' is the AIPass standard
- '--dangerously-skip-permissions' is PROHIBITED
- Any other skip/bypass permission patterns are PROHIBITED
- Documentation files that mention these flags for reference are exempt
"""

# =================== AIPass ====================
# Name: permission_flags_check.py
# Description: Permission Flags Standards Checker Handler
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


def _get_non_code_lines(lines: List[str]) -> set:
    """
    Build a set of line numbers that are inside docstrings or comments.
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


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows permission flags standards

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

    if is_bypassed(module_path, 'permission_flags', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'PERMISSION_FLAGS'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'PERMISSION_FLAGS'
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
            'standard': 'PERMISSION_FLAGS'
        }

    # Skip files that don't reference any permission patterns
    has_permission_ref = re.search(
        r'skip.?permissions|dangerously.?skip|permission.?mode|bypass.?permission',
        content, re.IGNORECASE
    )
    if not has_permission_ref:
        return {
            'passed': True,
            'checks': [{'name': 'Permission flags check', 'passed': True, 'message': 'No permission flags found (skipped)'}],
            'score': 100,
            'standard': 'PERMISSION_FLAGS'
        }

    # Check 1: No dangerous skip-permissions flags
    dangerous_flags_check = check_no_dangerous_flags(lines, module_path, bypass_rules=bypass_rules)
    checks.append(dangerous_flags_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'PERMISSION_FLAGS'
    }


def check_no_dangerous_flags(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that no dangerous permission bypass flags are used.
    Only '--permission-mode bypassPermissions' is acceptable.
    """
    # Patterns that are PROHIBITED
    dangerous_patterns = [
        r'dangerously.?skip.?permissions',
        r'--skip.?permissions',
        r'--no.?permissions',
        r'allow.?dangerously.?skip',
    ]

    violations = []
    skip_lines = _get_non_code_lines(lines)

    for i, line in enumerate(lines, 1):
        if i in skip_lines:
            continue

        for pattern in dangerous_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                if not is_bypassed(file_path, 'permission_flags', i, bypass_rules):
                    violations.append(i)
                break

    if violations:
        return {
            'name': 'No dangerous permission flags',
            'passed': False,
            'message': f'Dangerous permission bypass flags on lines {violations[:5]} - use --permission-mode bypassPermissions instead'
        }

    return {
        'name': 'No dangerous permission flags',
        'passed': True,
        'message': 'Only approved permission flags used (--permission-mode bypassPermissions)'
    }
