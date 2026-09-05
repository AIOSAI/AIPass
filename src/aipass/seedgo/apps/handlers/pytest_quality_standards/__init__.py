# =================== AIPass ====================
# Name: __init__.py
# Description: generic pytest test-quality scoring pack
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""The pytest_quality pack. A SCORING pack that judges what a test proves.

Generic by construction: the checkers read a project's tests with `ast` and
nothing else, so this directory lifts onto any Python project. That is the whole
reason it is not folded into `aipass_standards` (DPLAN-0323, Patrick's ruling).

NAMED `pytest_quality_standards` AND NOT `tests_standards` ON PURPOSE. Packs are
keyed by their directory name minus the `_standards` suffix, and `audit tests` is
already the execution lane's word - a pack keyed `tests` makes the verb ambiguous
and the audit refuses it by design rather than silently preferring one meaning.

ADVISORY WHILE IT IS YOUNG. Every check here reports `passed: True` and carries
`advisory: True` during the shadow cycle: v5 scores the fleet but gates nothing
until its numbers have been diffed against the calibrated triage. A standard that
starts by failing boards it has never been measured against would be repeating the
mistake this pack was built to correct.
"""

__version__ = "0.1.0"
