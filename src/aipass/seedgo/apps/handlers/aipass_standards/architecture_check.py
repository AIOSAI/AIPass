# =================== AIPass ====================
# Name: architecture_check.py
# Description: Architecture Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Architecture Standards Checker Handler

Validates module compliance with AIPass architecture standards.
Checks 3-layer pattern, handler independence, file size, domain organization.
For entry points, also verifies entire branch structure against template baseline.
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_template_ignore_patterns
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"

PACK_ROOT = Path(__file__).resolve().parent.parent.parent  # aipass_standards/ -> handlers/ -> apps/ -> seedgo/

# Spawn templates directory — live-scanned, class-aware
# PACK_ROOT = seedgo/apps/, so .parent.parent = src/aipass/
_SRC_PKG_ROOT = PACK_ROOT.parent.parent  # apps/ -> seedgo/ -> src/aipass/
SPAWN_TEMPLATES_DIR = _SRC_PKG_ROOT / "spawn" / "templates"


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
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows architecture standards

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules for this file

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
    if is_bypassed(module_path, 'architecture', bypass_rules=bypass_rules):
        return {
            'passed': True,
            'checks': [{'name': 'Bypassed', 'passed': True, 'message': 'Standard bypassed via .seedgo/bypass.json'}],
            'score': 100,
            'standard': 'ARCHITECTURE'
        }

    # Validate file exists
    if not path.exists():
        return {
            'passed': False,
            'checks': [{'name': 'File exists', 'passed': False, 'message': f'File not found: {module_path}'}],
            'score': 0,
            'standard': 'ARCHITECTURE'
        }

    # Read file
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            'passed': False,
            'checks': [{'name': 'File readable', 'passed': False, 'message': f'Error reading file: {e}'}],
            'score': 0,
            'standard': 'ARCHITECTURE'
        }

    # Determine file location and type
    is_entry_point = path.name.endswith('.py') and 'apps/' in module_path and path.parent.name == 'apps'
    is_module = 'apps/modules/' in module_path
    is_handler = 'apps/handlers/' in module_path
    is_init = path.name == '__init__.py'

    # Check 1: 3-Layer Pattern - File location
    if not is_init:
        layer_check = check_layer_location(module_path, is_entry_point, is_module, is_handler)
        checks.append(layer_check)

    # Check 2: File size
    size_check = check_file_size(lines, module_path)
    checks.append(size_check)

    # Check 3: Handler independence (handlers must not import parent modules)
    if is_handler:
        independence_check = check_handler_independence(lines, module_path)
        if independence_check:
            checks.append(independence_check)

    # Check 4: Domain organization (handlers should be in domain folders)
    if is_handler:
        domain_check = check_domain_organization(module_path)
        if domain_check:
            checks.append(domain_check)

    # Check 5: Template baseline verification (primary entry point only — {branch}.py)
    # Secondary entry points (e.g. daemon_wakeup.py, scheduler_cron.py) skip this
    # to avoid duplicate branch-level template checks.
    if is_entry_point:
        branch_dir = path.parent.parent  # apps/ -> branch/
        if path.stem == branch_dir.name:
            baseline_checks = check_template_baseline(module_path, bypass_rules=bypass_rules)
            checks.extend(baseline_checks)

    # Calculate score
    passed_checks = sum(1 for check in checks if check['passed'])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "architecture"})
    return {
        'passed': overall_passed,
        'checks': checks,
        'score': score,
        'standard': 'ARCHITECTURE'
    }


def check_layer_location(module_path: str, is_entry_point: bool, is_module: bool, is_handler: bool) -> Dict:
    """
    Check if file is in correct architectural layer

    3-Layer Pattern:
    - apps/branch.py (entry point)
    - apps/modules/ (orchestration)
    - apps/handlers/ (implementation)
    """
    if is_entry_point:
        return {
            'name': '3-layer pattern',
            'passed': True,
            'message': 'Entry point layer (apps/branch.py)'
        }
    elif is_module:
        return {
            'name': '3-layer pattern',
            'passed': True,
            'message': 'Module layer (apps/modules/)'
        }
    elif is_handler:
        return {
            'name': '3-layer pattern',
            'passed': True,
            'message': 'Handler layer (apps/handlers/)'
        }
    else:
        return {
            'name': '3-layer pattern',
            'passed': False,
            'message': f'File not in standard 3-layer structure (apps/, apps/modules/, apps/handlers/)'
        }


def check_file_size(lines: List[str], module_path: str) -> Dict:
    """
    Check file size compliance

    Guidelines:
    - Under 300 lines: Perfect
    - 300-500 lines: Good
    - 500-700 lines: Getting heavy
    - 700+ lines: Consider splitting
    """
    line_count = len(lines)

    if line_count < 300:
        return {
            'name': 'File size',
            'passed': True,
            'message': f'{line_count} lines (perfect - under 300)'
        }
    elif line_count < 500:
        return {
            'name': 'File size',
            'passed': True,
            'message': f'{line_count} lines (good - under 500)'
        }
    elif line_count < 700:
        return {
            'name': 'File size',
            'passed': True,
            'message': f'{line_count} lines (acceptable but getting heavy)'
        }
    else:
        return {
            'name': 'File size',
            'passed': False,
            'message': f'{line_count} lines (consider splitting - recommended under 700)'
        }


