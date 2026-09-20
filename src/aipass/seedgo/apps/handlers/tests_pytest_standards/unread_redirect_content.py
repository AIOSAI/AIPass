# =================== AIPass ====================
# Name: unread_redirect_content.py
# Description: queryable content for the unread_redirect nominator
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Queryable content for the `unread_redirect` static nominator.

DERIVED, NEVER RESTATED. The text comes from `unread_redirect_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.unread_redirect_check import SPECIFICATION


def get_unread_redirect_standards() -> str:
    """Return the unread_redirect nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("unread_redirect", SPECIFICATION)
