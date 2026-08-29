# =================== AIPass ====================
# Name: __init__.py - audit-tests MVP prototype package
# Description: package root; stdlib only, no aipass imports
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""MVP prototype of the ``audit-tests`` lane (FPLAN-0458 / DPLAN-0320).

Stdlib only, plus ruff through ``subprocess`` when it is present.  Nothing here
imports aipass code: the lane must run against any directory holding pytest
targets, including one that is not a branch at all.
"""

__version__ = "0.1.0"