def check_handler_independence(lines: List[str], module_path: str) -> Optional[Dict]:
    """
    Check that handlers don't import from parent branch modules

    Handlers must be independent and transportable.
    Allowed: from prax.apps.modules import ... (service)
    Allowed: from cli.apps.modules import ... (service)
    Forbidden: from <parent_branch>.apps.modules import ...
    """
    # Detect parent branch from module path
    parent_branch = None
    if module_path:
        path_parts = Path(module_path).parts
        for i, part in enumerate(path_parts):
            if part == 'apps' and i > 0:
                parent_branch = path_parts[i-1]
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

        # Check for forbidden module imports
        if '.apps.modules' in line and ('from ' in line or 'import ' in line):
            # Extract the import statement
            if '#' in line:
                code_part = line.split('#')[0]
            else:
                code_part = line

            if '.apps.modules' in code_part:
                # Allowed service imports
                if 'prax.apps.modules' in code_part or 'cli.apps.modules' in code_part:
                    continue

                # Check if importing from parent branch
                if parent_branch and f'{parent_branch}.apps.modules' in code_part:
                    return {
                        'name': 'Handler independence',
                        'passed': False,
                        'message': f'Handler importing from parent module on line {i} (violates independence)'
                    }

                # Generic check if no parent branch detected
                if not parent_branch:
                    return {
                        'name': 'Handler independence',
                        'passed': False,
                        'message': f'Handler importing from branch module on line {i} (violates independence)'
                    }

    return {
        'name': 'Handler independence',
        'passed': True,
        'message': 'No forbidden module imports detected'
    }


def check_domain_organization(module_path: str) -> Optional[Dict]:
    """
    Check if handler is organized by domain (not technical role)

    Good: handlers/json/, handlers/error/, handlers/branch/
    Bad: handlers/utils/, handlers/helpers/, handlers/operations/
    """
    # Extract handler domain from path
    # e.g., src/aipass/seedgo/apps/handlers/standards/file.py -> domain is 'standards'
    path_parts = Path(module_path).parts

    # Find 'handlers' in path and get next directory
    handler_domain = None
    for i, part in enumerate(path_parts):
        if part == 'handlers' and i + 1 < len(path_parts):
            handler_domain = path_parts[i + 1]
            break

    if not handler_domain:
        return {
            'name': 'Domain organization',
            'passed': False,
            'message': 'Could not detect handler domain from path'
        }

    # Check for technical (bad) organization
    technical_names = ['utils', 'helpers', 'operations', 'common', 'shared', 'lib']
    if handler_domain.lower() in technical_names:
        return {
            'name': 'Domain organization',
            'passed': False,
            'message': f'Technical organization ({handler_domain}/) - use business domains instead'
        }

    # Domain-based organization detected
    return {
        'name': 'Domain organization',
        'passed': True,
        'message': f'Domain-based organization ({handler_domain}/)'
    }


