# =================== AIPass ====================
# Name: drifted_inventory_content.py
# Description: queryable content for the drifted_inventory nominator
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Queryable content for the `drifted_inventory` static nominator.

DERIVED, NEVER RESTATED. The text comes from `drifted_inventory_check.py`'s own
`SPECIFICATION`, so the documentation and the detector cannot disagree. A
content file maintained by hand beside a checker is two statements of one rule
that can drift, and the one a reader trusts is the prose - which is the exact
species this campaign exists to catch, in the auditor's own pack. It is also
the species this particular rule is about, one level up: a hand-kept statement
that claims to describe something and stops doing so.
"""

from aipass.seedgo.apps.handlers.tests_pytest_standards import render_spec
from aipass.seedgo.apps.handlers.tests_pytest_standards.drifted_inventory_check import SPECIFICATION


def get_drifted_inventory_standards() -> str:
    """Return the drifted_inventory nominator's specification, rendered with Rich markup.

    Returns:
        str: Formatted standards text derived from the checker's SPECIFICATION
    """
    return render_spec.render("drifted_inventory", SPECIFICATION)
