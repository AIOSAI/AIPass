# =================== AIPass ====================
# Name: get_template.py
# Description: Get Template Handler
# Version: 1.3.1
# Created: 2025-11-30
# Modified: 2026-08-08
# =============================================

"""
Get Template Handler

Loads and formats PLAN templates from template directories.

Features:
- Loads templates from the flow/templates/ directory (package-relative)
- Supports placeholder replacement ({number}, {subject}, {location}, {today})
- Literal braces in template prose (code snippets, JSON) pass through untouched
- Automatic fallback to default template
- Multi-directory search support
- Reusable across Flow modules

Usage:
    from aipass.flow.apps.handlers.template.get_template import get_template

    content = get_template("default", number=101, location="flow", subject="My Task")
    content = get_template("master", number=102, location="flow/DOCUMENTS", subject="Big Project")
"""

import re
from pathlib import Path
from datetime import datetime

from aipass.flow.apps.handlers.json import json_handler

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "get_template"
FLOW_ROOT = _PKG_ROOT / "flow"
TEMPLATES_DIR = FLOW_ROOT / "templates"
DEFAULT_TEMPLATE = "default"

# The only brace tokens treated as placeholders. Everything else in a template
# is literal prose and passes through untouched.
PLACEHOLDER_NAMES = ("number", "subject", "location", "today", "prefix", "plan_number", "tag")
_PLACEHOLDER_PATTERN = re.compile(r"\{(" + "|".join(PLACEHOLDER_NAMES) + r")\}")

# =============================================
# HELPER FUNCTIONS
# =============================================


def _substitute_placeholders(content: str, values: dict[str, str]) -> str:
    """
    Replace known placeholders, leaving every other brace sequence verbatim.

    Templates are documentation as much as scaffolding — SOP/playbook templates
    legitimately contain code snippets, JSON, and tool-call syntax with braces
    (``{createIfEmpty: true}``). ``str.format()`` treats each of those as a
    replacement field and raises KeyError, which made whole templates
    un-instantiable. Matching only the known names cannot raise, so a template
    can never be broken by the prose it documents.

    A name in :data:`PLACEHOLDER_NAMES` with no supplied value passes through
    verbatim rather than raising: a template that loaded when it was registered
    must still load when it is stamped, so an unsupplied optional key degrades
    to the literal placeholder instead of killing the whole template.

    Args:
        content: Raw template text
        values: Placeholder name -> replacement value

    Returns:
        Template text with known placeholders substituted
    """
    return _PLACEHOLDER_PATTERN.sub(lambda match: values.get(match.group(1), match.group(0)), content)


def _template_search_dirs() -> list[Path]:
    """Determine the ordered list of directories to search for templates"""
    return [TEMPLATES_DIR]


def _find_template_file(template_name: str) -> Path:
    """
    Locate the requested template (or default fallback) across supported directories.

    Args:
        template_name: Name of template (without .md extension)

    Returns:
        Path to template file

    Raises:
        FileNotFoundError: When neither the requested nor default template exists
    """
    search_paths = _template_search_dirs()

    # Look for the requested template — no fallback
    candidate = search_paths[0] / f"{template_name}.md"
    if candidate.exists():
        return candidate

    # Not found — error with available templates
    available = [p.stem for p in search_paths[0].iterdir() if p.suffix == ".md"] if search_paths[0].is_dir() else []
    searched = ", ".join(str(path) for path in search_paths)
    error_msg = f"Template '{template_name}' not found in: {searched}. Available: {available if available else 'none'}"
    raise FileNotFoundError(error_msg)


# =============================================
# HANDLER FUNCTION
# =============================================


def get_template(
    template_name: str = "default",
    number: int = 0,
    location: str = "",
    subject: str = "",
    template_path: Path | None = None,
    prefix: str = "FPLAN",
    digits: int = 4,
) -> str:
    """
    Load and format a PLAN template.

    When *template_path* is provided the file is loaded directly from
    that path (used by the plan_types plugin system).  Otherwise the
    legacy ``templates/`` directory lookup is used as a fallback.

    Args:
        template_name: Name of template file (without .md extension)
        number: PLAN number for formatting
        location: Plan location (relative path)
        subject: Plan subject/title
        template_path: Absolute path to a template file.  Bypasses
            the old ``templates/`` directory lookup when set.
        prefix: Plan prefix (e.g. "FPLAN", "DPLAN") used for
            ``{prefix}`` and ``{plan_number}`` placeholders.
        digits: Number of zero-padded digits in the plan number.

    Returns:
        Formatted template content with placeholders replaced

    Raises:
        FileNotFoundError: If template not found
        Exception: If template loading/formatting fails

    Examples:
        >>> get_template("default", 101, "flow", "My Task")
        # Returns default.md with {number}->101, {subject}->"My Task", etc.

        >>> get_template("master", 102, "flow/DOCUMENTS", "Big Project")
        # Returns master.md with placeholders filled

        >>> get_template(template_path=Path(".../dev_plans/templates/default.md"),
        ...              number=4, subject="Design", prefix="DPLAN")
        # Returns DPLAN template with {plan_number}->"DPLAN-0004"
    """
    try:
        # Resolve template file
        if template_path is not None:
            template_file = template_path
        else:
            template_file = _find_template_file(template_name)

        # Read template file
        with open(template_file, "r", encoding="utf-8") as f:
            template_content = f.read()

        # Get current date for {today} placeholder
        today = datetime.now().strftime("%Y-%m-%d")

        # Build formatted number string (zero-padded)
        formatted_number = f"{number:0{digits}d}"
        plan_number = f"{prefix}-{formatted_number}"

        # Substitute placeholders (literal braces in template prose are preserved)
        formatted_content = _substitute_placeholders(
            template_content,
            {
                "number": formatted_number,
                "subject": subject,
                "location": location,
                "today": today,
                "prefix": prefix,
                "plan_number": plan_number,
                "tag": "",
            },
        )

        json_handler.log_operation(
            "template_loaded",
            {
                "template": template_file.stem,
                "plan_number": plan_number,
                "success": True,
            },
        )

        return formatted_content

    except Exception:
        raise
