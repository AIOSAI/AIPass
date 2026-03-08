"""
CLI Flags Standards Checker Handler

Validates that branch entry points support required CLI flags.

THE STANDARD (Tier 1 - Required):
- --version / -V  = Print branch name and version, then exit

Note: --help is already checked by cli_check.py, so it is NOT re-checked here.

Only entry point files are checked (files directly in apps/, not in
apps/handlers/ or apps/modules/). Non-entry-point files are skipped
with a pass.
"""

# =================== AIPass ====================
# Name: cli_flags_check.py
# Description: CLI Flags Standards Checker Handler
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
    Check if module follows CLI flags standards

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

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, 'cli_flags', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'CLI_FLAGS'
        }

    # Validate file exists
    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'CLI_FLAGS'
        }

    # Only check entry point files — files whose parent directory is "apps"
    if path.parent.name != 'apps':
        return {
            'passed': True,
            'checks': [{'name': 'Entry point check', 'passed': True, 'message': 'Not an entry point (skipped)'}],
            'score': 100,
            'standard': 'CLI_FLAGS'
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
            'standard': 'CLI_FLAGS'
        }

    # Check 1: --version / -V flag support
    version_flag_check = check_version_flag(lines, module_path, bypass_rules)
    checks.append(version_flag_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'CLI_FLAGS'
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


def check_version_flag(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that the entry point supports --version / -V flag.

    Scans non-comment/non-docstring lines for string literals:
    - '--version' or "--version"
    - '-V' or "-V"

    If either pattern is found, the check passes.
    """
    if is_bypassed(file_path, 'cli_flags', None, bypass_rules):
        return {
            'name': '--version flag support',
            'passed': True,
            'message': 'Bypassed by bypass rules'
        }

    skip_lines = _get_non_code_lines(lines)

    # Patterns to detect version flag handling in code
    version_patterns = [
        r"""['"]--version['"]""",
        r"""['"]-V['"]""",
    ]

    for i, line in enumerate(lines, 1):
        if i in skip_lines:
            continue

        for pattern in version_patterns:
            if re.search(pattern, line):
                return {
                    'name': '--version flag support',
                    'passed': True,
                    'message': f'Found version flag handling on line {i}'
                }

    return {
        'name': '--version flag support',
        'passed': False,
        'message': 'Entry point missing --version / -V flag support'
    }
