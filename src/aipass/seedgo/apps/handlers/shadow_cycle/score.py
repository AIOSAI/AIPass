# =================== AIPass ====================
# Name: score.py
# Description: the v5 shadow score - one checker pack over the fleet, scoring and never gating
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-09-02
# =============================================

"""
THE SHADOW SCORE: a full standards audit that decides nothing.

`pytest_quality` declares `"status": "shadow"` in its own pack.json - it judges
what a test PROVES, and until its numbers have been diffed against the
calibrated v4 triage nobody may act on them. So this pass runs the identical
scoring engine the `audit` verb runs, over the identical pack, and publishes the
number beside the word SHADOW rather than beside a threshold.

WHY IT REUSES `audit_branch_incremental` RATHER THAN SHELLING `drone`. A second
invocation path is a second answer: the moment the weekly number and the
`drone @seedgo audit pytest_quality` number can disagree, the series is
measuring the wrapper instead of the fleet. One engine, one answer.

ITS OWN ARTIFACT FILE, ALWAYS. A fleet audit's default destination is
`.seedgo/last_audit.json`, and a weekly cycle writing there would silently
replace the aipass-pack document a reader believes is the fleet's compliance
record - one file, two packs, no way to tell which run produced it. The cycle's
artifact carries the pack in its NAME, for the reason `last_audit_{branch}.json`
carries the branch in its own.

KNOWN COST, STATED RATHER THAN HIDDEN. The incremental audit cache is keyed on
branch name alone while its validity STAMP includes the pack path, so a shadow
run evicts the aipass-pack entry for every branch and the next `audit aipass` is
a cold full scan. The output is correct either way - only slower. The fix
belongs to the cache's key, not to this pass, and it is not taken here.
"""

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

#: This branch's `handlers/` directory - where every checker pack lives.
HANDLERS_DIR = module_file(__file__).parents[1]

#: How many of the weakest standards the one-screen summary names.
WEAKEST_SHOWN = 3

#: A branch scoring under this is named individually rather than averaged away.
#: Ninety is the audit display's own "healthy" line, reused so the weekly series
#: and the interactive verb draw attention to the same branches.
ATTENTION_BELOW = 90


def pack_path(pack_name: str) -> Path:
    """Where a scoring pack lives on disk.

    Raises rather than defaulting to another pack: a cycle that quietly scored
    `aipass` because `pytest_quality` was renamed would publish a number under
    the wrong heading, which is the one failure a weekly series cannot survive.

    Args:
        pack_name: The pack's short name, e.g. ``pytest_quality``.

    Returns:
        The pack directory.
    """
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

    Args:
        pack_name: The pack to score against.
        branches: Registry entries, as `discovery.discover_branches` returns them.
        artifact_path: Where the complete, untruncated result set is written.
        on_branch: Called with each branch's result the moment it lands, so a
            caller that owns a console can report a five-minute pass while it
            runs. A handler never prints; it hands the line back.

    Returns:
        The summary block the cycle document carries.
    """
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

    `result["branch"]` is the registry ENTRY, not a name - reading it as a
    string is the shape that puts a whole dict in a summary line.
    """
    low = [[result["branch"]["name"], result["average"]] for result in results if result["average"] < ATTENTION_BELOW]
    return sorted(low, key=lambda pair: pair[1])


def _mean(values) -> int:
    """The integer mean of a run of numbers, and 0 for an empty one."""
    collected = list(values)
    return int(sum(collected) / len(collected)) if collected else 0
