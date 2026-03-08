"""
Architecture Standards Checker Handler

Validates module compliance with AIPass architecture standards.
Checks 3-layer pattern, handler independence, file size, domain organization.
For entry points, also verifies entire branch structure against template baseline.
"""

# =================== AIPass ====================
# Name: architecture_check.py
# Description: Architecture Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


import sys
import json
from pathlib import Path
from typing import Dict, List, Optional

from aipass.seedgo.apps.standards.aipass.handlers.config.ignore_handler import get_template_ignore_patterns

PACK_ROOT = Path(__file__).resolve().parent.parent.parent  # standards/ -> handlers/ -> aipass/

# Template registry path - generated from spawn/templates/agent.template via template_scanner
# Points to the registry in seedgo's json_templates directory
# Set to None to skip template baseline checks
TEMPLATE_REGISTRY_PATH: Optional[Path] = PACK_ROOT / "json_templates" / ".template_registry.json"


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

    # Check 5: Template baseline verification (for entry points, check entire branch structure)
    if is_entry_point:
        baseline_checks = check_template_baseline(module_path, bypass_rules=bypass_rules)
        checks.extend(baseline_checks)

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
    """Load ignore patterns from .registry_ignore.json"""
    ignore_file = template_path / ".registry_ignore.json"

    if not ignore_file.exists():
        return {"ignore_files": [], "ignore_patterns": []}

    try:
        with open(ignore_file, 'r') as f:
            data = json.load(f)
            return {
                "ignore_files": data.get("ignore_files", []),
                "ignore_patterns": data.get("ignore_patterns", [])
            }
    except Exception:
        return {"ignore_files": [], "ignore_patterns": []}


def _should_ignore(path: Path, template_path: Path, ignore_config: Dict) -> bool:
    """Check if path should be ignored"""
    name = path.name

    # Check exact filename matches
    if name in ignore_config["ignore_files"]:
        return True

    # Check patterns
    for pattern in ignore_config["ignore_patterns"]:
        if pattern.startswith('*'):
            # *.pyc -> check extension
            if name.endswith(pattern[1:]):
                return True
        elif pattern.startswith('.') and '*' in pattern:
            # .backup* -> check prefix
            prefix = pattern.rstrip('*')
            if name.startswith(prefix):
                return True
        else:
            # Exact match or directory name
            if name == pattern or pattern in path.parts:
                return True

    return False


def check_template_baseline(module_path: str, bypass_rules: list | None = None) -> List[Dict]:
    """
    Verify branch structure against spawn template registry (source of truth)

    Loads the template registry, transforms paths for the branch ({{BRANCH}}, FILE_RENAMES),
    and checks if all template items exist in the branch.

    Args:
        module_path: Path to entry point file (e.g., src/aipass/api/apps/branch.py)

    Returns:
        List of check dictionaries for each template item
    """
    checks = []

    # Detect branch path and name from module path
    path = Path(module_path)
    branch_path = None

    # Find the branch root (parent of apps/ directory)
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

    # Get branch name from path
    branch_name = branch_path.name
    branch_upper = branch_name.upper().replace("-", "_")

    # Load template registry (source of truth)
    # Uses configurable TEMPLATE_REGISTRY_PATH; skips check if not configured
    template_registry_path = TEMPLATE_REGISTRY_PATH

    if template_registry_path is None:
        return [{
            'name': 'Template baseline',
            'passed': True,
            'message': 'Template registry path not configured (skipped)'
        }]

    if not template_registry_path.exists():
        return [{
            'name': 'Template baseline',
            'passed': True,
            'message': f'Template registry not found at {template_registry_path} (skipped)'
        }]

    try:
        with open(template_registry_path, 'r') as f:
            template_registry = json.load(f)
    except Exception as e:
        return [{
            'name': 'Template baseline',
            'passed': True,
            'message': f'Error reading template registry: {e} (skipped)'
        }]

    # FILE_RENAMES mapping (from spawn create_branch.py)
    # Entry point filename strips leading dots (e.g., .VSCODE -> vscode.py)
    entry_point_name = branch_name.lstrip('.').lower()
    FILE_RENAMES = {
        "PROJECT.json": f"{branch_upper}.json",
        "LOCAL.json": f"{branch_upper}.local.json",
        "OBSERVATIONS.json": f"{branch_upper}.observations.json",
        "AI_MAIL.json": f"{branch_upper}.ai_mail.json",
        "BRANCH.ID.json": f"{branch_upper}.id.json",
        "BRANCH.py": f"{entry_point_name}.py",
    }

    # Check template files
    for file_id, file_info in template_registry.get('files', {}).items():
        template_path = file_info.get('path', '')
        template_name = file_info.get('current_name', '')

        if not template_path:
            continue

        # Skip template files that aren't required in branches (from ignore_handler)
        if template_name in get_template_ignore_patterns():
            continue

        # Transform path for this branch
        # 1. Replace {{BRANCH}} placeholder
        # Use lowercase for _json directories to match cortex behavior
        if "_json" in template_path:
            branch_path_transformed = template_path.replace("{{BRANCH}}", branch_name.lower().replace("-", "_"))
        else:
            branch_path_transformed = template_path.replace("{{BRANCH}}", branch_upper)

        # 2. Apply FILE_RENAMES
        if template_name in FILE_RENAMES:
            # Replace the filename in the path
            path_parts = branch_path_transformed.split('/')
            path_parts[-1] = FILE_RENAMES[template_name]
            branch_path_transformed = '/'.join(path_parts)

        # Check if file exists
        full_path = branch_path / branch_path_transformed

        if full_path.exists():
            checks.append({
                'name': f'File: {branch_path_transformed}',
                'passed': True,
                'message': 'Template file exists'
            })
        else:
            # Check if missing file is bypassed
            # Use the final filename for bypass check (e.g., AI_MAIL.id.json)
            file_name = branch_path_transformed.split('/')[-1] if '/' in branch_path_transformed else branch_path_transformed
            if is_bypassed(file_name, 'architecture', bypass_rules=bypass_rules):
                checks.append({
                    'name': f'File: {branch_path_transformed}',
                    'passed': True,
                    'message': 'Template file missing (bypassed)'
                })
            else:
                checks.append({
                    'name': f'File: {branch_path_transformed}',
                    'passed': False,
                    'message': 'Template file missing'
                })

    # Check template directories
    for dir_id, dir_info in template_registry.get('directories', {}).items():
        template_path = dir_info.get('path', '')

        if not template_path:
            continue

        # Transform path for this branch
        # Use lowercase for _json directories to match cortex behavior
        if "_json" in template_path:
            branch_path_transformed = template_path.replace("{{BRANCH}}", branch_name.lower().replace("-", "_"))
        else:
            branch_path_transformed = template_path.replace("{{BRANCH}}", branch_upper)

        # Check if directory exists
        full_path = branch_path / branch_path_transformed

        if full_path.exists():
            checks.append({
                'name': f'Directory: {branch_path_transformed}/',
                'passed': True,
                'message': 'Template directory exists'
            })
        else:
            checks.append({
                'name': f'Directory: {branch_path_transformed}/',
                'passed': False,
                'message': 'Template directory missing'
            })

    return checks
