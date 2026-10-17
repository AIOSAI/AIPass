# =================== AIPass ====================
# Name: ranking.py
# Description: the review-priority score, with every component left visible
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""
THE COMPOSITE SCORE, and the reason it is called `review_priority` and not
`value`.

Higher = read sooner, nothing else: a static score cannot authorise removing a
test. Every component ships in the row (raw input, value, weight) so a reader
can recompute it; `twins` and `crowding` are weak proxies."""

import math
from dataclasses import dataclass
from typing import Dict, Optional

from aipass.seedgo.apps.handlers.test_inventory import history, shape

#: Sums to 1.0, pinned by a test.
WEIGHTS: dict = {
    "oracle": 0.50,
    "twins": 0.20,
    "crowding": 0.15,
    "authorship": 0.10,
    "recency": 0.05,
}

WEAK_COMPONENTS: tuple = ("twins", "crowding")

#: MOCK_ONLY outranks a NONE with a check-shaped helper: a delegated oracle is usually real.
ORACLE_SCORES: dict = {
    (shape.SHAPE_NONE, False): 1.00,
    (shape.SHAPE_MOCK_ONLY, False): 0.70,
    (shape.SHAPE_MOCK_ONLY, True): 0.70,
    (shape.SHAPE_NONE, True): 0.50,
    (shape.SHAPE_REAL, False): 0.00,
    (shape.SHAPE_REAL, True): 0.00,
}

CROWDING_CEILING = 150

RECENCY_HORIZON_DAYS = 365.0

AUTHORSHIP_SCORES: dict = {
    "AGENT_AIOSAI": 1.0,
    "AGENT_AIPASS": 1.0,
    "BOT": 1.0,
    history.BUCKET_UNTRACKED: 1.0,
    history.BUCKET_OTHER: 0.0,
}

DELETE_FAMILY: frozenset = frozenset({"useless", "delete", "remove", "worthless", "dead", "cull", "prune"})

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
    """1 - 1/n over the identically-shaped siblings in the same class."""
    return 0.0 if twins < 2 else 1.0 - (1.0 / twins)


def _crowding_value(file_tests: int) -> float:
    """How crowded the file is, log-scaled and saturating at the ceiling."""
    if file_tests < 2:
        return 0.0
    return min(1.0, math.log10(file_tests) / math.log10(CROWDING_CEILING))


def _authorship_value(unit_history: history.FunctionHistory) -> float:
    """Whether the author bucket argues for a read.

    UNTRACKED scores full weight: a test with no history has no recorded reason to exist."""
    return AUTHORSHIP_SCORES.get(unit_history.author_bucket, 0.0)


def _recency_value(age_days: Optional[float]) -> float:
    """Younger tests first, and an unknown age contributes nothing.

    An unknown age is not a young age."""
    if age_days is None:
        return 0.0
    return max(0.0, 1.0 - (age_days / RECENCY_HORIZON_DAYS))


def delete_language_in(text: str) -> list:
    """Every delete-family word a published string contains.

    Used to refuse the report, not to warn."""
    lowered = text.lower()
    return sorted(word for word in DELETE_FAMILY if word in lowered)
