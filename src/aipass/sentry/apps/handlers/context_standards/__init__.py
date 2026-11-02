# =================== AIPass ====================
# Name: __init__.py
# Description: context standards pack — the startup cost of a citizen
# Version: 1.2.0
# Created: 2026-09-15
# Modified: 2026-11-02
# =============================================

"""The context pack. One rule: what a greeting costs, in characters.

Its own pack so `audit context` runs alone; the audit row is advisory, the CI ratchets gate.
"""

__version__ = "0.2.0"

#: Re-exported for `.github/scripts/sentry_audit.py`, a caller outside the tree the dead-code rule sees.
from aipass.sentry.apps.handlers.context_standards import name_ratchet  # (re-exported)
from aipass.sentry.apps.handlers.context_standards import startup_ratchet  # (re-exported)
