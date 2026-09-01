# =================== AIPass ====================
# Name: empty_parametrize_content.py
# Description: queryable content for the empty_parametrize nominator
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Queryable content for the `empty_parametrize` static nominator.

DERIVED, NEVER RESTATED. The text comes from `empty_parametrize_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.empty_parametrize_check import SPECIFICATION


def get_empty_parametrize_standards() -> str:
    """Return the empty_parametrize nominator's specification, Rich-rendered.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("empty_parametrize", SPECIFICATION)
