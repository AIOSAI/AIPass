# =================== AIPass ====================
# Name: log_structure_check.py
# Description: Log Structure Standards Checker Handler
# Version: 1.2.0
# Created: 2026-03-06
# Modified: 2026-03-17
# =============================================

"""
Log Structure Standards Checker Handler

Validates the two-tier logging model:
  - system_logs/ at repo root (system-wide)
  - logs/ at branch root only (per-branch)
No hierarchical logs/ at every nested directory.
No hardcoded absolute log paths.
"""

import re
from pathlib import Path
from typing import Dict
from aipass.seedgo.apps.handlers.json import json_handler


def _find_branch_root(file_path: Path) -> Path:
    """Walk up from file to find branch root (directory containing apps/).

    The branch root is the directory that directly contains an ``apps/``
    subdirectory. For example::

        apps/seedgo.py          -> branch root is parent.parent (seedgo/)
        apps/modules/foo.py     -> branch root is parent.parent.parent
        apps/handlers/audit/bar -> branch root is parent x4

    Falls back to the file's parent when no ``apps/`` directory is found
    within 10 levels.
    """
    current = file_path.resolve().parent
    for _ in range(10):  # Safety limit
        if (current / "apps").is_dir():
            return current
        if current == current.parent:
            break
        current = current.parent
    # Fallback: assume parent of file
    return file_path.parent


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


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check module logging structure against the two-tier model.

    Checks:
    1. logs/ directory exists at branch root (entry file's parent)
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

    # Check 1: Branch-root log placement — logs/ directory at the branch root
    branch_root = _find_branch_root(path)
    logs_dir = branch_root / "logs"
    has_logs_dir = logs_dir.is_dir()
    checks.append({
        'name': 'Branch-root logs/ directory',
        'passed': has_logs_dir,
        'message': f'logs/ directory exists at branch root {branch_root}/'
                   if has_logs_dir
                   else f'Missing logs/ directory at branch root {branch_root}/ — two-tier model requires logs/ at branch root'
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
    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "log_structure"})
    return {'passed': passed, 'checks': checks, 'score': score, 'standard': 'LOG_STRUCTURE'}
