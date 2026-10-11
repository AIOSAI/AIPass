# =================== AIPass ====================
# Name: tautology_assert_content.py
# Description: queryable content for the tautology_assert nominator
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Queryable content for the `tautology_assert` static nominator.

DERIVED, NEVER RESTATED. The text comes from `tautology_assert_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.tautology_assert_check import SPECIFICATION


def get_tautology_assert_standards() -> str:
    """Return the tautology_assert nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("tautology_assert", SPECIFICATION)
