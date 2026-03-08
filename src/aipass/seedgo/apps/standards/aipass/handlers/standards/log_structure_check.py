"""
Log Structure Standards Checker Handler

Validates that AIPass modules follow the local logging pattern:
every module should have a logs/ directory for module-local logs.
No hardcoded absolute log paths.
"""

# =================== AIPass ====================
# Name: log_structure_check.py
# Description: Log Structure Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-06
# Modified: 2026-03-06
# =============================================


import re
from pathlib import Path
from typing import Dict


def is_bypassed(file_path: str, standard: str, bypass_rules: list | None = None) -> bool:
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
        if not rule_lines:
            return True
    return False


def _find_module_root(file_path: Path) -> Path | None:
    """Walk up from file to find the module root (directory containing apps/)."""
    current = file_path.parent
    for parent in [current] + list(current.parents):
        if (parent / "apps").is_dir():
            return parent
        # Stop at src/aipass level
        if parent.name == "aipass" and parent.parent.name == "src":
            break
    return None


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check module logging structure.

    Checks:
    1. Module has a logs/ directory
    2. No hardcoded absolute log paths in source
    3. No /home/ references in logging configuration

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules

    Returns:
        Standard check result dict
    """
    path = Path(module_path)
    checks = []

    if is_bypassed(module_path, 'log_structure', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'LOG_STRUCTURE'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'LOG_STRUCTURE'
        }

    # Check 1: Module has logs/ directory
    module_root = _find_module_root(path)
    if module_root:
        logs_dir = module_root / "logs"
        has_logs_dir = logs_dir.is_dir()
        checks.append({
            'name': 'Module logs/ directory',
            'passed': has_logs_dir,
            'message': 'Module has local logs/ directory' if has_logs_dir
                       else f'Missing logs/ directory at {module_root.name}/'
        })
    else:
        # Can't determine module root — skip this check, pass it
        checks.append({
            'name': 'Module logs/ directory',
            'passed': True,
            'message': 'Module root not determinable (standalone file)'
        })

    # Check 2-3: Scan file for hardcoded log paths
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        checks.append({
            'name': 'File readable',
            'passed': False,
            'message': f'Error reading file: {e}'
        })
        passed = all(c['passed'] for c in checks)
        score = int(sum(1 for c in checks if c['passed']) / len(checks) * 100)
        return {'passed': passed, 'checks': checks, 'score': score, 'standard': 'LOG_STRUCTURE'}

    lines = content.split('\n')

    # Check 2: No hardcoded absolute log paths
    abs_log_issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments and docstrings
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # Look for absolute paths in log-related contexts
        if re.search(r'["\'][/\\](?:home|tmp|var|etc)[/\\].*\.log', stripped):
            abs_log_issues.append(i)

    checks.append({
        'name': 'No hardcoded log paths',
        'passed': len(abs_log_issues) == 0,
        'message': 'No hardcoded absolute log paths found' if not abs_log_issues
                   else f'Hardcoded log paths on lines: {abs_log_issues}'
    })

    # Check 3: No /home/ references in logging setup
    home_log_issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # Look for /home/ in log file handler or path config
        if re.search(r'/home/\w+', stripped) and ('log' in stripped.lower() or 'LOG' in stripped):
            home_log_issues.append(i)

    checks.append({
        'name': 'No /home/ in log config',
        'passed': len(home_log_issues) == 0,
        'message': 'No /home/ references in logging configuration' if not home_log_issues
                   else f'/home/ references in log config on lines: {home_log_issues}'
    })

    passed = all(c['passed'] for c in checks)
    score = int(sum(1 for c in checks if c['passed']) / len(checks) * 100) if checks else 0
    return {'passed': passed, 'checks': checks, 'score': score, 'standard': 'LOG_STRUCTURE'}
