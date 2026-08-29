# =================== AIPass ====================
# Name: artifact.py - the published artifact and the scoring laws it obeys
# Description: closed group list, not_applicable never 0, no single overall number
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Assemble and validate the artifact.

The scoring laws (``DESIGN_BRIEF`` §B.12, S1-S5) are enforced here rather than
trusted, because both of this month's confidently-wrong-number incidents were
artifacts that looked fine:

* **S1** a group that did not run is ``not_applicable`` with a reason, never 0.
* **S2** no single overall number, anywhere -- :func:`validate` walks the whole
  document looking for one.
* **S3** a dropped group must never raise the score, so no group is ever dropped.
* **S4** the group list is closed and enumerated, and :data:`GROUPS` is it.
* **S5** cache provenance is stamped from day one; the MVP always runs live.

A refusal is a first-class outcome.  If the canary was not caught, or the suite
did not run against the copy, every group's status is ``refused`` and the reason
travels with it.  A gate that cannot prove it can fire publishes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ARTIFACT_VERSION = "audit-tests-mvp/1"

#: S4 -- closed and enumerated.  Groups are never added or dropped at runtime.
GROUPS = (
    "hygiene",
    "static_ruff_pt",
    "static_self_skip",
    "static_mock_drift",
    "oracle_execution",
    "ai_advisory",
)

#: The only group the MVP scores.  Everything else nominates or is not built.
SCORED_GROUPS = ("hygiene",)

NOT_BUILT_REASON = "not built in MVP"

#: S2 -- a key whose name reads like a single verdict for the whole target.
_FORBIDDEN_KEY_FRAGMENTS = (
    "overall",
    "average",
    "aggregate",
    "total_score",
    "final_score",
    "composite",
    "grade",
)


class LawViolation(AssertionError):
    """The artifact broke one of its own publishing laws."""


def _walk(node: Any, path: str = "$"):
    """Every (path, key, value) in a nested document, for the law checks."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def validate(document: dict) -> None:
    """Raise :class:`LawViolation` if the artifact breaks S1-S5."""
    groups = document.get("groups")
    if not isinstance(groups, dict):
        raise LawViolation("S3/S4: the artifact has no groups block")
    if tuple(groups) != GROUPS:
        raise LawViolation(f"S4: group list is {tuple(groups)}, must be exactly {GROUPS}")
    if document.get("group_list") != list(GROUPS):
        raise LawViolation("S4: group_list must enumerate the closed set verbatim")
    if "cache" not in document:
        raise LawViolation("S5: cache provenance is not stamped")

    for name, group in groups.items():
        status = group.get("status")
        if status not in ("measured", "not_applicable", "refused"):
            raise LawViolation(f"S1: group {name} has status {status!r}")
        if status in ("not_applicable", "refused") and not group.get("reason"):
            raise LawViolation(f"S1: group {name} is {status} without a reason")
        if status != "measured" and "score" in group:
            raise LawViolation(f"S1: group {name} is {status} but carries a score - not-run is never 0")
        if status == "measured" and name not in SCORED_GROUPS and "score" in group:
            raise LawViolation(f"S7: group {name} nominates only and may not be scored")

    for path, node in _walk(document):
        if not isinstance(node, dict):
            continue
        for key in node:
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise LawViolation(f"S2: {path}.{key} looks like a single overall number")


def _refused_groups(reason: str) -> dict[str, dict]:
    """The group list a refusal publishes: enumerated, unmeasured, never zero."""
    return {name: {"status": "refused", "reason": reason} for name in GROUPS}


def build(
    *,
    target: dict,
    tool: dict,
    harness: dict,
    hygiene_group: dict | None,
    ruff_result: dict | None,
    self_skip_result: dict | None,
    mock_drift_result: dict | None,
    refusal: dict | None,
) -> dict:
    """Compose the artifact.  Refusal short-circuits every group at once."""
    if refusal is not None:
        groups = _refused_groups(refusal["reason"])
    else:
        assert hygiene_group is not None
        groups = {
            "hygiene": hygiene_group,
            "static_ruff_pt": _nominating(ruff_result, "ruff PT family"),
            "static_self_skip": _nominating(self_skip_result, "self-skip AST rule"),
            "static_mock_drift": _nominating(mock_drift_result, "mock-drift AST rule"),
            "oracle_execution": {"status": "not_applicable", "reason": NOT_BUILT_REASON},
            "ai_advisory": {"status": "not_applicable", "reason": NOT_BUILT_REASON},
        }
        groups = {name: groups[name] for name in GROUPS}

    document = {
        "artifact_version": ARTIFACT_VERSION,
        "status": "refused" if refusal else "published",
        "refusal": refusal,
        "cache": "none (MVP always runs live)",
        "tool": tool,
        "target": target,
        "group_list": list(GROUPS),
        "groups": groups,
        "harness": harness,
        "laws": {
            "S1": "a group that did not run is not_applicable with a reason, never 0",
            "S2": "no single number for the target, in the artifact or the terminal",
            "S3": "no group is ever dropped",
            "S4": "the group list is closed and enumerated",
            "S5": "cache provenance is stamped",
            "M1": "static nominates, execution convicts - every static finding is unconvicted",
            "M10": "the suite ran against a copy, never the real tree",
            "T10": "the gate proved it can fire before it was allowed to publish",
        },
    }
    validate(document)
    return document


def _nominating(result: dict | None, label: str) -> dict:
    """Wrap a static result, keeping S7's verdict shape: nominated, unconvicted."""
    if result is None:
        return {"status": "not_applicable", "reason": f"{label} did not run"}
    if result.get("status") == "not_applicable":
        return {
            "status": "not_applicable",
            "reason": result.get("reason", "not measured"),
            "verdict_shape": "nominated (unconvicted)",
        }
    nominations = result.get("nominations", [])
    group = {
        "status": "measured",
        "kind": "nominate_only",
        "verdict_shape": "nominated (unconvicted)",
        "note": "suspects. Law M1: static nominates, execution convicts. Nothing here feeds a score.",
        "nomination_count": len(nominations),
        "nominations": nominations,
    }
    for key in ("counters", "rule", "by_code", "ruff", "select", "isolated"):
        if key in result:
            group[key] = result[key]
    return group


def write(document: dict, path: Path) -> Path:
    """Write the artifact, validating one more time on the way out."""
    validate(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
