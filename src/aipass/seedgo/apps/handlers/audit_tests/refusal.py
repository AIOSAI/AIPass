# =================== AIPass ====================
# Name: refusal.py
# Description: audit-tests refusal vocabulary and exit mapping
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The refusal vocabulary — the lane's most load-bearing distinction.

A REFUSAL IS NEVER A SCORE. The whole reason this lane exists is that a zero
from a gate that could not fire and a zero from a clean suite look identical
from the outside, and only an explicit refusal tells them apart.

Exit codes (design section 1.4). The code is a shell CONVENIENCE, never the
verdict: `seedgo.py` returns 0 on any truthy route, so a caller that reads the
exit code alone cannot see a refusal at all. The artifact's `status` field and
the `REFUSED:` stdout line are the load-bearing signals (design section 6.3b).

    0  published; every scored group passed
    1  published; a scored group failed
    2  refused - the harness could not prove it was entitled to publish
    3  refused - the target holds no runnable test units
    4  refused - no adapter claims this target
    5  refused - lane pointed at a static pack, or audit pointed at execution
    6  refused - the wall-clock budget expired (Law T-BUDGET)

Multi-target form returns the WORST per-target code, ordered

    0 < 1 < 3 < 4 < 5 < 6 < 2

with 2 ranked worst deliberately: an unproven harness is a more serious
result than a suite that failed a gate honestly.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# EXIT CODES
# =============================================================================

EXIT_PASSED = 0
EXIT_SCORED_FAILED = 1
EXIT_UNPROVEN = 2
EXIT_NO_UNITS = 3
EXIT_NO_ADAPTER = 4
EXIT_WRONG_PACK_KIND = 5
EXIT_BUDGET_EXHAUSTED = 6

#: Every code that means "refused". Codes 0 and 1 are publications.
REFUSAL_CODES: frozenset = frozenset(
    {
        EXIT_UNPROVEN,
        EXIT_NO_UNITS,
        EXIT_NO_ADAPTER,
        EXIT_WRONG_PACK_KIND,
        EXIT_BUDGET_EXHAUSTED,
    }
)

#: Worst-first severity for the multi-target fleet form. Index = severity rank;
#: a higher index is worse. `EXIT_UNPROVEN` is last because it is the worst.
SEVERITY_ORDER: tuple = (
    EXIT_PASSED,
    EXIT_SCORED_FAILED,
    EXIT_NO_UNITS,
    EXIT_NO_ADAPTER,
    EXIT_WRONG_PACK_KIND,
    EXIT_BUDGET_EXHAUSTED,
    EXIT_UNPROVEN,
)

#: The law each refusal cites, so a refusal always names the rule it refuses
#: under rather than only saying "no".
REFUSAL_LAW = {
    EXIT_UNPROVEN: "T10",
    EXIT_NO_UNITS: "S1",
    EXIT_NO_ADAPTER: "S1",
    EXIT_WRONG_PACK_KIND: "M1",
    EXIT_BUDGET_EXHAUSTED: "T-BUDGET",
}


# =============================================================================
# THE REFUSAL RECORD
# =============================================================================


@dataclass
class Refusal:
    """A refusal, carrying the law it refuses under and why.

    `detail` holds the evidence a reader needs to act — the canary's own
    output, the paths that had no test units, the elapsed seconds against the
    budget. A refusal with an empty detail list is a refusal nobody can fix.
    """

    code: int
    reason: str
    detail: List[str] = field(default_factory=list)

    @property
    def law(self) -> str:
        """The law this refusal cites."""
        return REFUSAL_LAW.get(self.code, "T10")

    def to_document(self) -> dict:
        """The artifact's `refusal` block."""
        return {
            "law": self.law,
            "code": self.code,
            "reason": self.reason,
            "detail": list(self.detail),
        }

    def stdout_line(self) -> str:
        """The load-bearing stdout signal (design section 6.3b).

        Printed on every refusal because the exit code cannot survive
        `seedgo.py`'s return path.
        """
        return f"REFUSED: [{self.law}] {self.reason}"

    def record(self) -> None:
        """Log this refusal to the operations log.

        Called at the point a refusal is acted on rather than at construction,
        so a refusal built and discarded during assembly never pollutes the
        record with something that did not happen.
        """
        json_handler.log_operation(
            "lane_refused",
            {"law": self.law, "code": self.code, "reason": self.reason, "detail": self.detail},
        )


# =============================================================================
# HELPERS
# =============================================================================


def is_refusal(code: int) -> bool:
    """True if this exit code means the lane refused to publish."""
    return code in REFUSAL_CODES


def worst_code(codes: List[int]) -> int:
    """The worst code across a fleet run, per SEVERITY_ORDER.

    An unknown code is treated as the worst possible rather than ignored —
    silently downgrading a code we do not recognise is exactly how a refusal
    would come to look like a pass.
    """
    if not codes:
        return EXIT_PASSED

    def rank(code: int) -> int:
        """Severity rank; anything unrecognised sorts worse than every known code."""
        if code in SEVERITY_ORDER:
            return SEVERITY_ORDER.index(code)
        return len(SEVERITY_ORDER)

    return max(codes, key=rank)


def refusal_for_budget(elapsed: float, budget: int, group: str) -> Refusal:
    """Build the T-BUDGET refusal (design section 4.7).

    A partial measurement that reports a number is OBSERVER-FORGERY by
    omission, so the adapter must never return one — this is what it returns
    instead.
    """
    return Refusal(
        code=EXIT_BUDGET_EXHAUSTED,
        reason=f"budget_exhausted: group '{group}' exceeded its wall-clock budget",
        detail=[
            f"group: {group}",
            f"budget_seconds: {budget}",
            f"elapsed_seconds: {elapsed:.1f}",
            "no partial measurement is published - a partial suite that reports a number is forgery by omission",
        ],
    )


def refusal_for_canary(detail: Optional[List[str]] = None) -> Refusal:
    """Build the canary refusal (Law T10 / M2).

    A run that cannot catch its own planted write has proved nothing, and must
    not publish. This is the refusal that makes a score of 100 mean anything
    at all.
    """
    return Refusal(
        code=EXIT_UNPROVEN,
        reason="the hygiene gate did not catch its own planted canary write",
        detail=list(detail or []) or ["the gate was installed but did not fire; a score from it would be unproven"],
    )
