# =================== AIPass ====================
# Name: readme_quality_check.py
# Description: README Quality Standards Checker Handler
# Version: 1.0.0
# Created: 2026-07-17
# Modified: 2026-10-17
# =============================================

"""
README Quality Standards Checker Handler

Validates README.md content quality from a stranger's perspective.
Orthogonal to readme_check.py which validates structural completeness.
"""

import re
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: README.md through the entry point.
APPLIES_TO = "production"
AUDIT_SCOPE = "entry_point"

# Internal AIPass branch names — a stranger would not recognise these
# without context. "aipass" is excluded because it is the project name
# itself and appears unavoidably in every branch description.
_INTERNAL_NAMES = frozenset(
    {
        "drone",
        "devpulse",
        "ai_mail",
        "flow",
        "seedgo",
        "prax",
        "memory",
        "spawn",
        "hooks",
        "trigger",
        "api",
        "cli",
        "skills",
        "daemon",
        "commons",
        "backup",
    }
)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if branch README meets content-quality standards."""
    checks: List[Dict] = []

    if Path(module_path).name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "README quality", "passed": True, "message": "__init__.py file (skipped)"}],
            "score": 100,
            "standard": "README_QUALITY",
        }

    if is_bypassed(module_path, "readme_quality", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "README_QUALITY",
        }

    # Derive branch root: module_path is apps/{branch}.py, go up 2 levels
    entry_path = Path(module_path)
    branch_root = entry_path.parent.parent
    branch_name = branch_root.name

    readme_path = branch_root / "README.md"
    if not readme_path.exists():
        fail_msg = "README.md not found at branch root"
        for name in ["quick_start", "stranger_accessible", "invoke_match", "what_description"]:
            checks.append({"name": name, "passed": False, "message": fail_msg})

        return {"passed": False, "checks": checks, "score": 0, "standard": "README_QUALITY"}

    try:
        content = readme_path.read_text(encoding="utf-8")
        lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read README at %s: %s", readme_path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading README: {e}"}],
            "score": 0,
            "standard": "README_QUALITY",
        }

    checks.append(_check_quick_start(lines, module_path, bypass_rules))

    checks.append(_check_stranger_accessible(lines, module_path, bypass_rules))

    checks.append(_check_invoke_match(lines, branch_name, module_path, bypass_rules))

    checks.append(_check_what_description(lines, module_path, bypass_rules))

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = all(c["passed"] for c in checks)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "readme_quality"},
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "README_QUALITY"}


def _check_quick_start(lines: List[str], file_path: str, bypass_rules: list | None) -> Dict:
    """README must have a Quick Start / Getting Started section with at least one fenced code block."""
    if is_bypassed(file_path, "readme_quality", None, bypass_rules):
        return {"name": "quick_start", "passed": True, "message": "Bypassed by bypass rules"}

    qs_pattern = re.compile(r"^(#{1,6})\s+.*(quick\s*start|getting\s+started)", re.IGNORECASE)
    section_start: int | None = None
    section_level: int = 0

    for i, line in enumerate(lines):
        m = qs_pattern.match(line)
        if m:
            section_start = i
            section_level = len(m.group(1))
            break

    if section_start is None:
        return {
            "name": "quick_start",
            "passed": False,
            "message": "README must have a Quick Start section with at least one runnable command example",
        }

    # Scan from section heading to next heading of equal or higher level (or EOF)
    has_code_block = False
    for j in range(section_start + 1, len(lines)):
        stripped = lines[j].strip()
        heading_match = re.match(r"^(#{1,6})\s+", lines[j])
        if heading_match and len(heading_match.group(1)) <= section_level:
            break
        if stripped.startswith("```"):
            has_code_block = True
            break

    if has_code_block:
        return {"name": "quick_start", "passed": True, "message": "Quick Start section found with code example"}

    return {
        "name": "quick_start",
        "passed": False,
        "message": "README must have a Quick Start section with at least one runnable command example",
    }


def _check_stranger_accessible(lines: List[str], file_path: str, bypass_rules: list | None) -> Dict:
    """First 5 content lines must not reference more than 2 unique internal branch names."""
    if is_bypassed(file_path, "readme_quality", None, bypass_rules):
        return {"name": "stranger_accessible", "passed": True, "message": "Bypassed by bypass rules"}

    names_pattern = re.compile(
        r"\b(" + "|".join(re.escape(n) for n in sorted(_INTERNAL_NAMES, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )

    # Collect first 5 non-empty, non-heading lines after the title heading
    content_lines: List[str] = []
    past_title = False
    for line in lines:
        stripped = line.strip()
        if not past_title:
            if stripped.startswith("#"):
                past_title = True
            continue
        if not stripped or stripped.startswith("#"):
            continue
        content_lines.append(stripped)
        if len(content_lines) >= 5:
            break

    if not content_lines:
        return {
            "name": "stranger_accessible",
            "passed": True,
            "message": "No content lines found to check (skipped)",
        }

    found_names: set = set()
    for cl in content_lines:
        for m in names_pattern.finditer(cl):
            found_names.add(m.group(1).lower())

    if len(found_names) > 2:
        sorted_names = ", ".join(sorted(found_names))
        return {
            "name": "stranger_accessible",
            "passed": False,
            "message": (
                f"First paragraph references {len(found_names)} internal branches"
                f" ({sorted_names}) — strangers won't understand without context"
            ),
        }

    return {
        "name": "stranger_accessible",
        "passed": True,
        "message": f"First paragraph references {len(found_names)} internal branch name(s) (limit 2)",
    }


def _check_invoke_match(lines: List[str], branch_name: str, file_path: str, bypass_rules: list | None) -> Dict:
    """If an Invoke / Usage / How to Run section exists, its command should reference the branch name."""
    if is_bypassed(file_path, "readme_quality", None, bypass_rules):
        return {"name": "invoke_match", "passed": True, "message": "Bypassed by bypass rules"}

    heading_pattern = re.compile(r"^(#{1,6})\s+.*(invoke|usage|how\s+to\s+run)", re.IGNORECASE)
    section_start: int | None = None
    section_level: int = 0

    for i, line in enumerate(lines):
        m = heading_pattern.match(line)
        if m:
            section_start = i
            section_level = len(m.group(1))
            break

    if section_start is None:
        return {
            "name": "invoke_match",
            "passed": True,
            "message": "No invoke section found — skipped",
        }

    section_content: List[str] = []
    for j in range(section_start + 1, len(lines)):
        heading_match = re.match(r"^(#{1,6})\s+", lines[j])
        if heading_match and len(heading_match.group(1)) <= section_level:
            break
        section_content.append(lines[j])

    section_text = "\n".join(section_content)

    if re.search(re.escape(branch_name), section_text, re.IGNORECASE):
        return {
            "name": "invoke_match",
            "passed": True,
            "message": f"Invoke section references branch '{branch_name}'",
        }

    if re.search(r"drone\s+@" + re.escape(branch_name), section_text, re.IGNORECASE):
        return {
            "name": "invoke_match",
            "passed": True,
            "message": f"Invoke section uses drone @{branch_name} pattern",
        }

    return {
        "name": "invoke_match",
        "passed": False,
        "message": f"Invoke section command does not match branch name '{branch_name}'",
    }


def _check_what_description(lines: List[str], file_path: str, bypass_rules: list | None) -> Dict:
    """README must describe what the branch does within the first 10 lines."""
    if is_bypassed(file_path, "readme_quality", None, bypass_rules):
        return {"name": "what_description", "passed": True, "message": "Bypassed by bypass rules"}

    # Collect first 10 lines, check for at least one non-heading, non-empty line > 20 chars
    for line in lines[:10]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(stripped) > 20:
            return {
                "name": "what_description",
                "passed": True,
                "message": "Description found within first 10 lines",
            }

    return {
        "name": "what_description",
        "passed": False,
        "message": "README must describe what the branch does within the first 10 lines",
    }
