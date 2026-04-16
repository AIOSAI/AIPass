# =================== AIPass ====================
# Name: differ.py
# Description: Template vs Branch Diff Handler
# Version: 0.2.0
# Created: 2026-02-14
# Modified: 2026-03-15
# =============================================

"""
Template vs Branch Diff Handler

Compares living template structure against a specific branch's memory files.
Reports structural differences without modifying any files.

Purpose:
    Audit tool to see what would change before pushing templates.
    Shows additions (fields in template not in branch), removals
    (deprecated fields in branch not in template), and modifications
    (structural fields that differ from template).

Independence:
    Reads templates and branch files directly. No service dependencies.
"""

import json
import copy
from pathlib import Path
from typing import Dict, Any, List

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

# =============================================================================
# PATH SETUP
# =============================================================================

MEMORY_ROOT = (
    Path(__file__).resolve().parent.parent.parent.parent
)  # handlers/templates/differ.py -> apps -> handlers -> templates -> memory/

# =============================================================================
# CONSTANTS
# =============================================================================

TEMPLATES_DIR = MEMORY_ROOT / "templates"
LOCAL_TEMPLATE = TEMPLATES_DIR / "LOCAL.template.json"
OBS_TEMPLATE = TEMPLATES_DIR / "OBSERVATIONS.template.json"

# Deprecated sections that should be flagged for removal
DEPRECATED_METADATA_KEYS = ["allowed_emojis"]
DEPRECATED_LIMIT_KEYS = ["max_word_count", "max_token_count"]
DEPRECATED_STATUS_KEYS = ["auto_compress_at"]
DEPRECATED_NOTES_KEYS = ["formatting_reference", "slash_command_tracking"]
DEPRECATED_GUIDELINES_KEYS = ["emoji_usage", "high_value_patterns", "low_value_patterns"]

# Structural sections to compare (not content)
LOCAL_STRUCTURAL = ["document_metadata", "notes"]
OBS_STRUCTURAL = ["document_metadata", "guidelines", "notes"]


# =============================================================================
# PLACEHOLDER REPLACEMENT
# =============================================================================


def _replace_placeholders(template: dict, branch_name: str) -> dict:
    """Replace {{BRANCHNAME}} and {{DATE}} in template values."""
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    result = copy.deepcopy(template)

    def _replace_in_value(val: Any) -> Any:
        if isinstance(val, str):
            return val.replace("{{BRANCHNAME}}", branch_name).replace("{{DATE}}", today)
        elif isinstance(val, list):
            return [_replace_in_value(item) for item in val]
        elif isinstance(val, dict):
            return {k: _replace_in_value(v) for k, v in val.items()}
        return val

    replaced = _replace_in_value(result)
    assert isinstance(replaced, dict)
    return replaced


# =============================================================================
# DIFF LOGIC
# =============================================================================


def _diff_structural_section(current: dict, template: dict, path_prefix: str) -> Dict[str, List[str]]:
    """
    Compare a structural section between current file and template.

    Args:
        current: Current section data
        template: Template section data
        path_prefix: Dot-path prefix for reporting (e.g., 'document_metadata')

    Returns:
        Dict with 'additions', 'removals', 'modifications' lists
    """
    diffs = {"additions": [], "removals": [], "modifications": []}

    if not isinstance(template, dict) or not isinstance(current, dict):
        return diffs

    # Keys in template but not in current = additions
    for key in template:
        full_path = f"{path_prefix}.{key}" if path_prefix else key
        if key not in current:
            diffs["additions"].append(f"{full_path}: {_truncate(template[key])}")
        elif isinstance(template[key], dict) and isinstance(current.get(key), dict):
            # Recurse for nested dicts (but only one level deep for structural)
            sub_diffs = _diff_structural_section(current[key], template[key], full_path)
            diffs["additions"].extend(sub_diffs["additions"])
            diffs["removals"].extend(sub_diffs["removals"])
            diffs["modifications"].extend(sub_diffs["modifications"])
        elif current[key] != template[key]:
            # Skip dynamic values that are expected to differ
            if key in (
                "current_lines",
                "health",
                "last_health_check",
                "current_key_learnings",
                "current_recently_completed",
                "created",
                "last_updated",
                "managed_by",
            ):
                continue
            diffs["modifications"].append(f"{full_path}: {_truncate(current[key])} -> {_truncate(template[key])}")

    return diffs


def _find_deprecated(data: dict, file_type: str) -> List[str]:
    """
    Find deprecated sections present in file.

    Args:
        data: Memory file data
        file_type: 'local' or 'observations'

    Returns:
        List of deprecated field paths found
    """
    found = []
    metadata = data.get("document_metadata", {})

    for key in DEPRECATED_METADATA_KEYS:
        if key in metadata:
            found.append(f"document_metadata.{key}")

    limits = metadata.get("limits", {})
    for key in DEPRECATED_LIMIT_KEYS:
        if key in limits:
            found.append(f"document_metadata.limits.{key}")

    status = metadata.get("status", {})
    for key in DEPRECATED_STATUS_KEYS:
        if key in status:
            found.append(f"document_metadata.status.{key}")

    notes = data.get("notes", {})
    if isinstance(notes, dict):
        for key in DEPRECATED_NOTES_KEYS:
            if key in notes:
                found.append(f"notes.{key}")

    if file_type == "observations":
        guidelines = data.get("guidelines", {})
        if isinstance(guidelines, dict):
            for key in DEPRECATED_GUIDELINES_KEYS:
                if key in guidelines:
                    found.append(f"guidelines.{key}")

    return found


def _truncate(val: Any, max_len: int = 60) -> str:
    """Truncate a value for display."""
    s = str(val)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


