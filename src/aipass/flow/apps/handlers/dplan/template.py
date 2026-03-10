# =================== AIPass ====================
# Name: template.py
# Description: Plan template management
# Version: 2.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
Template Handler - Plan Templates

Manages template loading and rendering for plan documents.
Supports multiple plan types with type-specific templates.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
from pathlib import Path
from typing import Tuple

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

# =============================================================================
# CONFIGURATION
# =============================================================================

# template.py → dplan/ → handlers/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = FLOW_ROOT / "templates"

DPLAN_DEFAULT_TEMPLATE = """# DPLAN-{{NUMBER}}: {{TOPIC}}

Tag: {{TAG}}

> One-line description

## Vision
What we're trying to achieve

## Current State
What exists now

## What Needs Building
Concrete items to build

## Design Decisions
Key choices and why

## Status
- [x] Planning
- [ ] In Progress
- [ ] Ready for Execution
- [ ] Complete
- [ ] Abandoned

## Notes
Session notes, discoveries, changes

---
*Created: {{DATE}}*
*Updated: {{DATE}}*
"""

BPLAN_DEFAULT_TEMPLATE = """# BPLAN-{{NUMBER}}: {{TOPIC}}

Tag: {{TAG}}

> One-line description

## Executive Summary
What this business initiative achieves and why it matters.

## Market Analysis
Target market, size, trends, and opportunity.

## Revenue Model
How this generates or saves revenue. Pricing, margins, unit economics.

## Competitive Landscape
Who else is doing this? What's our edge?

## KPIs
| Metric | Target | Timeline |
|--------|--------|----------|
| Example | TBD | Q1 2026 |

## Go-to-Market
Launch strategy, channels, partnerships.

## Risk Assessment
| Risk | Impact | Mitigation |
|------|--------|------------|
| Example | High | Plan B |

## Timeline
- [ ] Phase 1: Research & Validation
- [ ] Phase 2: MVP / Pilot
- [ ] Phase 3: Scale

## Budget Considerations
Estimated costs, resource requirements, ROI timeline.

## Relationships
- **Related BPLANs:** None yet
- **Related DPLANs:** None yet
- **Owner branches:** Who owns this

## Status
- [x] Planning
- [ ] In Progress
- [ ] Ready for Execution
- [ ] Complete
- [ ] Abandoned

## Notes
Session notes, discoveries, changes

---
*Created: {{DATE}}*
*Updated: {{DATE}}*
"""

DEFAULT_TEMPLATES = {
    "dplan": DPLAN_DEFAULT_TEMPLATE,
    "bplan": BPLAN_DEFAULT_TEMPLATE,
}


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def get_default_template(plan_type: str = "dplan") -> str:
    """
    Return built-in default template for the given plan type.

    Args:
        plan_type: Plan type (dplan, bplan). Case-insensitive.

    Returns:
        Template string with {{NUMBER}}, {{TOPIC}}, {{DATE}}, {{TAG}} placeholders
    """
    return DEFAULT_TEMPLATES.get(plan_type.lower(), DPLAN_DEFAULT_TEMPLATE)


def render_template(
    plan_number: int,
    topic: str,
    date_str: str,
    tag: str = "idea",
    plan_type: str = "dplan"
) -> Tuple[str, str]:
    """
    Render plan template with variables.

    Loads custom template if available, falls back to built-in default.
    Replaces {{NUMBER}}, {{TOPIC}}, {{DATE}}, {{TAG}} placeholders.

    Args:
        plan_number: The plan number (e.g., 42)
        topic: Topic name
        date_str: Date string (YYYY-MM-DD)
        tag: Plan tag classification (default: idea)
        plan_type: Plan type (dplan, bplan). Default: dplan.

    Returns:
        Tuple of (rendered_content, error_message)
        Error message is empty on success
    """
    plan_type_lower = plan_type.lower()

    # Try to load custom template for this type
    template_content = None
    template_file = TEMPLATE_DIR / f"{plan_type_lower}_default.md"
    if template_file.exists():
        try:
            template_content = template_file.read_text(encoding='utf-8')
        except Exception:
            template_content = None

    if template_content is None:
        template_content = get_default_template(plan_type_lower)

    # Replace placeholders
    prefix = plan_type.upper()
    content = template_content.replace("{{NUMBER}}", f"{plan_number:03d}")
    content = content.replace("{{TOPIC}}", topic)
    content = content.replace("{{DATE}}", date_str)
    content = content.replace("{{TAG}}", tag)

    # Handle templates that use hardcoded DPLAN prefix — replace with correct type
    if prefix != "DPLAN" and content.startswith("# DPLAN-"):
        content = content.replace("# DPLAN-", f"# {prefix}-", 1)

    return content, ""
