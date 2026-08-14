# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Symbolic Memory Handler Package (PARKED)
# Date: 2026-08-14
# Version: 1.0.0
# Category: memory/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-14): PARKED by Patrick's ruling — implementation moved to
#     .archive/parked_symbolic_20260814/, this package now refuses on import
#   - v0.1.0 (2026-02-04): Initial version - Fragmented Memory Phase 1
# =============================================

"""
Symbolic Memory Handler Package — PARKED 2026-08-14.

WHY THIS IS PARKED
    The Agent Memory Atlas published a code-grounded review of AIPass memory at
    revision 0d27e5ef (https://neoneye.github.io/agent-memory-atlas/systems/aipass/).
    Its top criticism: the AUDN deduplicator asks an LLM for a verdict and acts on
    ``Delete`` without recording what was removed or why — an unauditable deletion
    in a memory system. The tier was never wired into any live lane (no hook entry,
    no caller in rollover/extractor/auto_process/search/verify), so nothing depends
    on it. Patrick's ruling, 2026-08-14: park it, revivable, and point at the piece
    that is actually active.

WHERE THE ACTIVE PIECE IS
    Compass — @devpulse's curated-truth store. Owned by @devpulse, lives in
    src/aipass/devpulse, SQLite + FTS5, reached with ``drone @devpulse compass``.
    It already carries the supersession discipline this tier lacked: a correcting
    entry archives and links the entry it replaces, so a change of mind leaves a
    record instead of a hole.

    Note the split: Compass RECALL is gated by @memory's governance engine
    (apps/modules/governance.py -> handlers/governance/engine.py), which is LIVE on
    the UserPromptSubmit lane via @hooks' compass_recall. Governance is not parked
    and is not part of this tier.

HOW TO REVIVE (a park, not a demolition)
    1. Move the seven files back:
       .archive/parked_symbolic_20260814/handlers/*.py -> apps/handlers/symbolic/
       (the original __init__.py is in there too and replaces this file)
    2. Move .archive/parked_symbolic_20260814/modules/symbolic.py back over
       apps/modules/symbolic.py
    3. Uncomment ``from . import symbolic`` in apps/handlers/__init__.py
    4. Drop the module-level skips at the top of tests/test_symbolic*.py
    Full detail: .archive/parked_symbolic_20260814/README.md

This file stays behind on purpose. A missing package raises ModuleNotFoundError,
which says nothing about why; this one says who parked it, when, and what to use.
"""

_PARKED_MESSAGE = (
    "The symbolic fragments tier is PARKED (Patrick's ruling, 2026-08-14) and cannot be imported.\n"
    "  Why:    unused tier; the Agent Memory Atlas review (2026-08-14) flagged its AUDN\n"
    "          deduplicator for acting on an LLM Delete verdict with no record of what\n"
    "          was removed or why. Parked, not removed.\n"
    "  Active: Compass — @devpulse's curated-truth store (SQLite/FTS5).\n"
    "          drone @devpulse compass\n"
    "  Code:   memory/.archive/parked_symbolic_20260814/ (see its README to revive)"
)


class SymbolicTierParked(RuntimeError):
    """Raised when parked symbolic code is reached. Never silently no-ops."""


raise SymbolicTierParked(_PARKED_MESSAGE)
