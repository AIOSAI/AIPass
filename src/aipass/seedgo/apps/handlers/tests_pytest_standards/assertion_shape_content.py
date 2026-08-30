# =================== AIPass ====================
# Name: assertion_shape_content.py
# Description: queryable content for the assertion_shape nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `assertion_shape` static nominator.

DERIVED, NEVER RESTATED. The text comes from `assertion_shape_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.assertion_shape_check import SPECIFICATION


def get_assertion_shape_standards() -> str:
    """Return the assertion_shape nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("assertion_shape", SPECIFICATION)