def _load_ignore_patterns(template_path: Path) -> Dict:
    """Load ignore patterns from .registry_ignore.json in the template's .spawn/ dir"""
    ignore_file = template_path / ".spawn" / ".registry_ignore.json"

    if not ignore_file.exists():
        return {"ignore_files": [], "ignore_patterns": []}

    try:
        with open(ignore_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {
                "ignore_files": data.get("ignore_files", []),
                "ignore_patterns": data.get("ignore_patterns", [])
            }
    except Exception:
        logger.info("Cannot read ignore config: %s", ignore_file)
        return {"ignore_files": [], "ignore_patterns": []}


def _should_ignore(item: Path, ignore_config: Dict) -> bool:
    """Check if a template item should be ignored during baseline check"""
    name = item.name

    # Check exact filename matches
    if name in ignore_config["ignore_files"]:
        return True

    # Check patterns
    for pattern in ignore_config["ignore_patterns"]:
        if pattern.startswith('*'):
            if name.endswith(pattern[1:]):
                return True
        elif pattern.startswith('.') and '*' in pattern:
            prefix = pattern.rstrip('*')
            if name.startswith(prefix):
                return True
        else:
            if name == pattern or pattern in item.parts:
                return True

    return False


def _get_citizen_class(branch_path: Path) -> Optional[str]:
    """Read citizen_class from branch's .trinity/passport.json"""
    passport = branch_path / ".trinity" / "passport.json"
    if not passport.exists():
        return None
    try:
        with open(passport, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("identity", {}).get("citizen_class")
    except Exception:
        logger.info("Cannot read passport: %s", passport)
        return None


def _scan_template(template_path: Path) -> Dict:
    """Scan spawn template directory and return expected structure.

    Returns dict with 'directories' and 'files' — relative paths
    with {{BRANCH}} placeholders intact.
    """
    ignore_config = _load_ignore_patterns(template_path)
    structure = {"directories": [], "files": []}

    for item in sorted(template_path.rglob('*')):
        if _should_ignore(item, ignore_config):
            continue

        relative = str(item.relative_to(template_path))

        if item.is_dir():
            structure["directories"].append(relative)
        elif item.is_file():
            # Skip template-only files (from ignore_handler)
            if item.name in get_template_ignore_patterns():
                continue
            structure["files"].append(relative)

    return structure


def _transform_path(template_relative: str, branch_name: str) -> str:
    """Transform a template path for a specific branch.

    Replaces {{BRANCH}} placeholder and renames known template files
    to their branch-specific names.
    """
    branch_lower = branch_name.lower().replace("-", "_")
    entry_point_name = branch_name.lstrip('.').lower()

    # {{BRANCH}} in directory names uses lowercase (e.g., {{BRANCH}}_json → seedgo_json)
    result = template_relative.replace("{{BRANCH}}", branch_lower)

    # Known file renames from spawn's create_branch convention
    FILE_RENAMES = {
        f"{branch_lower}.py": f"{entry_point_name}.py",  # already lowercase from placeholder
    }

    filename = Path(result).name
    if filename in FILE_RENAMES:
        result = str(Path(result).parent / FILE_RENAMES[filename])

    return result


def check_template_baseline(module_path: str, bypass_rules: list | None = None) -> List[Dict]:
    """
    Verify branch structure against spawn template (live scan, class-aware).

    Reads .trinity/passport.json → citizen_class → picks spawn/templates/{class}/
    Scans the template directory live (no static registry needed).
    Transforms {{BRANCH}} placeholders and compares against actual branch.

    Args:
        module_path: Path to entry point file (e.g., src/aipass/api/apps/api.py)
        bypass_rules: Optional bypass rules

    Returns:
        List of check dicts for each template item
    """
    checks = []

    # Detect branch path from module path
    path = Path(module_path)
    branch_path = None
    current = path.parent
    while current != current.parent:
        if current.name == 'apps' and current.parent:
            branch_path = current.parent
            break
        current = current.parent

    if not branch_path:
        return [{
            'name': 'Template baseline',
            'passed': False,
            'message': 'Could not detect branch path from module path'
        }]

    branch_name = branch_path.name

    # Read citizen class from passport
    citizen_class = _get_citizen_class(branch_path)
    if not citizen_class:
        return [{
            'name': 'Template baseline',
            'passed': False,
            'message': f'No citizen_class in {branch_name}/.trinity/passport.json'
        }]

    # Find the matching template directory
    if not SPAWN_TEMPLATES_DIR.exists():
        return [{
            'name': 'Template baseline',
            'passed': False,
            'message': f'Spawn templates directory not found: {SPAWN_TEMPLATES_DIR}'
        }]

    template_path = SPAWN_TEMPLATES_DIR / citizen_class
    if not template_path.exists():
        return [{
            'name': 'Template baseline',
            'passed': False,
            'message': f'No template for citizen_class "{citizen_class}" at {template_path}'
        }]

    # Scan template live
    template_structure = _scan_template(template_path)

    # Check directories
    for template_dir in template_structure["directories"]:
        expected = _transform_path(template_dir, branch_name)
        full = branch_path / expected

        if full.exists():
            checks.append({
                'name': f'Dir: {expected}/',
                'passed': True,
                'message': 'Template directory exists'
            })
        else:
            if is_bypassed(expected, 'architecture', bypass_rules=bypass_rules):
                checks.append({
                    'name': f'Dir: {expected}/',
                    'passed': True,
                    'message': 'Template directory missing (bypassed)'
                })
            else:
                checks.append({
                    'name': f'Dir: {expected}/',
                    'passed': False,
                    'message': f'Missing dir: {expected}/ (template: {citizen_class})'
                })

    # Check files
    for template_file in template_structure["files"]:
        expected = _transform_path(template_file, branch_name)
        full = branch_path / expected

        if full.exists():
            checks.append({
                'name': f'File: {expected}',
                'passed': True,
                'message': 'Template file exists'
            })
        else:
            file_name = Path(expected).name
            if is_bypassed(file_name, 'architecture', bypass_rules=bypass_rules):
                checks.append({
                    'name': f'File: {expected}',
                    'passed': True,
                    'message': 'Template file missing (bypassed)'
                })
            else:
                checks.append({
                    'name': f'File: {expected}',
                    'passed': False,
                    'message': f'Missing file: {expected} (template: {citizen_class})'
                })

    # Summary check
    missing_count = sum(1 for c in checks if not c['passed'])
    total_count = len(checks)
    checks.insert(0, {
        'name': f'Template baseline ({citizen_class})',
        'passed': missing_count == 0,
        'message': f'{total_count} items checked from spawn/templates/{citizen_class}/, {missing_count} missing'
    })

    return checks
