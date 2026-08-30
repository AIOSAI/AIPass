# =================== AIPass ====================
# Name: unentered_assert_content.py
# Description: queryable content for the unentered_assert nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `unentered_assert` static nominator.

DERIVED, NEVER RESTATED. The text comes from `unentered_assert_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.unentered_assert_check import SPECIFICATION


def get_unentered_assert_standards() -> str:
    """Return the unentered_assert nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("unentered_assert", SPECIFICATION)
