# =================== AIPass ====================
# Name: artifact.py
# Description: audit-tests artifact assembly, provenance and write
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
Artifact assembly. The artifact IS the verdict; the exit code is a convenience.

Filename namespace is deliberately disjoint from the audit's:
`audit_tests_<target>.json`, never `last_audit_*`. Different schema, different
keys — a consumer that opened this expecting an audit document would read
`groups` where it wanted `scores`. The disjoint name defeats the existing
`.seedgo/last_audit_*.json` ignore glob, so `.seedgo/audit_tests_*.json` is
added to the ignore file in the same change that first writes one.

Written into SEEDGO's own `.seedgo/`, never into the target's. Writing into
another branch's `.seedgo/` would violate this branch's own `gateway_boundary`
standard, which names `.seedgo` as seedgo-owned storage.

Every artifact carries `group_baseline`. On a first run for a (target, adapter)
pair there is no previous artifact, so the S3 no-vanishing diff CANNOT run —
and a check that silently did not run is exactly what the harness self-report
exists to prevent. So it says so, in the document, rather than looking like a
check that ran and passed.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit_tests import laws, refusal, spine, target as target_module
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

ARTIFACT_VERSION = "audit-tests/1"
LANE_VERSION = "1.0.0"

#: Where artifacts live. Seedgo's own state directory, never the target's.
SEEDGO_ROOT = module_file(__file__).parents[3]
ARTIFACT_DIR = SEEDGO_ROOT / ".seedgo"

#: Baseline marker for a pair the lane has never measured before.
FIRST_RUN_BASELINE = "first run for this pair"


# =============================================================================
# PATHS
# =============================================================================


def artifact_path(target: target_module.Target) -> Path:
    """Absolute path this target's artifact is written to."""
    return ARTIFACT_DIR / f"{target.artifact_name()}.json"


def load_previous(target: target_module.Target) -> Optional[dict]:
    """The previous artifact for this target, or None if there is not one.

    Fail-open on a damaged file: an unreadable previous artifact means the S3
    diff cannot run, which the caller records as a missing baseline rather
    than treating as "nothing vanished".
    """
    path = artifact_path(target)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"[AUDIT-TESTS] previous artifact unreadable, S3 diff cannot run: {path} ({exc})")
        json_handler.log_operation("previous_artifact_unreadable", {"path": str(path), "error": str(exc)})
        return None


def previous_group_list(previous: Optional[dict]) -> Optional[List[str]]:
    """The group list of the previous artifact, or None if there was none."""
    if not previous:
        return None
    group_list = previous.get("group_list")
    return list(group_list) if isinstance(group_list, list) else None


# =============================================================================
# ASSEMBLY
# =============================================================================


def _provenance(run_id: str, started: datetime, elapsed: float) -> dict:
    """The provenance block. `host_note` is deliberately non-identifying."""
    return {
        "run_id": run_id,
        "started": started.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "host_note": f"{os.name} interpreter",
        "lane_version": LANE_VERSION,
    }


def assemble(
    target: target_module.Target,
    groups: Dict[str, dict],
    group_list: List[str],
    *,
    ecosystem: str,
    adapter: str,
    adapter_api: int,
    run_id: Optional[str] = None,
    started: Optional[datetime] = None,
    elapsed: float = 0.0,
    cache: Optional[dict] = None,
    retired_groups: Optional[List[dict]] = None,
    previous: Optional[dict] = None,
    executed_order: Optional[List[str]] = None,
    refused: Optional[refusal.Refusal] = None,
) -> dict:
    """Build the artifact document. Does not validate and does not write.

    `executed_order` is a rev-4 requirement (design section 9.2): a serial run
    executes one deterministic order and an xdist run executes another, so a
    v1 baseline is ORDER-SPECIFIC. Recorded from run one because it costs
    nothing now and CANNOT be reconstructed later — without it the v1-to-v2
    comparison is unfalsifiable.
    """
    started = started or datetime.now(timezone.utc)
    prior_list = previous_group_list(previous)

    # The S3 diff can only run against a previous artifact. When there is none,
    # the baseline says so out loud rather than leaving a reader to assume the
    # check ran and passed.
    if prior_list is None or previous is None:
        baseline = FIRST_RUN_BASELINE
    else:
        baseline = previous.get("provenance", {}).get("run_id", "unknown")

    document = {
        "artifact_version": ARTIFACT_VERSION,
        "status": "refused" if refused else "published",
        "refusal": refused.to_document() if refused else None,
        "cache": cache or {"served_from_cache": False, "stamp": "", "not_fingerprinted": []},
        "tool": {
            "name": "audit-tests",
            "version": LANE_VERSION,
            "adapter": adapter,
            "adapter_api": adapter_api,
            "ecosystem": ecosystem,
            "campaign": "DPLAN-0320 / FPLAN-0459",
        },
        "target": target.to_document(),
        "group_list": list(group_list),
        "groups": groups,
        "retired_groups": list(retired_groups or []),
        "group_baseline": baseline,
        "executed_order": list(executed_order or []),
        "scored_groups": list(spine.SCORED_GROUPS),
        "laws": dict(laws.LAW_STATEMENTS),
        "provenance": _provenance(run_id or uuid.uuid4().hex[:12], started, elapsed),
    }
    return document


