# =================== AIPass ====================
# Name: __init__.py
# Description: Compass handler package — devpulse-owned rated decision store
# Version: 1.0.0
# Created: 2026-06-16
# Modified: 2026-10-17
# =============================================

"""Compass — devpulse-owned, SQLite/FTS5-backed rated decision store.

Callers depend on this package, not on the ``store`` submodule.
"""

from aipass.devpulse.apps.handlers.compass.store import (
    DEFAULT_DB_PATH,
    VALID_RATINGS,
    VALID_SOURCES,
    VALID_STATUSES,
    add_decision,
    archive,
    find_conflicts,
    mark_surfaced,
    query_decisions,
    rate,
    recall_decisions,
    review,
    set_note,
    stats,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "VALID_RATINGS",
    "VALID_SOURCES",
    "VALID_STATUSES",
    "add_decision",
    "archive",
    "find_conflicts",
    "mark_surfaced",
    "query_decisions",
    "rate",
    "recall_decisions",
    "review",
    "set_note",
    "stats",
]
