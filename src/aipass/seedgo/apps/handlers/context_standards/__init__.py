# =================== AIPass ====================
# Name: __init__.py
# Description: context standards pack — the startup cost of a citizen
# Version: 1.0.0
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

ADVISORY WHILE IT IS YOUNG, by the room's ruling: a checker that moved in one
commit put 17 of 18 branches red on 2026-09-13. Phase 5 adds a per-file ratchet
in CI, which reads the README cap out of this pack's pack.json.

Design: DPLAN-0347 / FPLAN-0593, boardroom thread 16 (converged 2026-09-15).
"""

__version__ = "0.1.0"