def refused_artifact(
    target: target_module.Target,
    refused: refusal.Refusal,
    *,
    ecosystem: str = "unknown",
    adapter: str = "none",
    adapter_api: int = 0,
    group_list: Optional[List[str]] = None,
    previous: Optional[dict] = None,
    retired_groups: Optional[List[dict]] = None,
) -> dict:
    """A full artifact for a refused run - every group `not_applicable`.

    A refusal still publishes a complete document. An empty file, or no file
    at all, is indistinguishable from a run that never happened, and the whole
    point of the refusal vocabulary is that those two are different.

    EVERY GROUP THE PREVIOUS ARTIFACT PUBLISHED IS CARRIED FORWARD. A refusal
    reached before an adapter was selected knows only the core spine, so the
    adapter's groups would VANISH from the list - and S3 would then refuse the
    refusal itself, turning a diagnosable "no adapter claims this target" into
    an artifact that never reached disk. A group that could not be measured
    stays in the list saying so; that is the whole difference between S1 and a
    hole.
    """
    names = list(group_list or spine.CORE_SPINE)
    for previous_name in previous_group_list(previous) or []:
        if previous_name not in names:
            names.append(previous_name)
    groups = {}
    for name in names:
        # The base document differs by origin: a spine group brings its own
        # tier and rationale, an adapter group has neither here because the
        # adapter never ran. Neither base sets a status - the single override
        # below is the only place status and reason are decided, so removing
        # it produces an S1 violation rather than a silent no-op. An earlier
        # shape set the status in both branches AND overrode it, and the
        # mutation pass correctly reported the override as unkillable: a line
        # no test can distinguish is the code equivalent of a vacuous pin.
        if name in spine.CORE_SPINE:
            document = spine.spine_document(name)
        else:
            document = {"tier": "static", "score": None}
        document["status"] = "not_applicable"
        document["reason"] = f"run refused before measurement: {refused.reason}"
        groups[name] = document

    return assemble(
        target,
        groups,
        names,
        ecosystem=ecosystem,
        adapter=adapter,
        adapter_api=adapter_api,
        previous=previous,
        retired_groups=retired_groups,
        refused=refused,
    )


# =============================================================================
# PUBLICATION
# =============================================================================


def publish(document: dict, target: target_module.Target, previous: Optional[dict] = None) -> Path:
    """Validate against every law, then write. Raises LawViolation if unlawful.

    Validation happens BEFORE the write, so an unlawful artifact never reaches
    disk where something could read it. The write is atomic — a torn artifact
    read mid-write would be a confidently wrong number of exactly the kind this
    lane exists to stop publishing.
    """
    laws.enforce(document, previous_group_list(previous))

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifact_path(target)
    scratch = path.with_suffix(f".{os.getpid()}.tmp")

    with open(scratch, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
    os.replace(scratch, path)

    json_handler.log_operation(
        "artifact_published",
        {
            "target": target.name,
            "path": str(path),
            "status": document.get("status"),
            "group_count": len(document.get("group_list", [])),
        },
    )
    return path


def exit_code_for(document: dict) -> int:
    """The shell-convenience exit code this artifact implies.

    Never the verdict. `seedgo.py` returns 0 on any truthy route, so a caller
    reading only the exit code cannot see a refusal at all — the `status` field
    and the `REFUSED:` stdout line carry that.
    """
    if document.get("status") == "refused":
        code = document.get("refusal", {}).get("code")
        return code if isinstance(code, int) else refusal.EXIT_UNPROVEN

    for name in document.get("group_list", []):
        group = document.get("groups", {}).get(name, {})
        score = group.get("score")
        if spine.is_scored(name) and isinstance(score, (int, float)) and score < 100:
            return refusal.EXIT_SCORED_FAILED

    return refusal.EXIT_PASSED
