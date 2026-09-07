# =================== AIPass ====================
# Name: ranking.py
# Description: the review-priority score, with every component left visible
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
THE COMPOSITE SCORE, and the reason it is called `review_priority` and not
`value`.

Shi et al. (ISSTA 2018) reduced test suites on 32 real projects and replayed
1,478 real failed CI builds against the result. Suites built to kill exactly
the same mutants still missed 13.1% to 36.2% of real failures; every predictor
tested had R-squared at or below 0.26. So a number computed from static shape
cannot authorise removing a test, and one named `value` would be read as
though it could.

WHAT THE NUMBER MEANS: higher = look at this sooner. Nothing else. It orders a
reading queue for a human. It is not a verdict, it does not compose into one,
and `NEVER_A_DELETE_VERDICT` is asserted in the artifact and pinned by a test
so a later contributor cannot quietly add a band that reads like one.

EVERY COMPONENT SHIPS IN THE ROW with its raw input, its normalised value and
its weight. A reader who disagrees with the weighting - and the weighting is a
judgement, not a measurement - can recompute the whole column from the row
without re-running anything.

THE WEIGHTS AND WHY THEY ARE WHAT THEY ARE:

  oracle      0.50  the only component with published support. Zhang & Mesbah
                    (ESEC/FSE 2015): assertion presence correlates with fault
                    detection where coverage does not.
  twins       0.20  WEAK, and labelled weak wherever it is published. Identical
                    statement shapes inside one class find generated batches -
                    and also find a legitimate parametrised family. 39-75% of
                    real tests execute a strict line-subset of another test and
                    are STILL not deletable; this column carries that caveat.
  crowding    0.15  WEAK. A test in a 200-test file is more likely one of a
                    batch. It is also more likely to be a thorough suite.
  authorship  0.10  small on purpose: over 99% of this fleet is agent-authored,
                    so the column barely discriminates here. It is kept because
                    it will discriminate on a project that is not this one.
  recency     0.05  smallest, because age is not quality. It is here because
                    the highest-leverage governance action is stopping the
                    inflow, and the inflow is the young end of the distribution.
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional

from aipass.seedgo.apps.handlers.test_inventory import history, shape

#: What each component contributes to the composite. Sums to 1.0, pinned.
WEIGHTS: dict = {
    "oracle": 0.50,
    "twins": 0.20,
    "crowding": 0.15,
    "authorship": 0.10,
    "recency": 0.05,
}

#: Components whose evidence is a proxy with no published validation. Named in
#: the artifact beside the score, not buried in a design document.
WEAK_COMPONENTS: tuple = ("twins", "crowding")

#: The assertion shape's contribution. MOCK_ONLY outranks a NONE that calls a
#: check-shaped helper, because W4 (arXiv:2606.18168) is a named species and a
#: delegated oracle is most often a real oracle one call away.
ORACLE_SCORES: dict = {
    (shape.SHAPE_NONE, False): 1.00,
    (shape.SHAPE_MOCK_ONLY, False): 0.70,
    (shape.SHAPE_MOCK_ONLY, True): 0.70,
    (shape.SHAPE_NONE, True): 0.50,
    (shape.SHAPE_REAL, False): 0.00,
    (shape.SHAPE_REAL, True): 0.00,
}

#: File size at which crowding saturates. Above this the column stops
#: discriminating rather than growing without bound.
CROWDING_CEILING = 150

#: Age at which recency stops contributing. A year is not a measurement, it is
#: a declared horizon, and it is published as one.
RECENCY_HORIZON_DAYS = 365.0

#: Author buckets that score full authorship weight, and why each does.
AUTHORSHIP_SCORES: dict = {
    "AGENT_AIOSAI": 1.0,
    "AGENT_AIPASS": 1.0,
    "BOT": 1.0,
    history.BUCKET_UNTRACKED: 1.0,
    history.BUCKET_OTHER: 0.0,
}

