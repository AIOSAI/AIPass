# =================== AIPass ====================
# Name: posix_literal_content.py
# Description: queryable content for the posix_literal nominator
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Queryable content for the `posix_literal` static nominator.

DERIVED, NEVER RESTATED. The text comes from `posix_literal_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.posix_literal_check import SPECIFICATION


def get_posix_literal_standards() -> str:
    """Return the posix_literal nominator's specification, Rich-rendered.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("posix_literal", SPECIFICATION)
