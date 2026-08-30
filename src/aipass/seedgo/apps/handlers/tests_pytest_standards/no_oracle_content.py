# =================== AIPass ====================
# Name: no_oracle_content.py
# Description: queryable content for the no_oracle nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `no_oracle` static nominator.

DERIVED, NEVER RESTATED. The text comes from `no_oracle_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.no_oracle_check import SPECIFICATION


def get_no_oracle_standards() -> str:
    """Return the no_oracle nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("no_oracle", SPECIFICATION)
