# =================== AIPass ====================
# Name: memory_health.py
# Description: Branch Memory Health Checker
# Version: 0.2.1
# Created: 2026-01-30
# Modified: 2026-10-17
# =============================================

"""
Branch Memory Health Checker Handler
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Sequence

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler


STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_RED = "RED"

REQUIRED_FILES = [".trinity/local.json", "README.md"]

OPTIONAL_FILES = [".trinity/observations.json"]

FRESHNESS_WARNING_DAYS = 7
FRESHNESS_RED_DAYS = 30

# Containers a .trinity file must carry (schema 3.0.0). Caps are NOT checked here:
# they live in @memory's memory.config.json (merged per branch); a copy here would drift.
TRINITY_CONTAINERS: Dict[str, Sequence[str]] = {
    "local.json": ("sessions", "key_learnings", "todos"),
    "observations.json": ("observations",),
}


def check_memory_files_exist(branch_path: str) -> Dict[str, Any]:
    """Check if required memory files exist for a branch."""
    directory = Path(branch_path)
    trinity_dir = directory / ".trinity"

    required_checks = {
        ".trinity/local.json": trinity_dir / "local.json",
        "README.md": directory / "README.md",
    }

    optional_checks = {
        ".trinity/observations.json": trinity_dir / "observations.json",
        "DASHBOARD.local.json": directory / "DASHBOARD.local.json",
    }

    required_results = {}
    missing_required = []
    for name, path in required_checks.items():
        exists = path.exists() and path.is_file()
        required_results[name] = exists
        if not exists:
            missing_required.append(name)

    optional_results = {}
    missing_optional = []
    for name, path in optional_checks.items():
        exists = path.exists() and path.is_file()
        optional_results[name] = exists
        if not exists:
            missing_optional.append(name)

    return {
        "required": required_results,
        "optional": optional_results,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "all_required_present": len(missing_required) == 0,
    }


def validate_memory_structure(file_path: str, expected_containers: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Validate memory file structure — is this .trinity file usable at all?"""
    path = Path(file_path)

    if expected_containers is None:
        expected_containers = TRINITY_CONTAINERS.get(path.name, ())

    def _failure(issue: str) -> Dict[str, Any]:
        """Build an early-exit result for a file that cannot be read."""
        return {
            "valid": False,
            "has_metadata": False,
            "schema_version": None,
            "containers": {name: False for name in expected_containers or ()},
            "missing_containers": list(expected_containers or ()),
            "issues": [issue],
            "metadata_fields": [],
        }

    if not path.exists():
        return _failure("File does not exist")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in memory file %s: %s", file_path, e)
        return _failure(f"Invalid JSON: {str(e)}")
    except OSError as e:
        logger.warning("Cannot read memory file %s: %s", file_path, e)
        return _failure(f"Cannot read file: {str(e)}")

    issues = []

    has_metadata = False
    metadata_fields: List[str] = []
    metadata_section = None

    if "document_metadata" in data:
        has_metadata = True
        metadata_section = data["document_metadata"]
    elif "metadata" in data:
        has_metadata = True
        metadata_section = data["metadata"]

    if not has_metadata:
        issues.append("No metadata section found (expected 'document_metadata' or 'metadata')")

    # An unversioned file cannot be interpreted safely.
    schema_version = None
    if isinstance(metadata_section, dict):
        metadata_fields = list(metadata_section.keys())
        raw_version = metadata_section.get("schema_version")
        if isinstance(raw_version, str) and raw_version.strip():
            schema_version = raw_version
        else:
            issues.append("No readable 'schema_version' in metadata")

    containers: Dict[str, bool] = {}
    missing_containers: List[str] = []
    for name in expected_containers:
        present = isinstance(data.get(name), list)
        containers[name] = present
        if not present:
            missing_containers.append(name)
            issues.append(f"Missing entry container: '{name}'")

    valid = has_metadata and len(issues) == 0

    return {
        "valid": valid,
        "has_metadata": has_metadata,
        "schema_version": schema_version,
        "containers": containers,
        "missing_containers": missing_containers,
        "issues": issues,
        "metadata_fields": metadata_fields,
    }


