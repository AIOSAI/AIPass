# =================== AIPass ====================
# Name: mock_drift_content.py
# Description: queryable content for the mock_drift nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `mock_drift` static nominator.

DERIVED, NEVER RESTATED. The text comes from `mock_drift_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.mock_drift_check import SPECIFICATION


def get_mock_drift_standards() -> str:
    """Return the mock_drift nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("mock_drift", SPECIFICATION)
