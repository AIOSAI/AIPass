"""
Testing Standards Checker Handler

Validates testing compliance with AIPass testing standards.
Checks for test functions, error handling patterns.
Note: Manual testing is acceptable in current rapid iteration phase.
"""

# =================== AIPass ====================
# Name: testing_check.py
# Description: Testing Standards Checker Handler
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
    Check if module follows testing standards

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
    if is_bypassed(module_path, 'testing', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'TESTING'
        }

    # Validate file exists
    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'TESTING'
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
            'standard': 'TESTING'
        }

    # Check 1: Error handling presence (for non-test files)
    is_test_file = path.name.startswith('test_') or path.name.startswith('test.')
    if not is_test_file:
        error_handling_check = check_error_handling(content, lines)
        if error_handling_check:
            checks.append(error_handling_check)

    # Check 2: Test functions (if it's a test file)
    if is_test_file:
        test_functions_check = check_test_functions(content)
        checks.append(test_functions_check)

    # If no checks were added, testing standard doesn't apply (passes)
    if not checks:
        return {
            'passed': True,
            'checks': [{'name': 'Testing check', 'passed': True, 'message': 'Manual testing acceptable (no automated tests required)'}],
            'score': 100,
            'standard': 'TESTING'
        }

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'TESTING'
    }


def check_error_handling(content: str, lines: List[str]) -> Optional[Dict]:
    """
    Check for proper error handling patterns

    Good: try/except with logging or return values
    Bad: Silent failures (bare except: pass)
    """
    # Count try/except blocks
    try_count = content.count('try:')
    except_count = content.count('except')

    if try_count == 0:
        # No error handling, but that's acceptable (not all code needs it)
        return None

    # Check for silent failures (except: pass or except Exception: pass)
    silent_failures = []
    in_docstring = False
    in_except = False
    except_line = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track docstrings (skip single-line docstrings)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Check if it's a single-line docstring (opens and closes on same line)
            quote = '"""' if stripped.startswith('"""') else "'''"
            if stripped.count(quote) == 2 and len(stripped) > len(quote) * 2:
                # Single-line docstring, don't toggle
                pass
            else:
                in_docstring = not in_docstring

        # Skip docstrings
        if in_docstring:
            continue

        # Track except blocks
        if 'except' in stripped and ':' in stripped:
            in_except = True
            except_line = i
            continue

        # Check if except block only has pass
        if in_except:
            # Check if line is just 'pass' or 'pass' with a comment
            if stripped == 'pass' or stripped.startswith('pass ') or stripped.startswith('pass#'):
                # Check if this is the only statement in except block
                # Look ahead to see if next non-empty line is dedented
                is_silent = True
                for j in range(i, min(i + 3, len(lines))):
                    next_line = lines[j].strip()
                    # Check if line is not a pass statement (with or without comment)
                    is_pass_line = next_line == 'pass' or next_line.startswith('pass ') or next_line.startswith('pass#')
                    if next_line and not is_pass_line:
                        # Has other statements, not silent
                        if lines[j].startswith(' ') and len(lines[j]) - len(lines[j].lstrip()) > len(line) - len(line.lstrip()):
                            is_silent = False
                        break

                if is_silent:
                    silent_failures.append(f"line {except_line}")

            # Reset except tracking when we leave the block (check original line, not stripped)
            if line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                in_except = False

    if silent_failures:
        return {
            'name': 'Error handling',
            'passed': False,
            'message': f'Silent failure detected (except: pass) at {silent_failures[0]} - errors should log/return'
        }

    return {
        'name': 'Error handling',
        'passed': True,
        'message': f'Error handling present ({try_count} try/except blocks with proper handling)'
    }


def check_test_functions(content: str) -> Dict:
    """
    Check that test files have test functions

    Test files should have functions starting with test_
    """
    # Count test functions
    test_functions = re.findall(r'def\s+(test_\w+)\s*\(', content)

    if not test_functions:
        return {
            'name': 'Test functions',
            'passed': False,
            'message': 'Test file has no test functions (should have def test_* functions)'
        }

    return {
        'name': 'Test functions',
        'passed': True,
        'message': f'Test file has {len(test_functions)} test functions'
    }
