"""
JSON Structure Standards Checker Handler

Validates JSON handling patterns for pip packages:
- json_handler.py uses relative paths (not hardcoded absolute)
- Modules use json_handler for JSON operations (not direct json.load/dump)
- Branch detection via AIPASS_REGISTRY.json and BRANCH_REGISTRY.json
"""

# =================== AIPass ====================
# Name: json_structure_check.py
# Description: JSON Structure Standards Checker Handler
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import re
import ast
import json
from pathlib import Path
from typing import Dict, List, Optional


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
    Check if module follows JSON structure standards.

    For pip packages, validates:
    1. json_handler.py uses relative paths (Path(__file__).resolve().parent)
    2. json_handler.py does NOT use hardcoded absolute paths (BRANCH_ROOT, Path.home())
    3. Modules use json_handler instead of direct json.load/dump
    """
    checks = []
    path = Path(module_path)

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'JSON STRUCTURE'
        }

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {
            'passed': False,
            'checks': [{'name': 'File readable', 'passed': False, 'message': f'Error reading file: {e}'}],
            'score': 0,
            'standard': 'JSON STRUCTURE'
        }

    if 'json_handler' in path.name and path.parent.name == 'json':
        checks = check_json_handler_config(path, content, bypass_rules)
    elif 'apps/modules' in str(path):
        checks = check_module_json_files(path, content, bypass_rules)

    if not checks:
        return {
            'passed': True,
            'checks': [{'name': 'JSON structure check', 'passed': True, 'message': 'No JSON operations detected (skipped)'}],
            'score': 100,
            'standard': 'JSON STRUCTURE'
        }

    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'JSON STRUCTURE'
    }


def _find_registry() -> Path:
    """Find AIPASS_REGISTRY.json by walking up from this file's location."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        candidate = parent / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
    return Path.cwd() / "AIPASS_REGISTRY.json"


def detect_branch(file_path: Path) -> Optional[str]:
    """
    Detect which branch a file belongs to from its path.

    Checks AIPASS_REGISTRY.json as source of truth.
    Falls back to path heuristics if not available.
    """
    file_path_str = str(file_path.resolve())

    registry_path = _find_registry()
    if registry_path.exists():
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
            registry_dir = registry_path.parent
            branches = sorted(
                registry.get('branches', []),
                key=lambda b: len(b.get('path', '')),
                reverse=True
            )
            for branch in branches:
                raw_path = branch.get('path', '')
                branch_path = Path(raw_path)
                if not branch_path.is_absolute():
                    branch_path = (registry_dir / branch_path).resolve()
                if file_path_str.startswith(str(branch_path)):
                    return branch.get('name', '').lower()
        except (json.JSONDecodeError, IOError):
            pass

    # Fallback: path heuristics
    path_parts = file_path.parts
    if 'seedgo' in path_parts:
        return 'seedgo'
    if 'aipass' in path_parts:
        idx = path_parts.index('aipass')
        if idx + 1 < len(path_parts):
            return path_parts[idx + 1]

    return None


def get_branch_path(branch_name: str) -> Optional[str]:
    """Get actual branch path from AIPASS_REGISTRY.json."""
    registry_path = _find_registry()
    if registry_path.exists():
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
            registry_dir = registry_path.parent
            for branch in registry.get('branches', []):
                if branch.get('name', '').lower() == branch_name.lower():
                    raw_path = branch.get('path', '')
                    branch_path = Path(raw_path)
                    if not branch_path.is_absolute():
                        branch_path = (registry_dir / branch_path).resolve()
                    return str(branch_path)
        except (json.JSONDecodeError, IOError):
            pass

    return None


def check_json_handler_config(handler_path: Path, content: str, bypass_rules: list | None = None) -> List[Dict]:  # noqa: ARG001
    """
    Check json_handler.py for library profile.

    For pip packages:
    - PASS if using relative paths (Path(__file__).resolve().parent, etc.)
    - FAIL if using hardcoded absolute paths (Path.home(), BRANCH_ROOT, etc.)
    """
    checks = []

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
    has_relative = bool(re.search(r'Path\(__file__\)', content) or
                       re.search(r'\.resolve\(\)', content) or
                       re.search(r'\.parent', content))

    checks.append({
        'name': 'Relative path resolution',
        'passed': has_relative,
        'message': 'Uses relative path resolution (Path(__file__).parent)' if has_relative
                   else 'Missing relative path resolution — should use Path(__file__).resolve().parent'
    })

    return checks


def check_module_json_files(module_path: Path, content: str, bypass_rules: list | None = None) -> List[Dict]:
    """
    Check if module uses json_handler for JSON operations.
    For library profile, just validates json_handler usage pattern.
    """
    checks = []

    uses_json_handler = 'json_handler' in content and ('from' in content or 'import' in content)

    if not uses_json_handler:
        json_check = check_json_handler_usage(content, str(module_path), bypass_rules)
        if json_check:
            checks.append(json_check)
        return checks

    # Module uses json_handler — that's correct
    checks.append({
        'name': 'json_handler usage',
        'passed': True,
        'message': 'Module uses json_handler for JSON operations'
    })

    return checks


def check_json_handler_usage(content: str, file_path: str, bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check that modules use json_handler for JSON operations (not direct json.load/dump).
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    has_json_operations = False
    has_json_handler_import = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and 'json_handler' in node.module:
                has_json_handler_import = True

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if (isinstance(node.func.value, ast.Name) and
                    node.func.value.id == 'json' and
                    node.func.attr in ['dump', 'load']):
                    has_json_operations = True

    if not has_json_operations:
        return None

    if has_json_operations and not has_json_handler_import:
        if is_bypassed(file_path, 'json_structure', bypass_rules=bypass_rules):
            return None
        return {
            'name': 'json_handler usage',
            'passed': False,
            'message': 'Direct JSON operations detected (use json_handler for structured JSON management)'
        }

    return None
