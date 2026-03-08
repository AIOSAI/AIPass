"""
META Block Standards Checker Handler

Validates library-profile META blocks in Python files.
Library META is lighter than full META - focuses on identity
and traceability without branch-specific fields.

Required META format:
    # =================== AIPass ====================
    # Name: filename.py
    # Description: Brief description of the file
    # Version: X.Y.Z
    # Created: YYYY-MM-DD
    # Modified: YYYY-MM-DD
    # =============================================
"""

# =================== AIPass ====================
# Name: meta_check.py
# Description: META Block Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

import re
from pathlib import Path
from typing import Dict, List


# Header/footer markers for library META
# Accept both AIPass (canonical) and META (legacy) header markers
META_HEADER = "# =================== AIPass ===================="
META_HEADER_LEGACY = "# =================== META ===================="
META_FOOTER = "# ============================================="

# Required fields with validation patterns
REQUIRED_FIELDS = {
    "Name": r"# Name:\s+\S+\.py",
    "Description": r"# Description:\s+\S+",
    "Version": r"# Version:\s+\d+\.\d+\.\d+",
    "Created": r"# Created:\s+\d{4}-\d{2}-\d{2}",
    "Modified": r"# Modified:\s+\d{4}-\d{2}-\d{2}",
}


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
    Check if module has a valid library-profile META block.

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional bypass rules

    Returns:
        dict with passed, checks, score, standard keys
    """
    path = Path(module_path)

    if is_bypassed(module_path, 'meta', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'META'
        }

    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'META'
        }

    # Skip __init__.py files
    if path.name == '__init__.py':
        return {
            'passed': True,
            'checks': [{'name': 'META check', 'passed': True, 'message': '__init__.py file (skipped)'}],
            'score': 100,
            'standard': 'META'
        }

    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        return {
            'passed': False,
            'checks': [{'name': 'File readable', 'passed': False, 'message': f'Error reading file: {e}'}],
            'score': 0,
            'standard': 'META'
        }

    checks = []

    # Check 1: META block presence
    presence = check_meta_presence(content)
    checks.append(presence)

    # Check 2: Required fields (only if block exists)
    if presence['passed']:
        fields = check_required_fields(content, path.name)
        checks.extend(fields)

    passed_checks = sum(1 for c in checks if c['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'META'
    }


def check_meta_presence(content: str) -> Dict:
    """Check that META block header and footer markers exist"""
    has_header = META_HEADER in content or META_HEADER_LEGACY in content
    has_footer = META_FOOTER in content

    if has_header and has_footer:
        return {
            'name': 'META block present',
            'passed': True,
            'message': 'META block with header and footer markers found'
        }

    missing = []
    if not has_header:
        missing.append('header')
    if not has_footer:
        missing.append('footer')

    return {
        'name': 'META block present',
        'passed': False,
        'message': f'Missing META block ({", ".join(missing)} marker not found)'
    }


def check_required_fields(content: str, filename: str) -> List[Dict]:
    """Check all required fields are present and valid"""
    results = []

    for field_name, pattern in REQUIRED_FIELDS.items():
        match = re.search(pattern, content)

        if field_name == "Name" and match:
            # Extra validation: Name field should reference the actual filename
            name_match = re.search(r"# Name:\s+(\S+\.py)", content)
            if name_match and name_match.group(1) != filename:
                results.append({
                    'name': f'META {field_name}',
                    'passed': False,
                    'message': f'Name field says "{name_match.group(1)}" but file is "{filename}"'
                })
                continue

        if match:
            results.append({
                'name': f'META {field_name}',
                'passed': True,
                'message': f'{field_name} field present and valid'
            })
        else:
            results.append({
                'name': f'META {field_name}',
                'passed': False,
                'message': f'Missing or invalid {field_name} field'
            })

    return results
