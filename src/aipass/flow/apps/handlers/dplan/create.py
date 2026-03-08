#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: create.py - Plan creation handler
# Date: 2025-12-02
# Version: 2.0.0
# Category: devpulse/handlers/plan
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-02-19): Multi-type (DPLAN/BPLAN) + target_path for @ resolution
#   - v1.0.0 (2025-12-02): Extracted from dev_flow.py module
#
# CODE STANDARDS:
#   - Handler independence: NO cross-domain imports
#   - NO Prax logging (per 3-tier: modules log, handlers don't)
#   - Pure business logic only
# ==============================================

"""
Create Handler - Plan File Creation

Creates new plan files (DPLAN, BPLAN) with proper naming and content.
Supports @ branch resolution via target_path parameter.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Tuple, Dict, Any

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

from .counter import get_next_plan_number, VALID_PLAN_TYPES
from .template import render_template

# =============================================================================
# CONFIGURATION
# =============================================================================

DEV_PLANNING_ROOT = Path.home() / "aipass_os" / "dev_central" / "dev_planning"


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def create_plan(
    topic: str,
    tag: str = "idea",
    plan_type: str = "dplan",
    target_path: Path | None = None,
    subdir: str | None = None
) -> Tuple[bool, Dict[str, Any], str]:
    """
    Create a new plan file.

    Args:
        topic: Topic name for the plan
        tag: Plan tag classification (default: idea)
        plan_type: Plan type - dplan or bplan (default: dplan)
        target_path: Branch path for @ resolution (creates dev_planning/ there).
                     None defaults to dev_central/dev_planning/.
        subdir: Optional subdirectory within dev_planning/

    Returns:
        Tuple of (success, result_data, error_message)
        result_data contains: plan_number, filename, path, topic, tag, plan_type, date, subdir
    """
    if not topic or not topic.strip():
        return False, {}, "Topic is required"

    topic = topic.strip()

    # Validate plan type
    plan_type_lower = plan_type.lower()
    if plan_type_lower not in VALID_PLAN_TYPES:
        valid = ", ".join(VALID_PLAN_TYPES.keys())
        return False, {}, f"Invalid plan type '{plan_type}'. Valid types: {valid}"

    prefix = VALID_PLAN_TYPES[plan_type_lower]

    # Determine planning root
    if target_path:
        planning_root = target_path / "dev_planning"
    else:
        planning_root = DEV_PLANNING_ROOT

    # Sanitize topic for filename (snake_case)
    topic_slug = re.sub(r'[^\w\s-]', '', topic.lower())
    topic_slug = re.sub(r'[\s-]+', '_', topic_slug)
    topic_slug = topic_slug[:40]  # Limit length

    # Determine target directory
    if subdir:
        # Sanitize subdir name (alphanumeric and underscore only)
        subdir = re.sub(r'[^\w-]', '', subdir.strip())
        if not subdir:
            return False, {}, "Invalid subdirectory name"
        target_dir = planning_root / subdir
    else:
        target_dir = planning_root

    # Get next number for this plan type in this directory
    plan_number, cache_err = get_next_plan_number(
        plan_type=prefix,
        planning_root=planning_root
    )

    date_str = datetime.now().strftime("%Y-%m-%d")

    # Build filename: PREFIX-XXX_topic_name_YYYY-MM-DD.md
    filename = f"{prefix}-{plan_number:03d}_{topic_slug}_{date_str}.md"
    plan_path = target_dir / filename

    # Render template
    content, template_err = render_template(
        plan_number, topic, date_str, tag=tag, plan_type=plan_type_lower
    )
    if template_err:
        return False, {}, f"Failed to render template: {template_err}"

    # Create file
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(content, encoding='utf-8')

        result = {
            "plan_number": plan_number,
            "filename": filename,
            "path": str(plan_path),
            "topic": topic,
            "tag": tag,
            "plan_type": plan_type_lower,
            "prefix": prefix,
            "date": date_str,
            "subdir": subdir,
            "target_branch": str(target_path) if target_path else None,
            "cache_warning": cache_err
        }

        return True, result, ""

    except Exception as e:
        return False, {}, f"Failed to write file: {e}"
