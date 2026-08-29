# =================== AIPass ====================
# Name: logsetup.py - the tool's one logger
# Description: a single stdlib logger, so no module swallows an exception silently
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""One named logger for the whole prototype.

Deliberate, declared deviation from seedgo's ``log_visibility`` standard, which
requires ``prax``'s ``system_logger``.  This tool is stdlib-only by mandate: it
must audit directories that are not aipass packages at all, and its pytest
plugin is injected into a *copy* of somebody else's branch, where importing the
real repo's ``prax`` would be the instrument reaching back into the tree it is
measuring (Law M10).  Concentrating the ``getLogger`` call here means the
deviation exists in exactly two files -- this one and the standalone plugin --
rather than scattered across every module.

Nothing configures a handler.  At default level these records cost nothing and
stay invisible; ``logging.basicConfig(level=logging.DEBUG)`` in a caller turns
them all on at once.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("audit_tests")

__all__ = ["logger"]
