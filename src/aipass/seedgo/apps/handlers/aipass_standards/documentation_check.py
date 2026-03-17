# =================== AIPass ====================
# Name: documentation_check.py
# Description: Documentation Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Documentation Standards Checker Handler

Validates documentation compliance: module docstrings and function docstrings.
META block validation is handled separately by meta_check.py.
"""

import re
from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler


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
    Check if module follows documentation standards.

    Checks module-level docstrings and public function docstrings.

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional bypass rules

    Returns:
        dict with passed, checks, score, standard keys
    """
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, 'documentation', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'DOCUMENTATION'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'DOCUMENTATION'
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
            'standard': 'DOCUMENTATION'
        }

    # Skip __init__.py files
    if path.name == '__init__.py':
        return {
            'passed': True,
            'checks': [{'name': 'Documentation check', 'passed': True, 'message': '__init__.py file (skipped)'}],
            'score': 100,
            'standard': 'DOCUMENTATION'
        }

    # Check 1: Module-level docstring
    docstring_check = check_module_docstring(lines)
    checks.append(docstring_check)

    # Check 2: Function docstrings (for public functions)
    function_docs_check = check_function_docstrings(content, lines)
    if function_docs_check:
        checks.append(function_docs_check)

    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "documentation"})
    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'DOCUMENTATION'
    }


def check_module_docstring(lines: List[str]) -> Dict:
    """
    Check for module-level docstring.

    Looks for a triple-quoted string near the top of the file,
    allowing for META block, comments, or blank lines before it.
    """
    for line in lines[:30]:
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            return {
                'name': 'Module docstring',
                'passed': True,
                'message': 'Module-level docstring present'
            }

    return {
        'name': 'Module docstring',
        'passed': False,
        'message': 'Missing module-level docstring (expected within first 30 lines)'
    }


def check_function_docstrings(content: str, lines: List[str]) -> Dict | None:  # noqa: ARG001
    """
    Check that public functions have docstrings.

    Public functions (not starting with _) should have docstrings.
    """
    public_functions = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('def ') and not stripped.startswith('def _'):
            match = re.match(r'def\s+(\w+)\s*\(', stripped)
            if match:
                func_name = match.group(1)
                public_functions.append((func_name, i))

    if not public_functions:
        return None

    undocumented = []
    for func_name, line_num in public_functions:
        has_docstring = False
        for check_line in range(line_num, min(line_num + 5, len(lines) + 1)):
            if check_line - 1 < len(lines):
                check_stripped = lines[check_line - 1].strip()
                if check_stripped.startswith('"""') or check_stripped.startswith("'''"):
                    has_docstring = True
                    break
        if not has_docstring:
            undocumented.append(f'{func_name} (line {line_num})')

    if undocumented:
        return {
            'name': 'Function docstrings',
            'passed': False,
            'message': f'{len(undocumented)} public functions missing docstrings: {undocumented[0]}'
        }

    return {
        'name': 'Function docstrings',
        'passed': True,
        'message': f'All {len(public_functions)} public functions have docstrings'
    }
