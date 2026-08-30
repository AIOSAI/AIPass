# =================== AIPass ====================
# Name: capture_never_read_content.py
# Description: queryable content for the capture_never_read nominator
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""Queryable content for the `capture_never_read` static nominator.

DERIVED, NEVER RESTATED. The text comes from `capture_never_read_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.capture_never_read_check import SPECIFICATION


def get_capture_never_read_standards() -> str:
    """Return the capture_never_read nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("capture_never_read", SPECIFICATION)
