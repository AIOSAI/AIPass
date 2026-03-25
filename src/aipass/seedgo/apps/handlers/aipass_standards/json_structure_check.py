# =================== AIPass ====================
# Name: json_structure_check.py
# Description: JSON Structure Standards Checker Handler
# Version: 3.0.0
# Created: 2026-03-05
# Modified: 2026-03-17
# =============================================

"""
JSON Structure Standards Checker Handler

Validates three-JSON code wiring in modules and handlers.

For every .py file in apps/modules/ and apps/handlers/:
  1. Must import json_handler from the branch's handlers/json package
  2. Must call json_handler.log_operation() at least once

For json_handler.py itself (in a json/ directory):
  - Validates handler config (relative paths, no hardcoded absolutes)

Entry points and other files outside modules/handlers are skipped.
"""

import re
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger

# Audit scope: scan every .py file, not just entry point
AUDIT_SCOPE = "all_files"


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
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows JSON structure standards.

    Routing:
      a. json_handler.py in a json/ dir  -> validate handler config
      b. File in apps/modules/           -> check code wiring
      c. File in apps/handlers/          -> check code wiring
      d. Everything else (entry points)  -> skip (not applicable)

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional bypass rules

    Returns:
        dict with passed, checks, score, standard keys
    """
    path = Path(module_path)

    if is_bypassed(module_path, 'json_structure', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'JSON STRUCTURE'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'JSON STRUCTURE'
        }

    # Skip __init__.py files
    if path.name == '__init__.py':
        return {
            'passed': True,
            'checks': [{'name': 'JSON structure check', 'passed': True, 'message': '__init__.py file (skipped)'}],
            'score': 100,
            'standard': 'JSON STRUCTURE'
        }

    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            'passed': False,
            'checks': [{'name': 'File readable', 'passed': False, 'message': f'Error reading file: {e}'}],
            'score': 0,
            'standard': 'JSON STRUCTURE'
        }

    path_str = str(path)

    # --- Case (a): json_handler.py in a json/ directory ---
    if 'json_handler' in path.name and path.parent.name == 'json':
        checks = _check_json_handler_config(path, content, bypass_rules)
        passed_count = sum(1 for c in checks if c['passed'])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {
            'passed': score >= 75,
            'checks': checks,
            'score': score,
            'standard': 'JSON STRUCTURE'
        }

    # --- Determine if the file is in modules/ or handlers/ ---
    in_modules = 'apps/modules' in path_str or 'apps\\modules' in path_str
    in_handlers = 'apps/handlers' in path_str or 'apps\\handlers' in path_str

    # Exclude files inside the json/ handler directory itself (they ARE the
    # json infrastructure, not consumers of it)
    if in_handlers and path.parent.name == 'json':
        return {
            'passed': True,
            'checks': [{'name': 'JSON structure check', 'passed': True,
                         'message': 'JSON handler infrastructure file (not applicable)'}],
            'score': 100,
            'standard': 'JSON STRUCTURE'
        }

    # --- Cases (b) and (c): code wiring check ---
    if in_modules or in_handlers:
        checks = _check_code_wiring(path, content)
        passed_count = sum(1 for c in checks if c['passed'])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {
            'passed': passed_count == total,
            'checks': checks,
            'score': score,
            'standard': 'JSON STRUCTURE'
        }

    # --- Case (d): file outside modules/ and handlers/ (entry point, etc.) ---
    return {
        'passed': True,
        'checks': [{'name': 'JSON structure check', 'passed': True,
                     'message': 'Not in modules/ or handlers/ (not applicable)'}],
        'score': 100,
        'standard': 'JSON STRUCTURE'
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _check_code_wiring(_path: Path, content: str) -> List[Dict]:
    """
    Check that a module/handler file has the three-JSON wiring:
      1. Imports json_handler
      2. Calls json_handler.log_operation()

    Returns a list of two check dicts.
    """
    checks: List[Dict] = []

    # Check 1: imports json_handler
    # Matches patterns like:
    #   from aipass.seedgo.apps.handlers.json import json_handler
    #   from aipass.flow.apps.handlers.json import json_handler
    #   from ...handlers.json import json_handler
    has_import = bool(
        re.search(r'from\s+\S*\.json\s+import\s+json_handler', content)
        or re.search(r'from\s+\S*json\s+import\s+json_handler', content)
        or re.search(r'import\s+json_handler', content)
    )
    checks.append({
        'name': 'json_handler import',
        'passed': has_import,
        'message': 'Imports json_handler' if has_import
                   else 'Missing json_handler import — add: from aipass.<branch>.apps.handlers.json import json_handler'
    })

    # Check 2: calls json_handler.log_operation()
    has_log_operation = 'json_handler.log_operation' in content
    checks.append({
        'name': 'log_operation call',
        'passed': has_log_operation,
        'message': 'Calls json_handler.log_operation()' if has_log_operation
                   else 'Missing json_handler.log_operation() call — every module/handler must log operations'
    })

    return checks


def _check_json_handler_config(_handler_path: Path, content: str, _bypass_rules: list | None = None) -> List[Dict]:
    """
    Check json_handler.py for correct wiring per the json_structure standard.

    Validates:
    1. No hardcoded absolute paths (Path.home())
    2. Uses relative path resolution (Path(__file__))
    3. No template directory references (json_templates)
    4. Uses inline code defaults, not file-based templates (load_template)
    """
    checks: List[Dict] = []

    # Check 1: No hardcoded absolute paths
    has_path_home = bool(re.search(r'Path\.home\(\)', content))
    # Only flag _ROOT constants that use Path.home() (legacy pattern)
    # Allow _ROOT = Path(__file__).resolve()... (relative, pip-safe)
    has_branch_root = False
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if re.search(r'\w+_ROOT\s*=', stripped) and 'Path.home()' in stripped:
            has_branch_root = True
            break

    if has_path_home or has_branch_root:
        issues = []
        if has_path_home:
            issues.append('Path.home()')
        if has_branch_root:
            issues.append('hardcoded _ROOT constant')
        checks.append({
            'name': 'No absolute paths',
            'passed': False,
            'message': f'Found {", ".join(issues)} — pip packages should use relative paths'
        })
    else:
        checks.append({
            'name': 'No absolute paths',
            'passed': True,
            'message': 'No hardcoded absolute paths (correct for pip packages)'
        })

    # Check 2: Uses relative path resolution
    has_relative = bool(re.search(r'Path\(__file__\)', content)
                        or re.search(r'\.resolve\(\)', content)
                        or re.search(r'\.parent', content))

    checks.append({
        'name': 'Relative path resolution',
        'passed': has_relative,
        'message': 'Uses relative path resolution (Path(__file__).parent)' if has_relative
                   else 'Missing relative path resolution — should use Path(__file__).resolve().parent'
    })

    # Check 3: No template directory references
    # The standard says: "The CODE PATTERN is the template -- no json_templates/ directory"
    # Check for path constants or strings referencing json_templates
    has_template_dir = False
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if 'json_templates' in stripped:
            has_template_dir = True
            break

    checks.append({
        'name': 'No template directory',
        'passed': not has_template_dir,
        'message': 'No json_templates/ references (correct — code is the template)' if not has_template_dir
                   else 'References json_templates/ directory — standard requires auto-create from code defaults, not file templates'
    })

    # Check 4: No load_template() function
    # The correct pattern uses inline defaults (_create_default or similar).
    # A load_template() that reads from files violates the auto-create principle.
    has_load_template = bool(re.search(r'def\s+load_template\s*\(', content))

    checks.append({
        'name': 'No file-based templates',
        'passed': not has_load_template,
        'message': 'No load_template() function (correct — uses inline code defaults)' if not has_load_template
                   else 'Has load_template() function — standard requires inline code defaults, not file-based templates'
    })

    return checks
