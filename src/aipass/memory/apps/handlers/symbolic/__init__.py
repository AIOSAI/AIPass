# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Symbolic Memory Handler Package (PARKED)
# Date: 2026-08-14
# Version: 1.0.0
# Category: memory/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-14): PARKED by the owner's ruling — implementation moved to
#     tests/parked/symbolic_20260814/, this package now refuses on import
#   - v0.1.0 (2026-02-04): Initial version - Fragmented Memory Phase 1
# =============================================

"""
Symbolic Memory Handler Package — PARKED 2026-08-14.

Kept on purpose: a missing package raises a bare ModuleNotFoundError; this one
says why it is parked and what to use. Revive: tests/parked/symbolic_20260814/README.md
"""

_PARKED_MESSAGE = (
    "The symbolic fragments tier is PARKED (the owner's ruling, 2026-08-14) and cannot be imported.\n"
    "  Why:    unused tier; the Agent Memory Atlas review (2026-08-14) flagged its AUDN\n"
    "          deduplicator for acting on an LLM Delete verdict with no record of what\n"
    "          was removed or why. Parked, not removed.\n"
    "  Active: Compass — @devpulse's curated-truth store (SQLite/FTS5).\n"
    "          drone @devpulse compass\n"
    "  Code:   memory/tests/parked/symbolic_20260814/ (see its README to revive)"
)


class SymbolicTierParked(RuntimeError):
    """Raised when parked symbolic code is reached. Never silently no-ops."""


raise SymbolicTierParked(_PARKED_MESSAGE)
