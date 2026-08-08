# =================== AIPass ====================
# Name: json_structure_check.py
# Description: JSON Structure Standards Checker Handler
# Version: 3.1.0
# Created: 2026-03-05
# Modified: 2026-08-07
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
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: scan every .py file, not just entry point
AUDIT_SCOPE = "all_files"

ALLOWED_JSON_SUBDIRS: frozenset[str] = frozenset({"custom_config"})

CUSTOM_CONFIG_DIR = "custom_config"

# The custom_config/ README is scaffolding, not an operator override.
CUSTOM_CONFIG_SKIP_FILES: frozenset[str] = frozenset({"README.md"})

CUSTOM_CONFIG_GUIDE = "Guide: drone @seedgo standard json_structure"


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

    if is_bypassed(module_path, "json_structure", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "JSON STRUCTURE",
        }

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "JSON structure check", "passed": True, "message": "__init__.py file (skipped)"}],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "JSON STRUCTURE",
        }

    path_str = str(path)

    # --- Case (a): json_handler.py in a json/ directory ---
    if "json_handler" in path.name and path.parent.name == "json":
        checks = _check_json_handler_config(path, content, bypass_rules)
        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {"passed": score >= 75, "checks": checks, "score": score, "standard": "JSON STRUCTURE"}

    # --- Determine if the file is in modules/ or handlers/ ---
    in_modules = "apps/modules" in path_str or "apps\\modules" in path_str
    in_handlers = "apps/handlers" in path_str or "apps\\handlers" in path_str

    # Exclude files inside the json/ handler directory itself (they ARE the
    # json infrastructure, not consumers of it)
    if in_handlers and path.parent.name == "json":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "JSON structure check",
                    "passed": True,
                    "message": "JSON handler infrastructure file (not applicable)",
                }
            ],
            "score": 100,
            "standard": "JSON STRUCTURE",
        }

    # --- Cases (b) and (c): code wiring check ---
    if in_modules or in_handlers:
        checks = _check_code_wiring(path, content)
        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = int((passed_count / total * 100)) if total > 0 else 0
        return {"passed": passed_count == total, "checks": checks, "score": score, "standard": "JSON STRUCTURE"}

    # --- Case (d): file outside modules/ and handlers/ (entry point, etc.) ---
    return {
        "passed": True,
        "checks": [
            {"name": "JSON structure check", "passed": True, "message": "Not in modules/ or handlers/ (not applicable)"}
        ],
        "score": 100,
        "standard": "JSON STRUCTURE",
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
        re.search(r"from\s+\S*\.json\s+import\s+json_handler", content)
        or re.search(r"from\s+\S*json\s+import\s+json_handler", content)
        or re.search(r"import\s+json_handler", content)
    )
    checks.append(
        {
            "name": "json_handler import",
            "passed": has_import,
            "message": "Imports json_handler"
            if has_import
            else "Missing json_handler import — add: from aipass.<branch>.apps.handlers.json import json_handler",
        }
    )

    # Check 2: calls json_handler.log_operation()
    has_log_operation = "json_handler.log_operation" in content
    checks.append(
        {
            "name": "log_operation call",
            "passed": has_log_operation,
            "message": "Calls json_handler.log_operation()"
            if has_log_operation
            else "Missing json_handler.log_operation() call — every module/handler must log operations",
        }
    )

    return checks  # noqa: RET504


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
    has_path_home = bool(re.search(r"Path\.home\(\)", content))
    # Only flag _ROOT constants that use Path.home() (legacy pattern)
    # Allow _ROOT = Path(__file__).resolve()... (relative, pip-safe)
    has_branch_root = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r"\w+_ROOT\s*=", stripped) and "Path.home()" in stripped:
            has_branch_root = True
            break

    if has_path_home or has_branch_root:
        issues = []
        if has_path_home:
            issues.append("Path.home()")
        if has_branch_root:
            issues.append("hardcoded _ROOT constant")
        checks.append(
            {
                "name": "No absolute paths",
                "passed": False,
                "message": f"Found {', '.join(issues)} — pip packages should use relative paths",
            }
        )
    else:
        checks.append(
            {
                "name": "No absolute paths",
                "passed": True,
                "message": "No hardcoded absolute paths (correct for pip packages)",
            }
        )

    # Check 2: Uses relative path resolution
    has_relative = bool(
        re.search(r"Path\(__file__\)", content)
        or re.search(r"\.resolve\(\)", content)
        or re.search(r"\.parent", content)
    )

    checks.append(
        {
            "name": "Relative path resolution",
            "passed": has_relative,
            "message": "Uses relative path resolution (Path(__file__).parent)"
            if has_relative
            else "Missing relative path resolution — should use Path(__file__).resolve().parent",
        }
    )

    # Check 3: No template directory references
    # The standard says: "The CODE PATTERN is the template -- no json_templates/ directory"
    # Check for path constants or strings referencing json_templates
    has_template_dir = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "json_templates" in stripped:
            has_template_dir = True
            break

    checks.append(
        {
            "name": "No template directory",
            "passed": not has_template_dir,
            "message": "No json_templates/ references (correct — code is the template)"
            if not has_template_dir
            else "References json_templates/ directory — use auto-create from code defaults, not file templates",
        }
    )

    # Check 4: No load_template() function
    # The correct pattern uses inline defaults (_create_default or similar).
    # A load_template() that reads from files violates the auto-create principle.
    has_load_template = bool(re.search(r"def\s+load_template\s*\(", content))

    checks.append(
        {
            "name": "No file-based templates",
            "passed": not has_load_template,
            "message": "No load_template() function (correct — uses inline code defaults)"
            if not has_load_template
            else "Has load_template() function — standard requires inline code defaults, not file-based templates",
        }
    )

    return checks


