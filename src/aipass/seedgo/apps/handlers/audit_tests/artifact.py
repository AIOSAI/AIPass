# =================== AIPass ====================
# Name: artifact.py
# Description: audit-tests artifact assembly, provenance and write
# Version: 1.0.1
# Created: 2026-08-29
# Modified: 2026-10-24
# =============================================

"""
Artifact assembly. The artifact IS the verdict; the exit code is a convenience.

Named `audit_tests_<target>.json`, never `last_audit_*`: a different schema, and
`.seedgo/audit_tests_*.json` needs its own ignore entry. Written into seedgo's
own `.seedgo/`, never the target's (gateway_boundary).
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

SEEDGO_ROOT = module_file(__file__).parents[3]
ARTIFACT_DIR = SEEDGO_ROOT / ".seedgo"

FIRST_RUN_BASELINE = "first run for this pair"


def artifact_path(target: target_module.Target) -> Path:
    """Absolute path this target's artifact is written to."""
    return ARTIFACT_DIR / f"{target.artifact_name()}.json"


def load_previous(target: target_module.Target) -> Optional[dict]:
    """The previous artifact for this target, or None if there is not one.

    A damaged file reads as None, which records a missing baseline, not "nothing vanished".
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

    `executed_order` is recorded because a baseline is order-specific (serial vs xdist).
    """
    started = started or datetime.now(timezone.utc)
    prior_list = previous_group_list(previous)

    # No previous artifact means the S3 diff did not run; the baseline says so.
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

    Previous groups carry forward: dropping them would make S3 refuse the refusal itself.
    """
    names = list(group_list or spine.CORE_SPINE)
    for previous_name in previous_group_list(previous) or []:
        if previous_name not in names:
            names.append(previous_name)
    groups = {}
    for name in names:
        # Neither base sets a status: the override below is the only place, so a test can kill it.
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


def publish(document: dict, target: target_module.Target, previous: Optional[dict] = None) -> Path:
    """Validate against every law, then write. Raises LawViolation if unlawful."""
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

    Never the verdict: `seedgo.py` returns 0 on any truthy route, so `status` carries refusals.
    """
    if document.get("status") == "refused":
        code = document.get("refusal", {}).get("code")
        return code if isinstance(code, int) else refusal.EXIT_UNPROVEN

    if unproven_reasons(document):
        return refusal.EXIT_UNPROVEN

    for name in document.get("group_list", []):
        group = document.get("groups", {}).get(name, {})
        score = group.get("score")
        if spine.is_scored(name) and isinstance(score, (int, float)) and score < 100:
            return refusal.EXIT_SCORED_FAILED

    return refusal.EXIT_PASSED


def unproven_reasons(document: dict) -> List[str]:
    """Why a published measurement cannot be trusted; empty when nothing undermines it.

    A score beside a failed self-check or a changed real tree is not a verdict.
    """
    reasons: List[str] = []
    failed = (document.get("harness") or {}).get("failed")
    if failed:
        reasons.append(f"{failed} harness self-check(s) failed")
    if (document.get("m10_proof") or {}).get("real_tree_unchanged") is False:
        reasons.append("the real tree changed during the run")
    return reasons
