# =================== AIPass ====================
# Name: __init__.py
# Description: context standards pack — the startup cost of a citizen
# Version: 1.1.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""The context pack. One rule: what a greeting costs, in characters.

ITS OWN PACK SO IT RUNS ALONE. `drone @seedgo audit context` measures six files
per branch and nothing else — it never opens `apps/`, so asking it a question
should not run the 47 rules of `aipass_standards` over every branch's source.
The audit verb strips the `_standards` suffix, which is why the directory is
`context_standards` and the command is `audit context`.

NOT `startup_standards`, NOT `budget_standards`. The pack is named for the LAYER
it measures, so the caps rule can be joined by the rest of the layer contract —
docs index coverage, the kernel/navmap budget — without any of them living under
a name that only describes the first rule written.

ADVISORY ROW, RATCHETED FILES. The audit row is advisory by the room's ruling:
a checker that moved in one commit put 17 of 18 branches red on 2026-09-13, so
the score prints and gates nothing. What gates is `startup_ratchet.py` (Phase 5,
landed 2026-09-15): the `seedgo-audit` CI job holds README.md and the branch
prompt at the caps their owners publish, reading this pack's pack.json for one
and @hooks for the other. Two files, not six - `.trinity/` and the dashboard are
gitignored and a clean checkout cannot see them, so a gate on them would measure
nothing and pass by accident forever.

Design: DPLAN-0347 / FPLAN-0593, boardroom thread 16 (converged 2026-09-15).
"""

__version__ = "0.2.0"

#: The gate, re-exported so the pack has a front door for it. Nothing under
#: seedgo's own `apps/` calls it — its caller is `.github/scripts/seedgo_audit.py`,
#: outside the tree the dead-code rule can see — and a published module that no
#: in-tree file names is indistinguishable from an abandoned one. Named here, the
#: pack says which of its arms are part of it: the checker, found by the audit's
#: `*_check.py` glob, and the ratchet, imported by the CI runner.
from aipass.seedgo.apps.handlers.context_standards import startup_ratchet  # noqa: F401  (re-exported)