def check_freshness(
    file_path: str, warning_days: int = FRESHNESS_WARNING_DAYS, red_days: int = FRESHNESS_RED_DAYS
) -> Dict[str, Any]:
    """Check when a file was last modified and determine freshness status."""
    path = Path(file_path)

    if not path.exists():
        return {
            "exists": False,
            "last_modified": None,
            "days_ago": None,
            "status": STATUS_RED,
            "message": "File does not exist",
        }

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        days_ago = (datetime.now() - mtime).total_seconds() / 86400

        if days_ago > red_days:
            status = STATUS_RED
            message = f"Not modified in {int(days_ago)} days (threshold: {red_days})"
        elif days_ago > warning_days:
            status = STATUS_WARNING
            message = f"Not modified in {int(days_ago)} days (threshold: {warning_days})"
        else:
            status = STATUS_OK
            message = f"Modified {days_ago:.1f} days ago"

        return {
            "exists": True,
            "last_modified": mtime.isoformat(),
            "days_ago": round(days_ago, 2),
            "status": status,
            "message": message,
        }
    except OSError as e:
        logger.error("Cannot read file stats for %s: %s", file_path, e)
        return {
            "exists": True,
            "last_modified": None,
            "days_ago": None,
            "status": STATUS_RED,
            "message": f"Cannot read file stats: {str(e)}",
        }


def get_memory_health_status(branch_path: str, branch_name: str) -> Dict[str, Any]:
    """Get comprehensive memory health status for a branch."""
    json_handler.log_operation("memory_health_check", {"branch": branch_name})
    directory = Path(branch_path)
    issues: List[str] = []

    file_check = check_memory_files_exist(branch_path)

    if not file_check["all_required_present"]:
        for missing in file_check["missing_required"]:
            issues.append(f"Missing required file: {missing}")

    for missing in file_check["missing_optional"]:
        issues.append(f"Missing optional file: {missing}")

    structure_checks = {}
    trinity_dir = directory / ".trinity"
    local_file = trinity_dir / "local.json"
    obs_file = trinity_dir / "observations.json"

    if local_file.exists():
        local_validation = validate_memory_structure(str(local_file))
        structure_checks[".trinity/local.json"] = local_validation
        if not local_validation["valid"]:
            for issue in local_validation["issues"]:
                issues.append(f".trinity/local.json: {issue}")

    if obs_file.exists():
        obs_validation = validate_memory_structure(str(obs_file))
        structure_checks[".trinity/observations.json"] = obs_validation
        if not obs_validation["valid"]:
            for issue in obs_validation["issues"]:
                issues.append(f".trinity/observations.json: {issue}")

    freshness_checks = {}
    files_to_check = [
        (".trinity/local.json", local_file),
        ("README.md", directory / "README.md"),
    ]

    worst_freshness = STATUS_OK
    for name, path in files_to_check:
        if path.exists():
            freshness = check_freshness(str(path))
            freshness_checks[name] = freshness

            if freshness["status"] == STATUS_RED:
                worst_freshness = STATUS_RED
            elif freshness["status"] == STATUS_WARNING and worst_freshness != STATUS_RED:
                worst_freshness = STATUS_WARNING

    if not file_check["all_required_present"]:
        overall_status = STATUS_RED
    elif worst_freshness == STATUS_RED:
        overall_status = STATUS_RED
    elif file_check["missing_optional"] or worst_freshness == STATUS_WARNING:
        overall_status = STATUS_WARNING
    else:
        overall_status = STATUS_OK

    has_structure_issues = any(not check.get("valid", True) for check in structure_checks.values())
    if has_structure_issues and overall_status == STATUS_OK:
        overall_status = STATUS_WARNING

    return {
        "branch_name": branch_name,
        "branch_path": branch_path,
        "overall_status": overall_status,
        "file_check": file_check,
        "structure_checks": structure_checks,
        "freshness_checks": freshness_checks,
        "issues": issues,
        "check_time": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    print("Testing memory_health...")

    test_path = "."
    test_name = "EXAMPLE"

    print(f"\nChecking {test_name} at {test_path}")

    existence = check_memory_files_exist(test_path)
    print(f"  Required files present: {existence['all_required_present']}")
    print(f"  Missing required: {existence['missing_required']}")
    print(f"  Missing optional: {existence['missing_optional']}")

    local_path = f"{test_path}/.trinity/local.json"
    structure = validate_memory_structure(local_path)
    print(f"  Structure valid: {structure['valid']}")
    print(f"  Has metadata: {structure['has_metadata']}")
    print(f"  Schema version: {structure['schema_version']}")
    print(f"  Missing containers: {structure['missing_containers']}")

    freshness = check_freshness(local_path)
    print(f"  Freshness: {freshness['status']} ({freshness['message']})")

    health = get_memory_health_status(test_path, test_name)
    print(f"\n  Overall status: {health['overall_status']}")
    print(f"  Issues: {len(health['issues'])}")
    for issue in health["issues"][:5]:
        print(f"    - {issue}")
