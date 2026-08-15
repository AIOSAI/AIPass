# =================== AIPass ====================
# Name: memory_health.py
# Description: Branch Memory Health Checker
# Version: 0.2.0
# Created: 2026-01-30
# Modified: 2026-08-15
# =============================================

"""
Branch Memory Health Checker Handler

Validates memory file existence, structure, and freshness for branches.
Provides health status reporting for the Branch Activity Monitoring System.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Sequence

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler


# Health status constants
STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_RED = "RED"

# Required memory files (branch cannot function properly without these)
# These live inside the .trinity/ subdirectory of each branch
REQUIRED_FILES = [".trinity/local.json", "README.md"]

# Optional memory files (nice to have, warning if missing)
OPTIONAL_FILES = [".trinity/observations.json"]

# Freshness thresholds (in days)
FRESHNESS_WARNING_DAYS = 7
FRESHNESS_RED_DAYS = 30

# Structural containers a .trinity file must carry (schema 3.0.0), keyed by filename.
# A file missing one of these is genuinely broken — the entries have nowhere to land.
#
# Caps are deliberately NOT checked here. Schema 3.0.0 moved limits out of every
# .trinity file into @memory's memory.config.json, where defaults are deep-merged
# with per-branch overrides. A copy of the caps in this handler would be a snapshot
# that drifts, and re-implementing the merge is how @memory and @daemon end up
# disagreeing about "over cap". Entry-count and entry-size health are @memory's
# read-only APIs to answer, not ours to re-derive (@memory, 2026-08-13).
TRINITY_CONTAINERS: Dict[str, Sequence[str]] = {
    "local.json": ("sessions", "key_learnings", "todos"),
    "observations.json": ("observations",),
}


def check_memory_files_exist(branch_path: str, branch_name: str) -> Dict[str, Any]:
    """
    Check if required memory files exist for a branch.

    Required files (actual .trinity/ structure):
    - .trinity/local.json
    - README.md

    Optional files:
    - .trinity/observations.json
    - DASHBOARD.local.json

    Args:
        branch_path: Absolute path to the branch directory.
        branch_name: Name of the branch (uppercase, e.g., "DRONE").

    Returns:
        Dict with structure:
        {
            "required": {"filename": bool, ...},
            "optional": {"filename": bool, ...},
            "missing_required": [str],
            "missing_optional": [str],
            "all_required_present": bool
        }
    """
    directory = Path(branch_path)
    trinity_dir = directory / ".trinity"

    # Build expected file paths
    required_checks = {
        ".trinity/local.json": trinity_dir / "local.json",
        "README.md": directory / "README.md",
    }

    optional_checks = {
        ".trinity/observations.json": trinity_dir / "observations.json",
        "DASHBOARD.local.json": directory / "DASHBOARD.local.json",
    }

    # Check required files
    required_results = {}
    missing_required = []
    for name, path in required_checks.items():
        exists = path.exists() and path.is_file()
        required_results[name] = exists
        if not exists:
            missing_required.append(name)

    # Check optional files
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
    """
    Validate memory file structure — is this .trinity file usable at all?

    Checks the three things that make a memory file structurally sound:
    - a metadata section exists ("document_metadata" or "metadata")
    - that metadata carries a readable schema_version
    - the entry containers for this filename exist and are lists

    Caps are NOT checked here — see TRINITY_CONTAINERS for why.

    Args:
        file_path: Absolute path to the memory file.
        expected_containers: Container names to require. Defaults to the
            TRINITY_CONTAINERS entry for the filename (empty for unknown names).

    Returns:
        Dict with structure:
        {
            "valid": bool,
            "has_metadata": bool,
            "schema_version": str or None,
            "containers": {"name": bool, ...},
            "missing_containers": [str],
            "issues": [str],
            "metadata_fields": [str] (if metadata exists)
        }
    """
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

    # Check for metadata section
    # Memory files use either "document_metadata" or "metadata"
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

    # Check schema_version — an unversioned file cannot be interpreted safely
    schema_version = None
    if isinstance(metadata_section, dict):
        metadata_fields = list(metadata_section.keys())
        raw_version = metadata_section.get("schema_version")
        if isinstance(raw_version, str) and raw_version.strip():
            schema_version = raw_version
        else:
            issues.append("No readable 'schema_version' in metadata")

    # Check entry containers — a missing container means entries have nowhere to land
    containers: Dict[str, bool] = {}
    missing_containers: List[str] = []
    for name in expected_containers:
        present = isinstance(data.get(name), list)
        containers[name] = present
        if not present:
            missing_containers.append(name)
            issues.append(f"Missing entry container: '{name}'")

    # Overall validity
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
    """
    Check when a file was last modified and determine freshness status.

    Args:
        file_path: Absolute path to the file.
        warning_days: Days after which status becomes WARNING.
        red_days: Days after which status becomes RED.

    Returns:
        Dict with structure:
        {
            "exists": bool,
            "last_modified": str (ISO format) or None,
            "days_ago": float or None,
            "status": "OK" | "WARNING" | "RED",
            "message": str
        }
    """
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
    """
    Get comprehensive memory health status for a branch.

    Combines file existence, structure validation, and freshness checks
    into an overall health assessment.

    Health Status Levels:
    - OK: All required files present, valid structure, recent activity
    - WARNING: Missing optional files or stale (7+ days)
    - RED: Missing required files or very stale (30+ days)

    Args:
        branch_path: Absolute path to the branch directory.
        branch_name: Name of the branch (uppercase, e.g., "DRONE").

    Returns:
        Dict with structure:
        {
            "branch_name": str,
            "branch_path": str,
            "overall_status": "OK" | "WARNING" | "RED",
            "file_check": {file existence results},
            "structure_checks": {filename: validation result},
            "freshness_checks": {filename: freshness result},
            "issues": [str],
            "check_time": str
        }
    """
    json_handler.log_operation("memory_health_check", {"branch": branch_name})
    directory = Path(branch_path)
    issues: List[str] = []

    # Step 1: Check file existence
    file_check = check_memory_files_exist(branch_path, branch_name)

    if not file_check["all_required_present"]:
        for missing in file_check["missing_required"]:
            issues.append(f"Missing required file: {missing}")

    for missing in file_check["missing_optional"]:
        issues.append(f"Missing optional file: {missing}")

    # Step 2: Validate structure of existing memory files (.trinity/ paths)
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

    # Step 3: Check freshness
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

            # Track worst freshness status
            if freshness["status"] == STATUS_RED:
                worst_freshness = STATUS_RED
            elif freshness["status"] == STATUS_WARNING and worst_freshness != STATUS_RED:
                worst_freshness = STATUS_WARNING

    # Step 4: Determine overall status
    if not file_check["all_required_present"]:
        overall_status = STATUS_RED
    elif worst_freshness == STATUS_RED:
        overall_status = STATUS_RED
    elif file_check["missing_optional"] or worst_freshness == STATUS_WARNING:
        overall_status = STATUS_WARNING
    else:
        overall_status = STATUS_OK

    # Filter out structure check issues from issues list for WARNING-only items
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
    # Simple test
    print("Testing memory_health...")

    # Test with a sample branch path
    test_path = "."
    test_name = "EXAMPLE"

    print(f"\nChecking {test_name} at {test_path}")

    # Test file existence
    existence = check_memory_files_exist(test_path, test_name)
    print(f"  Required files present: {existence['all_required_present']}")
    print(f"  Missing required: {existence['missing_required']}")
    print(f"  Missing optional: {existence['missing_optional']}")

    # Test structure validation
    local_path = f"{test_path}/.trinity/local.json"
    structure = validate_memory_structure(local_path)
    print(f"  Structure valid: {structure['valid']}")
    print(f"  Has metadata: {structure['has_metadata']}")
    print(f"  Schema version: {structure['schema_version']}")
    print(f"  Missing containers: {structure['missing_containers']}")

    # Test freshness
    freshness = check_freshness(local_path)
    print(f"  Freshness: {freshness['status']} ({freshness['message']})")

    # Test overall health
    health = get_memory_health_status(test_path, test_name)
    print(f"\n  Overall status: {health['overall_status']}")
    print(f"  Issues: {len(health['issues'])}")
    for issue in health["issues"][:5]:
        print(f"    - {issue}")
