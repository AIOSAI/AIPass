# =================== AIPass ====================
# Name: score.py
# Description: the v5 shadow score - one checker pack over the fleet, scoring and never gating
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-10-17
# =============================================

"""
THE SHADOW SCORE: a full standards audit that decides nothing.

`pytest_quality` declares itself shadow, so its number is published beside the
word SHADOW, never a threshold. It runs `audit_branch_incremental`, not `drone`:
a second path is a second answer. The artifact name carries the pack so it never
replaces `.seedgo/last_audit.json`."""

import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.audit.artifact import write_audit_artifact
from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch_incremental
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

MODULE_NAME = "shadow_cycle.score"

HANDLERS_DIR = module_file(__file__).parents[1]

WEAKEST_SHOWN = 3

#: The audit display's own "healthy" line, so the series and the verb flag the same branches.
ATTENTION_BELOW = 90


def pack_path(pack_name: str) -> Path:
    """Where a scoring pack lives on disk.

    Raises rather than defaulting: a renamed pack must never publish under the wrong heading."""
    packs = discovery.discover_packs(HANDLERS_DIR)
    if pack_name not in packs:
        available = ", ".join(sorted(packs)) or "none"
        raise ValueError(f"'{pack_name}' is not an installed scoring pack - available: {available}")
    return packs[pack_name]


def run(
    pack_name: str,
    branches: Sequence[Dict[str, str]],
    artifact_path: Path,
    on_branch: Optional[Callable[[Dict], None]] = None,
) -> dict:
    """Score every branch against one pack, publish the full result set, summarise it.

    ``on_branch`` gets each result as it lands: a handler never prints, it hands the line back."""
    resolved = pack_path(pack_name)
    results: List[Dict] = []

    for branch in branches:
        started = time.monotonic()
        result = audit_branch_incremental(branch, load_bypass_rules(branch["path"]), pack_path=resolved)
        result["elapsed"] = time.monotonic() - started
        results.append(result)
        if on_branch is not None:
            on_branch(result)

    written = _publish(results, pack_name, artifact_path)
    return _summary(pack_name, results, written)


def _publish(results: Sequence[Dict], pack_name: str, artifact_path: Path) -> Path:
    """Write the complete violation set and return where it landed."""
    written = write_audit_artifact(list(results), output_path=artifact_path, pack=pack_name)
    json_handler.log_operation(
        "shadow_cycle_score_published",
        {"pack": pack_name, "branches": len(results), "artifact": str(written)},
        module_name=MODULE_NAME,
    )
    logger.info(f"[SHADOW_CYCLE] {pack_name} scored {len(results)} branches into {written}")
    return written


def _summary(pack_name: str, results: Sequence[Dict], artifact: Path) -> dict:
    """The counts a reader checks this week's cycle against last week's."""
    averages = _standard_averages(results)
    weakest = sorted(averages.items(), key=lambda pair: (pair[1], pair[0]))[:WEAKEST_SHOWN]

    return {
        "pack": pack_name,
        "mode": "shadow",
        "gating": False,
        "branches": len(results),
        "standards": len(averages),
        "average": _mean(result["average"] for result in results),
        "standard_averages": dict(sorted(averages.items())),
        "weakest_standards": [[name, score] for name, score in weakest],
        "branches_below_attention": _below_attention(results),
        "attention_below": ATTENTION_BELOW,
        "artifact": str(artifact),
    }


def _standard_averages(results: Sequence[Dict]) -> Dict[str, int]:
    """Fleet average per standard, over every branch that carried a score."""
    per_standard: Dict[str, List[int]] = defaultdict(list)
    for result in results:
        for standard, score in result.get("scores", {}).items():
            per_standard[standard].append(score)
    return {standard: _mean(scores) for standard, scores in per_standard.items()}


def _below_attention(results: Sequence[Dict]) -> List[list]:
    """Branch and score for every branch under the attention line, worst first.

    `result["branch"]` is the registry ENTRY, not a name."""
    low = [[result["branch"]["name"], result["average"]] for result in results if result["average"] < ATTENTION_BELOW]
    return sorted(low, key=lambda pair: pair[1])


def _mean(values) -> int:
    """The integer mean of a run of numbers, and 0 for an empty one."""
    collected = list(values)
    return int(sum(collected) / len(collected)) if collected else 0
