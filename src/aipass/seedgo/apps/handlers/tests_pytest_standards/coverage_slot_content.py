# =================== AIPass ====================
# Name: coverage_slot_content.py
# Description: queryable content for the coverage_slot nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `coverage_slot` static nominator.

DERIVED, NEVER RESTATED. The text comes from `coverage_slot_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.coverage_slot_check import SPECIFICATION


def get_coverage_slot_standards() -> str:
    """Return the coverage_slot nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("coverage_slot", SPECIFICATION)
