# =================== AIPass ====================
# Name: get_template.py
# Description: Get Template Handler
# Version: 1.3.1
# Created: 2025-11-30
# Modified: 2026-10-17
# =============================================

"""Get Template Handler"""

import re
from pathlib import Path
from datetime import datetime

from aipass.flow.apps.handlers.json import json_handler

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]

MODULE_NAME = "get_template"
FLOW_ROOT = _PKG_ROOT / "flow"
TEMPLATES_DIR = FLOW_ROOT / "templates"
DEFAULT_TEMPLATE = "default"

# The only brace tokens treated as placeholders; every other brace is literal prose.
PLACEHOLDER_NAMES = ("number", "subject", "location", "today", "prefix", "plan_number", "tag")
_PLACEHOLDER_PATTERN = re.compile(r"\{(" + "|".join(PLACEHOLDER_NAMES) + r")\}")


def _substitute_placeholders(content: str, values: dict[str, str]) -> str:
    """Replace known placeholders, leaving every other brace sequence verbatim.

    Not str.format(): templates contain code and JSON braces, which it rejects with KeyError.
    A known name with no value passes through verbatim, so a template never fails to stamp.
    """
    return _PLACEHOLDER_PATTERN.sub(lambda match: values.get(match.group(1), match.group(0)), content)


def _template_search_dirs() -> list[Path]:
    """Determine the ordered list of directories to search for templates"""
    return [TEMPLATES_DIR]


def _find_template_file(template_name: str) -> Path:
    """Locate the requested template (or default fallback) across supported directories.

    Raises FileNotFoundError, listing the available templates; there is no fallback.
    """
    search_paths = _template_search_dirs()

    candidate = search_paths[0] / f"{template_name}.md"
    if candidate.exists():
        return candidate

    available = [p.stem for p in search_paths[0].iterdir() if p.suffix == ".md"] if search_paths[0].is_dir() else []
    searched = ", ".join(str(path) for path in search_paths)
    error_msg = f"Template '{template_name}' not found in: {searched}. Available: {available if available else 'none'}"
    raise FileNotFoundError(error_msg)


def get_template(
    template_name: str = "default",
    number: int = 0,
    location: str = "",
    subject: str = "",
    template_path: Path | None = None,
    prefix: str = "FPLAN",
    digits: int = 4,
) -> str:
    """Load and format a PLAN template.

    *template_path* wins over the ``templates/`` lookup by *template_name*.
    """
    try:
        if template_path is not None:
            template_file = template_path
        else:
            template_file = _find_template_file(template_name)

        with open(template_file, "r", encoding="utf-8") as f:
            template_content = f.read()

        today = datetime.now().strftime("%Y-%m-%d")

        formatted_number = f"{number:0{digits}d}"
        plan_number = f"{prefix}-{formatted_number}"

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
