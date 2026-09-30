# =================== AIPass ====================
# Name: template_check.py
# Description: Template/Boilerplate Detection Checker Handler
# Version: 1.0.0
# Created: 2026-07-01
# Modified: 2026-07-01
# =============================================

"""
Template/Boilerplate Detection Checker Handler

Detects files still left in un-configured template form and flags them
as advisory warnings. Never blocks the audit — surfaces loudly so
branches know they have unconfigured stub files.

Checks:
1. .aipass/aipass_local_prompt.md for template markers
2. README.md for template markers
3. .trinity/passport.json for template markers (the only spawn-templated artifact)

AUDIT_SCOPE: branch_level — runs once per branch via check_branch().
ADVISORY: always passes so it never blocks commits or audits.
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: an unresolved spawn marker is unresolved wherever it sits.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "branch_level"
ADVISORY = True

_DEFINITIVE_MARKERS = [
    "NEEDS CONFIGURATION",
    "{{BRANCHNAME}}",
    "{{BRANCH}}",
    "INSTRUCTIONS FOR FILLING OUT THIS TEMPLATE",
    "WHEN YOU'RE DONE",
]

_SINGLE_CURLY_RE = re.compile(r"\{[^{}\n]+\}")
_DOUBLE_CURLY_RE = re.compile(r"\{\{[^}]*\}\}")
_FENCED_BLOCK_RE = re.compile(r"(?:```|~~~).*?(?:```|~~~)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _strip_markdown_code(content: str) -> str:
    """Remove fenced code blocks and inline code spans."""
    content = _FENCED_BLOCK_RE.sub("", content)
    return _INLINE_CODE_RE.sub("", content)


def _find_markers(content: str, check_single_curly: bool, is_markdown: bool = False) -> list[str]:
    """Return list of matched template marker descriptions."""
    found: list[str] = []

    scan_content = _strip_markdown_code(content) if is_markdown else content
    scan_upper = scan_content.upper()

    for marker in _DEFINITIVE_MARKERS:
        if marker.upper() in scan_upper:
            found.append(marker)

    if check_single_curly:
        stripped = _DOUBLE_CURLY_RE.sub("", scan_content)
        curly_matches = _SINGLE_CURLY_RE.findall(stripped)
        if curly_matches:
            examples = curly_matches[:3]
            suffix = f" (+{len(curly_matches) - 3} more)" if len(curly_matches) > 3 else ""
            found.append(f"single-curly placeholders: {', '.join(examples)}{suffix}")

    return found


def _check_file(file_path: Path, bypass_rules: list | None) -> Dict:
    """Check a single target file for template markers."""
    rel = file_path.name
    if not file_path.exists():
        return {"name": rel, "passed": True, "message": f"{rel} not found (skipped)"}

    if is_bypassed(str(file_path), "template", bypass_rules=bypass_rules):
        return {"name": rel, "passed": True, "message": f"{rel} bypassed via .seedgo/bypass.json"}

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        logger.info("Cannot read %s for template check", file_path)
        return {"name": rel, "passed": True, "message": f"{rel} unreadable (skipped)"}

    is_markdown = file_path.suffix == ".md"
    is_prompt = file_path.name == "aipass_local_prompt.md"
    markers = _find_markers(content, check_single_curly=is_prompt, is_markdown=is_markdown)

    if not markers:
        return {"name": rel, "passed": True, "message": "no template markers"}

    marker_list = ", ".join(markers)
    return {
        "name": rel,
        "passed": False,
        "message": (
            f"⚠ still in template form — {file_path.name} contains"
            f" un-configured template markers ({marker_list})."
            f" Please configure it (see the spawn template for the sections"
            f" to fill), or add a template bypass in .seedgo/bypass.json"
            f" if intentional."
        ),
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check branch for un-configured template/boilerplate files.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/cli)
        bypass_rules: Standard bypass rules from .seedgo/bypass.json

    Returns:
        dict with passed=True (advisory), checks list, score, standard, advisory flag
    """
    bp = Path(branch_path)

    if is_bypassed(branch_path, "template", bypass_rules=bypass_rules):
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "template"},
        )
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Template check",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "TEMPLATE",
            "advisory": True,
        }

    checks: list[Dict] = []

    targets: list[Path] = [
        bp / ".aipass" / "aipass_local_prompt.md",
        bp / "README.md",
    ]
    passport = bp / ".trinity" / "passport.json"
    if passport.exists():
        targets.append(passport)

    for target in targets:
        checks.append(_check_file(target, bypass_rules))

    if not checks:
        checks.append({"name": "Template check", "passed": True, "message": "No target files found (skipped)"})

    failed_count = sum(1 for c in checks if not c["passed"])
    total = len(checks)
    score = int(((total - failed_count) / total) * 100) if total > 0 else 100

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "template",
            "warnings": failed_count,
            "advisory": True,
        },
    )

    return {
        "passed": True,
        "checks": checks,
        "score": score,
        "standard": "TEMPLATE",
        "advisory": True,
    }
