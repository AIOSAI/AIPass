# =================== AIPass ====================
# Name: artifact.py
# Description: Audit Artifact Handler
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

"""
Audit Artifact Handler

Serialises a COMPLETE audit result set to a JSON file on disk.

WHY THIS EXISTS:
audit_display.py renders for a human and therefore truncates -- 10 files, 3
diagnostics per file, 5 violations per standard, messages clipped at 60 chars.
A branch reading that display as if it were the whole truth derived a violation
count that never existed (@prax, the "85 fossil rules" measurement). The display
budget is correct for a terminal and wrong for a machine, so machines get a
different surface: this one.

The artifact is a LOSSLESS projection of the same ``audit_results`` list the
display renders from. Nothing here caps, clips, sorts-and-takes, or summarises
away a violation. If a cap ever appears in this file, the feature is worthless
-- completeness is the entire point.

JOIN CONTRACT (the reason for the shape):
Consumers reconcile violations against a branch's ``.seedgo/bypass.json``,
whose rules key on ``(file, standard)`` where ``file`` is a branch-relative
POSIX path. So every violation row carries ``branch``, ``standard`` and a
branch-relative ``file`` as first-class fields -- no string parsing, no
basename guessing, no path arithmetic needed on the consumer side. The raw
path the checker reported is preserved alongside as ``abs_path``.

Doc shape (schema_version 1)::

    {
      "metadata": {schema_version, generated_at, seedgo_version, pack,
                   scope, target_branch, no_bypass, branches, branch_count,
                   totals},
      "branches":      [{name, path, average, scores, violation_count, ...}],
      "violations":    [{branch, standard, file, abs_path, score, issues, message}],
      "failed_checks": [{branch, standard, name, message}],
      "type_errors":   [{branch, file, errors, warnings, diagnostics: [...]}]
    }

Flat top-level lists, each row self-identifying by branch -- one loop to
filter, no nesting to walk, and no duplicated copy that could drift.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Bump when the doc SHAPE changes so consumers can gate on it.
SCHEMA_VERSION = 1

# audit/ -> handlers/ -> apps/ -> seedgo/  (never a hardcoded path)
_SEEDGO_ROOT = Path(__file__).resolve().parents[3]

ARTIFACT_DIR_NAME = ".seedgo"
ARTIFACT_FILE_NAME = "last_audit.json"


# =============================================================================
# PATHS
# =============================================================================


def default_artifact_path(specific_branch: Optional[str] = None, no_bypass: bool = False) -> Path:
    """Default destination for an audit artifact.

    Derived from this file's location, so it follows the checkout wherever it
    lives -- a clone, a container, another OS.

    ``last_audit.json`` means the FLEET and only the fleet. A single-branch run
    writes ``last_audit_{branch}.json`` instead, because a scoped run used to
    overwrite the fleet file with a one-branch document (@prax hit this within a
    minute of the feature landing). The metadata said scope=single-branch, but a
    consumer reading the file cold measured one branch and concluded the other
    16 were clean. Separate names mean that consumer gets no file rather than a
    confident subset.

    A ``--no-bypass`` run gets a ``_no_bypass`` suffix for exactly that reason:
    same fleet, same tree, deliberately lower numbers. Overwriting the normal
    artifact with it would hand the next cold reader a confident wrong answer.

    Args:
        specific_branch: Branch name for a single-branch run, else None.
        no_bypass: True when the run had every bypass rule switched off.

    Returns:
        Path to write the artifact to.
    """
    stem = ARTIFACT_FILE_NAME.removesuffix(".json")
    if specific_branch:
        stem = f"{stem}_{specific_branch}"
    if no_bypass:
        stem = f"{stem}_no_bypass"
    return _SEEDGO_ROOT / ARTIFACT_DIR_NAME / f"{stem}.json"


def _seedgo_version() -> Optional[str]:
    """Seedgo's own version string, or None when it cannot be read.

    Imported lazily and defensively: a handler must not hard-depend on the
    entry point it is called from, and a missing version is metadata worth
    omitting -- never a reason to lose an audit artifact.
    """
    try:
        from aipass.seedgo.apps.seedgo import VERSION

        return str(VERSION)
    except Exception as e:
        logger.info("[audit_artifact] seedgo VERSION unavailable: %s", e)
        return None


def _branch_relative(raw: str, branch_root: Path) -> str:
    """Branch-relative POSIX path -- the join key against bypass.json's 'file'.

    Checkers report either an absolute path or an already-relative one; both
    arrive here and leave in the single form a bypass rule is written in.
    """
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(branch_root).as_posix()
    except ValueError as e:
        logger.info("[audit_artifact] %s not relative to %s: %s", raw, branch_root, e)
        return path.as_posix()


# =============================================================================
# COLLECTORS -- one row per finding, nothing capped
# =============================================================================


def _collect_violations(result: Dict[str, Any], branch_name: str, branch_root: Path) -> List[Dict[str, Any]]:
    """Every per-file violation across every standard in one branch result.

    Reads the ``{standard}_violations`` keys audit_branch() writes, so a new
    checker pack shows up here with no change to this handler.
    """
    rows: List[Dict[str, Any]] = []
    for key in sorted(result):
        if not key.endswith("_violations"):
            continue
        standard = key.removesuffix("_violations")
        for violation in result.get(key) or []:
            raw = violation.get("path") or violation.get("file") or ""
            rows.append(
                {
                    "branch": branch_name,
                    "standard": standard,
                    "file": _branch_relative(raw, branch_root),
                    "file_name": Path(raw).name if raw else "",
                    "abs_path": raw,
                    "score": violation.get("score", 0),
                    "issues": list(violation.get("issues", [])),
                    "message": violation.get("message", ""),
                }
            )
    return rows


def _collect_failed_checks(result: Dict[str, Any], branch_name: str) -> List[Dict[str, Any]]:
    """Every failed check from results[standard]['checks'].

    Branch-level findings (architecture's missing dirs/files, crashed-checker
    reports) live only here -- they never become per-file violations, and the
    display renders them through a separate path.
    """
    rows: List[Dict[str, Any]] = []
    for standard, data in sorted(result.get("results", {}).items()):
        if not isinstance(data, dict):
            continue
        for check in data.get("checks") or []:
            if check.get("passed", False):
                continue
            rows.append(
                {
                    "branch": branch_name,
                    "standard": standard,
                    "name": check.get("name", ""),
                    "message": check.get("message", ""),
                }
            )
    return rows


def _collect_type_errors(result: Dict[str, Any], branch_name: str, branch_root: Path) -> List[Dict[str, Any]]:
    """Every diagnostics (pyright) file result with its full diagnostic list."""
    rows: List[Dict[str, Any]] = []
    for file_result in result.get("type_error_files") or []:
        raw = file_result.get("file", "")
        rows.append(
            {
                "branch": branch_name,
                "standard": "diagnostics",
                "file": _branch_relative(raw, branch_root),
                "file_name": Path(raw).name if raw else "",
                "abs_path": raw,
                "errors": file_result.get("errors", 0),
                "warnings": file_result.get("warnings", 0),
                "diagnostics": [dict(d) for d in file_result.get("diagnostics") or []],
            }
        )
    return rows


def _branch_entry(result: Dict[str, Any], violation_count: int) -> Dict[str, Any]:
    """Per-branch scores and context (the numbers, not the findings)."""
    branch = result.get("branch", {}) or {}
    return {
        "name": branch.get("name", ""),
        "path": branch.get("path", ""),
        "entry_file": branch.get("entry_file", ""),
        "average": result.get("average", 0),
        "scores": dict(result.get("scores", {})),
        "advisory_standards": list(result.get("advisory_standards", [])),
        "files_checked": result.get("files_checked", 0),
        "type_errors": result.get("type_errors", 0),
        "violation_count": violation_count,
        "cache_hit": bool(result.get("_cache_hit", False)),
        "elapsed_seconds": result.get("elapsed"),
        "info_lines": [dict(i) for i in result.get("info_lines") or []],
        "deprecated_patterns": [dict(p) for p in result.get("deprecated_patterns") or []],
        "test_map": result.get("test_map"),
    }


# =============================================================================
# PUBLIC API
# =============================================================================


def build_artifact(
    audit_results: List[Dict[str, Any]],
    pack: Optional[str] = None,
    specific_branch: Optional[str] = None,
    no_bypass: bool = False,
) -> Dict[str, Any]:
    """Build the complete artifact document from an audit result list.

    Args:
        audit_results: The audit's own result list -- the same object the
            display renders (and truncates) from.
        pack: Checker pack name, recorded in metadata.
        specific_branch: Branch name when the run targeted one branch; None
            means a full-fleet run.
        no_bypass: True when the run had every bypass rule switched off.
            Recorded in metadata so a consumer can tell the raw score from the
            normal one without inspecting the filename.

    Returns:
        The artifact doc (JSON-serialisable), uncapped and unclipped.
    """
    branches: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []
    failed_checks: List[Dict[str, Any]] = []
    type_errors: List[Dict[str, Any]] = []

    for result in audit_results:
        branch = result.get("branch", {}) or {}
        branch_name = branch.get("name", "")
        branch_root = Path(branch.get("path", ".")).resolve()

        branch_violations = _collect_violations(result, branch_name, branch_root)
        violations.extend(branch_violations)
        failed_checks.extend(_collect_failed_checks(result, branch_name))
        type_errors.extend(_collect_type_errors(result, branch_name, branch_root))
        branches.append(_branch_entry(result, len(branch_violations)))

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seedgo_version": _seedgo_version(),
            "pack": pack,
            "scope": "single-branch" if specific_branch else "full-fleet",
            "target_branch": specific_branch,
            "no_bypass": no_bypass,
            "branches": [b["name"] for b in branches],
            "branch_count": len(branches),
            "totals": {
                "violations": len(violations),
                "failed_checks": len(failed_checks),
                "type_error_files": len(type_errors),
                "type_errors": sum(r.get("type_errors", 0) for r in audit_results),
            },
        },
        "branches": branches,
        "violations": violations,
        "failed_checks": failed_checks,
        "type_errors": type_errors,
    }


def write_audit_artifact(
    audit_results: List[Dict[str, Any]],
    output_path: Optional[Any] = None,
    pack: Optional[str] = None,
    specific_branch: Optional[str] = None,
    no_bypass: bool = False,
) -> Path:
    """Write the complete audit result set to a JSON file. Returns its path.

    Raises whatever the filesystem raises -- an artifact that silently failed
    to write is exactly the "display looked complete" failure this feature
    exists to end. Callers report the error; they never swallow it.

    Args:
        audit_results: Complete audit result list.
        output_path: Destination override. Defaults to default_artifact_path().
        pack: Checker pack name, recorded in metadata.
        specific_branch: Branch name for a single-branch run, else None.
        no_bypass: True when the run had every bypass rule switched off — its
            own filename and its own metadata flag, never the normal one's.

    Returns:
        Path the artifact was written to.
    """
    path = Path(output_path) if output_path else default_artifact_path(specific_branch, no_bypass)
    document = build_artifact(audit_results, pack=pack, specific_branch=specific_branch, no_bypass=no_bypass)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")

    json_handler.log_operation(
        "audit_artifact_written",
        {
            "path": str(path),
            "branches": document["metadata"]["branch_count"],
            "violations": document["metadata"]["totals"]["violations"],
        },
    )
    return path