# =============================================================================
# PUBLIC API
# =============================================================================


def diff_template_vs_branch(branch_path: str | Path) -> dict:
    """
    Compare template structure against a specific branch's memory files.

    Reads branch memory files and compares structural sections against
    the living templates. Reports what would change on a template push.

    Args:
        branch_path: Path to branch directory (string or Path)

    Returns:
        dict with:
        - branch: branch name
        - local: {additions: [], removals: [], modifications: []} per file
        - observations: {additions: [], removals: [], modifications: []} per file
        - errors: list of any errors encountered
    """
    branch_path = Path(branch_path)
    branch_name = branch_path.name.upper()

    result = {"branch": branch_name, "path": str(branch_path), "local": [], "observations": [], "errors": []}

    # Load templates
    templates = {}
    for name, path in [("local", LOCAL_TEMPLATE), ("observations", OBS_TEMPLATE)]:
        if not path.exists():
            result["errors"].append(f"Template not found: {path}")
            return result
        try:
            with open(path, "r", encoding="utf-8") as f:
                templates[name] = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[differ] Failed to load template {path.name}: {e}")
            result["errors"].append(f"Failed to load template {path.name}: {e}")
            return result

    if not branch_path.exists():
        result["errors"].append(f"Branch path not found: {branch_path}")
        return result

    # Find and diff .local.json files
    for f in sorted(branch_path.iterdir()):
        if f.name.startswith("DASHBOARD") or f.name.startswith(".backup"):
            continue
        if not f.name.endswith(".local.json"):
            continue

        try:
            with open(f, "r", encoding="utf-8") as fh:
                current = json.load(fh)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[differ] Failed to read {f.name}: {e}")
            result["errors"].append(f"Failed to read {f.name}: {e}")
            continue

        tmpl = _replace_placeholders(templates["local"], branch_name)
        file_diff = {"file": f.name, "additions": [], "removals": [], "modifications": []}

        # Compare structural sections
        for section in LOCAL_STRUCTURAL:
            curr_section = current.get(section, {})
            tmpl_section = tmpl.get(section, {})
            diffs = _diff_structural_section(curr_section, tmpl_section, section)
            file_diff["additions"].extend(diffs["additions"])
            file_diff["modifications"].extend(diffs["modifications"])

        # Check for deprecated fields
        deprecated = _find_deprecated(current, "local")
        file_diff["removals"] = deprecated

        # Check missing top-level structural keys
        if "key_learnings" not in current:
            active = current.get("active_tasks", {})
            if not isinstance(active, dict) or "key_learnings" not in active:
                file_diff["additions"].append("key_learnings: {} (missing)")

        if file_diff["additions"] or file_diff["removals"] or file_diff["modifications"]:
            result["local"].append(file_diff)

    # Find and diff .observations.json files
    for f in sorted(branch_path.iterdir()):
        if f.name.startswith("DASHBOARD") or f.name.startswith(".backup"):
            continue
        if not f.name.endswith(".observations.json"):
            continue

        try:
            with open(f, "r", encoding="utf-8") as fh:
                current = json.load(fh)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[differ] Failed to read {f.name}: {e}")
            result["errors"].append(f"Failed to read {f.name}: {e}")
            continue

        tmpl = _replace_placeholders(templates["observations"], branch_name)
        file_diff = {"file": f.name, "additions": [], "removals": [], "modifications": []}

        for section in OBS_STRUCTURAL:
            curr_section = current.get(section, {})
            tmpl_section = tmpl.get(section, {})
            diffs = _diff_structural_section(curr_section, tmpl_section, section)
            file_diff["additions"].extend(diffs["additions"])
            file_diff["modifications"].extend(diffs["modifications"])

        deprecated = _find_deprecated(current, "observations")
        file_diff["removals"] = deprecated

        if file_diff["additions"] or file_diff["removals"] or file_diff["modifications"]:
            result["observations"].append(file_diff)

    json_handler.log_operation(
        "template_diff",
        {
            "branch": branch_name,
            "local_diffs": len(result["local"]),
            "obs_diffs": len(result["observations"]),
            "success": True,
        },
    )
    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    import sys as _sys

    args = _sys.argv[1:]
    if not args:
        _sys.stdout.write("Usage: drone @memory diff-templates\n")
        _sys.stdout.write("\nCompare template structure against a branch's memory files.\n")
        _sys.exit(1)

    branch = Path(args[0])
    result = diff_template_vs_branch(branch)

    _sys.stdout.write(f"\n=== Template Diff: {result['branch']} ===\n")
    _sys.stdout.write(f"Path: {result['path']}\n")

    for file_type in ["local", "observations"]:
        diffs = result[file_type]
        if not diffs:
            _sys.stdout.write(f"\n  {file_type}: up to date\n")
            continue
        for entry in diffs:
            _sys.stdout.write(f"\n  {entry['file']}:\n")
            if entry["additions"]:
                _sys.stdout.write("    Additions:\n")
                for a in entry["additions"]:
                    _sys.stdout.write(f"      + {a}\n")
            if entry["removals"]:
                _sys.stdout.write("    Removals (deprecated):\n")
                for r in entry["removals"]:
                    _sys.stdout.write(f"      - {r}\n")
            if entry["modifications"]:
                _sys.stdout.write("    Modifications:\n")
                for m in entry["modifications"]:
                    _sys.stdout.write(f"      ~ {m}\n")

    if result["errors"]:
        _sys.stdout.write("\n  Errors:\n")
        for err in result["errors"]:
            _sys.stdout.write(f"    ! {err}\n")

    _sys.stdout.write("\n")
    _sys.exit(0)
