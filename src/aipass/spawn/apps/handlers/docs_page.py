# =================== AIPass ====================
# Name: docs_page.py
# Description: The docs page skeleton read — the one source @seedgo's docs_page standard renders
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""The docs/*.md page skeleton, read live for @seedgo (DPLAN-0351)."""

from pathlib import Path

# Beside templates/citizen/, never inside: everything in that tree is stamped into every newborn.
DOCS_PAGE_TEMPLATE = Path(__file__).parents[2] / "templates" / "docs_page.md"


def docs_page_template() -> str:
    """Return the docs page skeleton text, read from disk on every call."""
    return DOCS_PAGE_TEMPLATE.read_text(encoding="utf-8")
