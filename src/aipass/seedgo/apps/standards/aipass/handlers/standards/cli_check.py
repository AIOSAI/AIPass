"""
CLI Standards Checker Handler

Validates module compliance with AIPass CLI standards.
Checks console.print() usage, CLI service imports, handler separation.
"""

# =================== AIPass ====================
# Name: cli_check.py
# Description: CLI Standards Checker Handler
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
    Check if module follows CLI standards

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules for specific violations

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
    if is_bypassed(module_path, 'cli', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'CLI'
        }

    # Validate file exists
    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'CLI'
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
            'standard': 'CLI'
        }

    # Determine file type (handle both absolute and relative paths)
    is_handler = 'handlers/' in module_path
    is_module = 'modules/' in module_path
    is_entry_point = path.name.endswith('.py') and 'apps/' in module_path and path.parent.name == 'apps'

    # Check 1: Handler separation (handlers must NOT have console output)
    if is_handler:
        handler_separation_check = check_handler_separation(content)
        checks.append(handler_separation_check)

    # Check 2: CLI service imports (modules/entry points should use CLI services)
    if is_module or is_entry_point:
        cli_imports_check = check_cli_imports(content, module_path)
        if cli_imports_check:
            checks.append(cli_imports_check)

    # Check 3: No bare print() statements (modules should use console.print())
    if is_module or is_entry_point:
        print_usage_check = check_print_usage(content, lines, module_path)
        if print_usage_check:
            checks.append(print_usage_check)

    # Check 4: --help flag support (modules should have --help)
    if is_module or is_entry_point:
        help_flag_check = check_help_flag(content)
        if help_flag_check:
            checks.append(help_flag_check)

    # Check 5: No duplicate display functions (use CLI service instead)
    if is_module or is_entry_point:
        duplicate_display_check = check_duplicate_display_functions(content, module_path)
        if duplicate_display_check:
            checks.append(duplicate_display_check)

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
        'standard': 'CLI'
    }


def check_handler_separation(content: str) -> Dict:
    """
    Check that handlers don't have console output

    Handlers should return data, modules should handle display
    Only checks actual code (not strings or comments)
    Excludes: if __name__ == '__main__': blocks (test/debug code is OK)
    """
    lines = content.split('\n')

    # Find code section boundaries (skip docstrings and comments)
    in_docstring = False
    console_print_lines = []
    cli_import_lines = []
    print_lines = []

    # Track if we're inside an if __name__ == '__main__': block
    in_main_block = False
    main_block_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if line.strip() else 0

        # Detect entry into if __name__ == '__main__': block
        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue

        # Detect exit from if __name__ == '__main__': block
        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        # Skip checking if we're inside the __main__ block (test/debug code)
        if in_main_block:
            continue

        # Track docstrings (handle single-line docstrings correctly)
        triple_double = line.count('"""')
        triple_single = line.count("'''")
        # Odd count means we're entering/exiting a docstring
        # Even count (e.g., """text""") means complete docstring on one line - no state change
        if triple_double % 2 == 1:
            in_docstring = not in_docstring
            continue
        if triple_single % 2 == 1:
            in_docstring = not in_docstring
            continue
        # If even count (0, 2, 4...), docstring is complete on this line - don't toggle, but skip it
        if triple_double >= 2 or triple_single >= 2:
            continue

        # Skip if in docstring or comment
        if in_docstring or stripped.startswith('#'):
            continue

        # Look for actual console.print() calls
        # Must be actual code, not in a string
        if 'console.print(' in stripped:
            # Skip if it's in a string literal
            # Check if console.print( appears inside quotes
            before_pattern = line.split('console.print(')[0]
            # Count quotes before the pattern
            single_quotes = before_pattern.count("'")
            double_quotes = before_pattern.count('"')
            # If odd number of quotes, we're inside a string
            if single_quotes % 2 == 1 or double_quotes % 2 == 1:
                continue
            # Skip if console.print( appears inside a string assignment
            if '=' in stripped and 'console.print(' in stripped:
                # Check if console.print( appears in a string assignment
                before_console = stripped.split('console.print(')[0]
                last_eq_pos = before_console.rfind('=')
                if last_eq_pos != -1:
                    after_eq = before_console[last_eq_pos+1:]
                    # Count quotes ONLY after the last =
                    sq_after = after_eq.count("'")
                    dq_after = after_eq.count('"')
                    # If odd quotes after =, console.print( is inside string
                    if sq_after % 2 == 1 or dq_after % 2 == 1:
                        continue
            # This is likely an actual call
            console_print_lines.append(i)

        # Look for actual CLI service imports
        if 'from aipass.cli.apps.modules import' in stripped or 'from aipass.cli import' in stripped:
            # Skip if in a string
            if ('"from aipass.cli.apps.modules import' in line or "'from aipass.cli.apps.modules import" in line
                    or '"from aipass.cli import' in line or "'from aipass.cli import" in line):
                continue
            # This is likely an actual import
            cli_import_lines.append(i)

        # Look for print() calls
        if re.search(r'^\s*print\s*\(', line):
            # This is an actual print call at start of line (not in string)
            print_lines.append(i)

    if console_print_lines:
        return {
            'name': 'Handler separation',
            'passed': False,
            'message': f'Handler contains console.print() on lines {console_print_lines[:3]} (violates separation)'
        }

    if cli_import_lines:
        return {
            'name': 'Handler separation',
            'passed': False,
            'message': f'Handler imports CLI services on lines {cli_import_lines[:3]} (handlers should not display)'
        }

    if print_lines:
        return {
            'name': 'Handler separation',
            'passed': False,
            'message': f'Handler contains print() on lines {print_lines[:3]} (use logger instead)'
        }

    return {
        'name': 'Handler separation',
        'passed': True,
        'message': 'No console output detected (good separation)'
    }


