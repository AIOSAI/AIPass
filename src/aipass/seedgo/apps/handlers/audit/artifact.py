# =================== AIPass ====================
# Name: artifact.py
# Description: Audit Artifact Handler
# Version: 1.3.1
# Created: 2026-08-11
# Modified: 2026-10-24
# =============================================

"""
Audit Artifact Handler

A lossless projection of ``audit_results`` for machines (the display truncates): never cap here.
Rows carry ``branch``, ``standard`` and branch-relative ``file``, the join key of bypass.json.

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
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import incremental_cache
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

# Bump when the doc SHAPE changes so consumers can gate on it.
SCHEMA_VERSION = 1

_SEEDGO_ROOT = module_file(__file__).parents[3]

ARTIFACT_DIR_NAME = ".seedgo"
ARTIFACT_FILE_NAME = "last_audit.json"

#: The pack whose artifact keeps the bare name CI and every consumer read; others are suffixed.
DEFAULT_PACK_NAME = "aipass"


def default_artifact_path(
    specific_branch: Optional[str] = None,
    no_bypass: bool = False,
    pack: Optional[str] = None,
) -> Path:
    """Default destination for an audit artifact.

    ``last_audit.json`` is the default-pack fleet run only; a branch, ``--no-bypass`` or other
    pack run gets its own suffix, so a cold reader never takes a subset for the fleet record.
    """
    stem = ARTIFACT_FILE_NAME.removesuffix(".json")
    if pack and pack != DEFAULT_PACK_NAME:
        stem = f"{stem}_pack_{pack}"
    if specific_branch:
        stem = f"{stem}_{specific_branch}"
    if no_bypass:
        stem = f"{stem}_no_bypass"
    return _SEEDGO_ROOT / ARTIFACT_DIR_NAME / f"{stem}.json"


def _seedgo_version() -> Optional[str]:
    """Seedgo's own version string, or None; lazy so a handler never hard-depends on its entry point."""
    try:
        from aipass.seedgo.apps.seedgo import VERSION

        return str(VERSION)
    except Exception as e:
        logger.info("[audit_artifact] seedgo VERSION unavailable: %s", e)
        return None


def _branch_relative(raw: str, branch_root: Path) -> str:
    """Branch-relative POSIX path -- the join key against bypass.json's 'file'."""
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


def _collect_violations(result: Dict[str, Any], branch_name: str, branch_root: Path) -> List[Dict[str, Any]]:
    """Every per-file violation, read from the ``{standard}_violations`` keys audit_branch() writes."""
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
    """Every failed check from results[standard]['checks'], where branch-level findings live only."""
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
        "declined": {name: list(files) for name, files in (result.get("declined") or {}).items()},
        "ignored": {pattern: list(files) for pattern, files in (result.get("ignored") or {}).items()},
        "ignored_tracked": list(result.get("ignored_tracked") or []),
        "bypass_dead": [dict(entry) for entry in (result.get("bypass_dead") or [])],
        "bypass_markers": list(result.get("bypass_markers") or []),
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


def build_artifact(
    audit_results: List[Dict[str, Any]],
    pack: Optional[str] = None,
    specific_branch: Optional[str] = None,
    no_bypass: bool = False,
) -> Dict[str, Any]:
    """Build the complete artifact document from an audit result list."""
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

    Raises whatever the filesystem raises: a silently unwritten artifact is the failure this ends.
    """
    path = Path(output_path) if output_path else default_artifact_path(specific_branch, no_bypass, pack=pack)
    document = build_artifact(audit_results, pack=pack, specific_branch=specific_branch, no_bypass=no_bypass)

    incremental_cache.atomic_write(path, document)

    json_handler.log_operation(
        "audit_artifact_written",
        {
            "path": str(path),
            "branches": document["metadata"]["branch_count"],
            "violations": document["metadata"]["totals"]["violations"],
        },
    )
    return path
