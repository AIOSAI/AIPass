# =================== AIPass ====================
# Name: entry_point_diff_content.py
# Description: queryable content for the entry_point_diff nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `entry_point_diff` static nominator.

DERIVED, NEVER RESTATED. The text comes from `entry_point_diff_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.entry_point_diff_check import SPECIFICATION


def get_entry_point_diff_standards() -> str:
    """Return the entry_point_diff nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("entry_point_diff", SPECIFICATION)