def check_cli_imports(content: str, module_path: str = "") -> Optional[Dict]:
    """
    Check for CLI service imports

    Modules should import from cli.apps.modules
    Exception: CLI branch itself uses internal imports
    """
    # Exception: CLI branch uses internal imports (it's the implementation)
    if '/cli/apps/' in module_path:
        return {
            'name': 'CLI service imports',
            'passed': True,
            'message': 'CLI branch exempt (uses internal imports)'
        }

    # Check for CLI imports (canonical or shortcut via cli/__init__.py)
    has_cli_imports = 'from aipass.cli.apps.modules import' in content or 'from aipass.cli import' in content

    if has_cli_imports:
        # Check what's imported (canonical full path or shortcut via __init__.py)
        import_match = re.search(r'from aipass\.cli\.apps\.modules import (.+)', content) or re.search(r'from aipass\.cli import (.+)', content)
        if import_match:
            imports = import_match.group(1)
            return {
                'name': 'CLI service imports',
                'passed': True,
                'message': f'Using CLI services ({imports})'
            }

    # No CLI imports found - check if there's any output at all
    has_console_print = 'console.print(' in content
    has_print = bool(re.search(r'\bprint\s*\(', content))

    if has_console_print or has_print:
        return {
            'name': 'CLI service imports',
            'passed': False,
            'message': 'Has output but missing CLI service imports (import from cli.apps.modules)'
        }

    # No output at all - that's fine for some modules
    return {
        'name': 'CLI service imports',
        'passed': True,
        'message': 'No CLI output needed'
    }


