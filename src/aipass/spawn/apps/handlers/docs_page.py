# =================== AIPass ====================
# Name: docs_page.py
# Description: The docs page skeleton read — the one source @seedgo's docs_page standard renders
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""The docs/*.md page skeleton, read live for @seedgo (DPLAN-0351).

The owner ruled that every branch's docs/ pages share one shape, scored by
@seedgo's docs_page standard. The skeleton that shows the shape has one source,
spawn's template tree, and seedgo reads it through the modules gateway on every
render — never a copy on either side.

It sits BESIDE ``templates/citizen/``, never inside it. Everything in the
citizen tree is stamped into every newborn, and a skeleton stamped as a docs/
page would be a placeholder page in every branch. Beside the tree no walk
reaches it: not the copy, not the manifest a mint is verified against, not the
update engine.

It reads and returns and performs no operation of its own, so it carries no
logger: the render is seedgo's operation, and seedgo logs it.
"""

from pathlib import Path

DOCS_PAGE_TEMPLATE = Path(__file__).parents[2] / "templates" / "docs_page.md"


def docs_page_template() -> str:
    """Return the docs page skeleton text, read from disk on every call.

    Raises OSError when the skeleton is missing or unreadable, so the caller can
    say the door is unreachable. There is no fallback shape.
    """
    return DOCS_PAGE_TEMPLATE.read_text(encoding="utf-8")