#: Words this report may never emit about a test. Law S7b's family, honoured
#: outside the lane because the reason for it is the evidence, not the law.
DELETE_FAMILY: frozenset = frozenset({"useless", "delete", "remove", "worthless", "dead", "cull", "prune"})

#: Stamped on the artifact and on every row's score block.
NEVER_A_DELETE_VERDICT = (
    "review_priority orders a reading queue; it is not a value score and it authorises nothing. "
    "ISSTA 2018 replayed 1,478 real failed builds against reduced suites: reductions that killed the "
    "identical mutants still missed 13.1-36.2% of real failures. No static signal here is better than those."
)


@dataclass
class Score:
    """One test's review priority, with the arithmetic left in the open."""

    review_priority: float
    components: Dict[str, dict]

    def as_dict(self) -> dict:
        """The score block as it is published."""
        return {
            "review_priority": self.review_priority,
            "components": self.components,
            "weak_components": list(WEAK_COMPONENTS),
            "means": NEVER_A_DELETE_VERDICT,
        }


def score(
    unit_shape: shape.Shape,
    unit_history: history.FunctionHistory,
    twins: int,
    file_tests: int,
) -> Score:
    """The composite review priority for one test function."""
    components = {
        "oracle": _component(_oracle_value(unit_shape), unit_shape.shape, "oracle"),
        "twins": _component(_twins_value(twins), twins, "twins"),
        "crowding": _component(_crowding_value(file_tests), file_tests, "crowding"),
        "authorship": _component(_authorship_value(unit_history), unit_history.author_bucket, "authorship"),
        "recency": _component(_recency_value(unit_history.age_days), unit_history.age_days, "recency"),
    }
    total = sum(part["weighted"] for part in components.values())
    return Score(review_priority=round(total, 4), components=components)


def _component(value: float, raw, name: str) -> dict:
    """One component's raw input, normalised value, weight and contribution."""
    weight = WEIGHTS[name]
    return {
        "raw": raw,
        "value": round(value, 4),
        "weight": weight,
        "weighted": round(value * weight, 4),
        "weak": name in WEAK_COMPONENTS,
    }


def _oracle_value(unit_shape: shape.Shape) -> float:
    """How much the assertion shape argues for a read."""
    return ORACLE_SCORES[(unit_shape.shape, unit_shape.delegated_oracle)]


def _twins_value(twins: int) -> float:
    """1 - 1/n over the identically-shaped siblings in the same class.

    A lone test scores zero and a family of ten scores 0.9, which is the shape
    wanted: the more interchangeable a test looks, the sooner somebody should
    read the family - never the sooner it should go.
    """
    return 0.0 if twins < 2 else 1.0 - (1.0 / twins)


def _crowding_value(file_tests: int) -> float:
    """How crowded the file is, log-scaled and saturating at the ceiling."""
    if file_tests < 2:
        return 0.0
    return min(1.0, math.log10(file_tests) / math.log10(CROWDING_CEILING))


def _authorship_value(unit_history: history.FunctionHistory) -> float:
    """Whether the author bucket argues for a read.

    UNTRACKED scores full weight rather than zero: a test with no recorded
    history has no recorded reason to exist, and that is the single strongest
    argument for a human reading it that this module can make.
    """
    return AUTHORSHIP_SCORES.get(unit_history.author_bucket, 0.0)


def _recency_value(age_days: Optional[float]) -> float:
    """Younger tests first, and an unknown age contributes nothing.

    An unknown age is not a young age. Scoring it as one would put every
    untracked file at the top of the queue for the wrong reason, on top of the
    authorship weight it already earns for the right one.
    """
    if age_days is None:
        return 0.0
    return max(0.0, 1.0 - (age_days / RECENCY_HORIZON_DAYS))


def delete_language_in(text: str) -> list:
    """Every delete-family word a published string contains.

    Used to refuse the report rather than to warn about it. The whole argument
    for this tool is that a static signal cannot authorise a deletion, so a
    build that lets the vocabulary drift back in has lost the argument.
    """
    lowered = text.lower()
    return sorted(word for word in DELETE_FAMILY if word in lowered)