# ------------------------------------------------------------------
# Branch-level post-check: {branch}_json/ directory structure
# ------------------------------------------------------------------


def _find_json_dir(branch_path: str) -> Path | None:
    """Locate {branch}_json/ under a branch root."""
    bp = Path(branch_path)
    json_dir = bp / f"{bp.name}_json"
    return json_dir if json_dir.is_dir() else None


def _check_json_dir_structure(branch_path: str, bypass_rules: list | None = None) -> list[dict]:
    """Validate {branch}_json/ has no unsanctioned subdirectories.

    Allowed: custom_config/ (operator-editable config).
    Hidden dirs (starting with '.') are ignored (e.g. .archive).
    Bypassed subdirs (via .seedgo/bypass.json) are also allowed.
    """
    json_dir = _find_json_dir(branch_path)
    if json_dir is None:
        return []

    bp = Path(branch_path)
    violations = []
    for child in sorted(json_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.name in ALLOWED_JSON_SUBDIRS:
            continue
        relative = f"{bp.name}_json/{child.name}"
        if is_bypassed(relative, "json_structure", bypass_rules=bypass_rules):
            continue
        violations.append(
            {
                "file": child.name,
                "path": str(child),
                "score": 0,
                "issues": [f"Unsanctioned subdir '{child.name}/' under {json_dir.name}/ — only custom_config/ allowed"],
                "message": (
                    f"Unsanctioned subdir '{child.name}/' under {json_dir.name}/ — only custom_config/ allowed"
                ),
            }
        )
    return violations


def check_branch_post(branch_path: str, bypass_rules: list | None = None) -> tuple[list, list]:
    """Post-audit check: validate {branch}_json/ directory structure."""
    violations = _check_json_dir_structure(branch_path, bypass_rules=bypass_rules)
    scores = [0] if violations else [100]
    return violations, scores


# ------------------------------------------------------------------
# Branch-level info channel: custom_config/ signpost (never scored)
# ------------------------------------------------------------------


def _custom_config_files(branch_path: str) -> list[str]:
    """Filenames the operator put in {branch}_json/custom_config/ (README excluded)."""
    json_dir = _find_json_dir(branch_path)
    if json_dir is None:
        return []
    custom_config = json_dir / CUSTOM_CONFIG_DIR
    if not custom_config.is_dir():
        return []
    return sorted(p.name for p in custom_config.iterdir() if p.is_file() and p.name not in CUSTOM_CONFIG_SKIP_FILES)


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines for the json_structure standard.

    custom_config/ is operator-owned: seedgo never reads or judges its
    contents. This lists the filenames only, so a live operator override is
    visible in the audit instead of invisible. Returns plain strings on the
    audit's info channel — it can never reach a score by construction.
    """
    files = _custom_config_files(branch_path)
    if not files:
        return []
    noun = "file" if len(files) == 1 else "files"
    return [
        f"{Path(branch_path).name}_json/{CUSTOM_CONFIG_DIR}/: {len(files)} operator {noun} "
        f"({', '.join(files)}) — content not audited. {CUSTOM_CONFIG_GUIDE}"
    ]
