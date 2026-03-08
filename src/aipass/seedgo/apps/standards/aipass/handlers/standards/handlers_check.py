"""
Handlers Standards Checker Handler

Validates handler compliance with AIPass handler standards.
Checks handler independence, auto-detection pattern, no orchestration.
"""

# =================== AIPass ====================
# Name: handlers_check.py
# Description: Handlers Standards Checker Handler
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
    Check if handler follows handler standards

    Args:
        module_path: Path to Python handler to check
        bypass_rules: Optional list of bypass rules to apply

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
    if is_bypassed(module_path, 'handlers', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'HANDLERS'
        }

    # Validate file exists
    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'HANDLERS'
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
            'standard': 'HANDLERS'
        }

    # Only check files in handlers/ directory
    is_handler = 'apps/handlers/' in module_path
    if not is_handler:
        return {
            'passed': True,
            'checks': [{'name': 'Handler check', 'passed': True, 'message': 'Not a handler file (skipped)'}],
            'score': 100,
            'standard': 'HANDLERS'
        }

    # Check 1: Handler independence (no cross-handler imports except defaults)
    independence_check = check_handler_independence(content, lines, module_path)
    checks.append(independence_check)

    # Check 2: Auto-detection pattern (if module_name parameter exists)
    auto_detect_check = check_auto_detection(content)
    if auto_detect_check:
        checks.append(auto_detect_check)

    # Check 3: No orchestration logic (handlers shouldn't import modules)
    orchestration_check = check_no_orchestration(content, lines)
    if orchestration_check:
        checks.append(orchestration_check)

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
        'standard': 'HANDLERS'
    }


def check_handler_independence(content: str, lines: List[str], module_path: str) -> Dict:
    """
    Check handler independence - no cross-handler imports except defaults

    Rules:
    - ALLOWED: from aipass.seedgo.apps.handlers.json import json_handler (default handler)
    - ALLOWED: from .decorators import catch_errors (same package)
    - FORBIDDEN: from aipass.seedgo.apps.handlers.error import error_handler (cross-handler)
    """
    forbidden_imports = []

    # Detect handler's own package
    # e.g., src/aipass/seedgo/apps/handlers/standards/cli_check.py -> package is 'standards'
    path_parts = Path(module_path).parts
    own_package = None
    for i, part in enumerate(path_parts):
        if part == 'handlers' and i + 1 < len(path_parts):
            own_package = path_parts[i + 1]
            break

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings (handle both single-line and multi-line)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote_marker = '"""' if stripped.startswith('"""') else "'''"
            # Count occurrences of the quote marker
            quote_count = stripped.count(quote_marker)
            if quote_count >= 2:
                # Single-line docstring (opening and closing on same line)
                continue  # Skip this line but don't toggle state
            else:
                # Multi-line docstring boundary
                in_docstring = not in_docstring

        # Skip docstrings, comments and empty lines
        if in_docstring or not stripped or stripped.startswith('#'):
            continue

        # Check for handler imports
        if 'apps.handlers' in stripped and ('from ' in stripped or 'import ' in stripped):
            # Skip if in a string (rough check)
            if '"from ' in stripped or "'from " in stripped:
                continue

            # Extract code part (before comment)
            code_part = stripped.split('#')[0] if '#' in stripped else stripped

            if 'apps.handlers' not in code_part:
                continue

            # Allowed: Default handlers (json_handler)
            if 'handlers.json import json_handler' in code_part:
                continue

            # Allowed: Same package imports (relative imports like "from .decorators")
            if code_part.strip().startswith('from .'):
                continue

            # Allowed: Same package absolute imports
            if own_package and f'handlers.{own_package}' in code_part:
                continue

            # Forbidden: Cross-handler imports
            forbidden_imports.append(f"line {i}: {stripped}")

    if forbidden_imports:
        return {
            'name': 'Handler independence',
            'passed': False,
            'message': f'Cross-handler imports detected (except defaults): {forbidden_imports[0]}'
        }

    return {
        'name': 'Handler independence',
        'passed': True,
        'message': 'No forbidden cross-handler imports detected'
    }


def check_auto_detection(content: str) -> Optional[Dict]:
    """
    Check for auto-detection pattern if handler accepts module_name

    If handler has module_name parameter, should use inspect.stack() auto-detection
    """
    # Check if any function accepts module_name parameter
    has_module_name_param = bool(re.search(r'def\s+\w+\([^)]*module_name', content))

    if not has_module_name_param:
        return None  # No module_name parameter, auto-detection not needed

    # Check for auto-detection implementation
    has_inspect_import = 'import inspect' in content
    has_stack_usage = 'inspect.stack()' in content
    has_auto_detect_function = '_get_caller_module_name' in content or 'get_caller' in content

    if has_auto_detect_function or (has_inspect_import and has_stack_usage):
        return {
            'name': 'Auto-detection pattern',
            'passed': True,
            'message': 'Auto-detection pattern implemented (inspect.stack())'
        }

    # Has module_name param but no auto-detection
    return {
        'name': 'Auto-detection pattern',
        'passed': False,
        'message': 'Has module_name parameter but missing auto-detection (use inspect.stack())'
    }


def check_no_orchestration(content: str, lines: List[str]) -> Optional[Dict]:
    """
    Check that handler doesn't import/call modules (orchestration)

    Handlers should be pure implementation, not orchestration.
    FORBIDDEN: from aipass.seedgo.apps.modules import some_module
    """
    module_imports = []

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings (handle both single-line and multi-line)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote_marker = '"""' if stripped.startswith('"""') else "'''"
            # Count occurrences of the quote marker
            quote_count = stripped.count(quote_marker)
            if quote_count >= 2:
                # Single-line docstring (opening and closing on same line)
                continue  # Skip this line but don't toggle state
            else:
                # Multi-line docstring boundary
                in_docstring = not in_docstring

        # Skip docstrings, comments and empty lines
        if in_docstring or not stripped or stripped.startswith('#'):
            continue

        # Check for module imports
        if 'apps.modules' in stripped and ('from ' in stripped or 'import ' in stripped):
            # Skip if in a string
            if '"from ' in stripped or "'from " in stripped:
                continue

            # Extract code part
            code_part = stripped.split('#')[0] if '#' in stripped else stripped

            if 'apps.modules' not in code_part:
                continue

            # Allowed: Service imports (prax.apps.modules.logger, cli.apps.modules)
            if 'prax.apps.modules.logger' in code_part or 'cli.apps.modules' in code_part:
                continue

            # Forbidden: Module imports (orchestration)
            module_imports.append(f"line {i}: {stripped}")

    if module_imports:
        return {
            'name': 'No orchestration',
            'passed': False,
            'message': f'Handler imports modules (orchestration): {module_imports[0]}'
        }

    return {
        'name': 'No orchestration',
        'passed': True,
        'message': 'No module imports detected (pure implementation)'
    }