def check_print_usage(content: str, lines: List[str], module_path: str = "") -> Optional[Dict]:
    """
    Check for bare print() statements (should use console.print() instead)

    Looks for print( NOT preceded by a dot (to exclude console.print, logger.print, etc.)
    Also checks for parser.print_help() which uses plain print internally
    Excludes: if __name__ == '__main__': blocks (test/debug code is OK)

    Args:
        content: File content as string
        lines: File lines as list
        module_path: Path to module being checked (for error messages)
    """
    # Find print() statements
    print_lines = []
    parser_print_help_lines = []

    # Track if we're inside an if __name__ == '__main__': block
    in_main_block = False
    main_block_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if line.strip() else 0

        # Detect entry into if __name__ == '__main__': block
        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue

        # Detect exit from if __name__ == '__main__': block
        # (when we find non-empty code at same or lower indentation level)
        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        # Skip checking if we're inside the __main__ block (test/debug code)
        if in_main_block:
            continue

        # Skip comments
        if stripped.startswith('#'):
            continue

        # Check for parser.print_help() - uses plain print() internally
        if 'parser.print_help()' in stripped:
            # Skip if in a comment
            if '#' in line:
                code_part = line.split('#')[0]
                if 'parser.print_help()' in code_part:
                    parser_print_help_lines.append(i)
            else:
                parser_print_help_lines.append(i)

        # Use regex to find BARE print() - not preceded by . or word character
        # This excludes: console.print(), logger.print(), pprint(), etc.
        if re.search(r'(?<![.\w])print\s*\(', line):
            # Skip if in a comment
            if '#' in line:
                code_part = line.split('#')[0]
                if re.search(r'(?<![.\w])print\s*\(', code_part):
                    print_lines.append(i)
            else:
                print_lines.append(i)

    # Get filename for better error messages
    from pathlib import Path
    filename = Path(module_path).name if module_path else "file"

    # Check for parser.print_help() first (more specific violation)
    if parser_print_help_lines:
        return {
            'name': 'print() usage',
            'passed': False,
            'message': f'Found parser.print_help() in {filename} on lines {parser_print_help_lines[:3]} (uses plain print() - use Rich console.print() instead)'
        }

    if print_lines:
        return {
            'name': 'print() usage',
            'passed': False,
            'message': f'Found {len(print_lines)} print() statements in {filename} (use console.print() instead) on lines {print_lines[:3]}{"..." if len(print_lines) > 3 else ""}'
        }

    # Check if using console.print()
    has_console_print = 'console.print(' in content

    if has_console_print:
        return {
            'name': 'print() usage',
            'passed': True,
            'message': 'Using console.print() (no bare print() found)'
        }

    return None  # No output at all


def check_help_flag(content: str) -> Optional[Dict]:
    """
    Check for --help flag implementation

    Modules should respond to --help
    """
    # Look for --help handling
    has_help_flag = '--help' in content and ('-h' in content or 'help' in content)

    # Look for argparse usage
    has_argparse = 'argparse.ArgumentParser' in content or 'import argparse' in content

    # Look for print_help function
    has_print_help = 'def print_help' in content

    if has_print_help or (has_help_flag and has_argparse):
        return {
            'name': '--help flag',
            'passed': True,
            'message': '--help flag implemented'
        }

    # Check if it's a simple module that might not need --help
    if '__main__' not in content:
        return None  # Not an executable module

    return {
        'name': '--help flag',
        'passed': False,
        'message': '--help flag not implemented (modules should respond to --help)'
    }


def check_duplicate_display_functions(content: str, module_path: str = "") -> Optional[Dict]:
    """
    Check for duplicate display functions that should use CLI service instead.

    CLI service provides: header(), success(), error(), warning(), info()
    Modules should import these, not define their own.
    Exception: CLI branch itself defines these functions.
    """
    # Exception: CLI branch defines these functions
    if '/cli/apps/' in module_path:
        return None

    # Display functions that CLI service provides
    cli_display_functions = ['header', 'success', 'error', 'warning', 'info']

    # Look for local function definitions that duplicate CLI service
    duplicates_found = []
    for func_name in cli_display_functions:
        # Check for "def header(" pattern
        if f'def {func_name}(' in content:
            duplicates_found.append(func_name)

    if duplicates_found:
        return {
            'name': 'CLI display functions',
            'passed': False,
            'message': f'Defines own {", ".join(duplicates_found)}() - use from cli.apps.modules.display import {", ".join(duplicates_found)}'
        }

    return {
        'name': 'CLI display functions',
        'passed': True,
        'message': 'No duplicate CLI display functions defined'
    }
