#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: registry.py - DPLAN Registry Handler
# Date: 2026-02-18
# Version: 1.0.0
# Category: devpulse/handlers/plan
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-18): Initial version - registry + summaries per FPLAN-0355
#
# CONNECTS:
#   - create.py (registers on plan creation)
#   - close.py (updates status on close)
#   - list.py (reads registry for enhanced list)
#   - dashboard.py (reads registry for counts)
#
# CODE STANDARDS:
#   - Handler independence: NO cross-domain imports
#   - NO Prax logging (per 3-tier: modules log, handlers don't)
#   - Pure business logic only
# ==============================================

"""
Registry Handler - DPLAN Registry and Summaries

Manages dplan_registry.json and dplan_summaries.json for tracking
plan metadata, status, tags, and AI-generated summaries.
"""

import json
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

from .status import extract_status, extract_tag, extract_description

# =============================================================================
# CONFIGURATION
# =============================================================================

DEVPULSE_ROOT = Path.home() / "aipass_os" / "dev_central" / "devpulse"
DEV_PLANNING_ROOT = Path.home() / "aipass_os" / "dev_central" / "dev_planning"
REGISTRY_FILE = DEVPULSE_ROOT / "devpulse_json" / "dplan_registry.json"
SUMMARIES_FILE = DEVPULSE_ROOT / "devpulse_json" / "dplan_summaries.json"


# =============================================================================
# REGISTRY OPERATIONS
# =============================================================================

def load_registry() -> Dict[str, Any]:
    """Load registry from disk, return empty structure if missing"""
    if not REGISTRY_FILE.exists():
        return {"plans": {}}
    try:
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"plans": {}}


def save_registry(data: Dict[str, Any]) -> None:
    """Save registry to disk"""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def register_plan(
    plan_number: int,
    topic: str,
    status: str,
    tag: str,
    file_path: str,
    date: str,
    description: str = ""
) -> None:
    """Register a new plan or update existing entry"""
    registry = load_registry()
    key = f"{plan_number:03d}"
    registry["plans"][key] = {
        "number": plan_number,
        "topic": topic,
        "status": status,
        "tag": tag,
        "file_path": file_path,
        "created": date,
        "description": description,
        "last_updated": datetime.now().isoformat()
    }
    save_registry(registry)


def update_plan_status(plan_number: int, new_status: str) -> None:
    """Update a plan's status in the registry"""
    registry = load_registry()
    key = f"{plan_number:03d}"
    if key in registry["plans"]:
        registry["plans"][key]["status"] = new_status
        registry["plans"][key]["last_updated"] = datetime.now().isoformat()
        if new_status == "complete":
            registry["plans"][key]["closed"] = datetime.now().isoformat()
        save_registry(registry)


def get_plan(plan_number: int) -> Optional[Dict[str, Any]]:
    """Get a single plan's registry entry"""
    registry = load_registry()
    key = f"{plan_number:03d}"
    return registry["plans"].get(key)


def populate_from_filesystem() -> Dict[str, Any]:
    """
    Scan dev_planning/ and build/update registry from all DPLAN files.

    Returns:
        Updated registry data
    """
    registry = load_registry()
    plans = registry.setdefault("plans", {})

    if not DEV_PLANNING_ROOT.exists():
        return registry

    for plan_file in DEV_PLANNING_ROOT.glob("DPLAN-*.md"):
        match = re.match(r"DPLAN-(\d+)_(.+)_(\d{4}-\d{2}-\d{2})\.md", plan_file.name)
        if not match:
            continue

        num = int(match.group(1))
        key = f"{num:03d}"
        topic = match.group(2).replace('_', ' ')
        date = match.group(3)
        status = extract_status(plan_file)
        tag = extract_tag(plan_file)
        description = extract_description(plan_file)

        # Preserve existing fields (like closed date), update the rest
        existing = plans.get(key, {})
        existing.update({
            "number": num,
            "topic": topic,
            "status": status,
            "tag": tag,
            "file_path": str(plan_file),
            "created": date,
            "description": description,
            "last_updated": datetime.now().isoformat()
        })
        plans[key] = existing

    save_registry(registry)
    return registry


# =============================================================================
# SUMMARY OPERATIONS
# =============================================================================

def load_summaries() -> Dict[str, Any]:
    """Load summaries cache from disk"""
    if not SUMMARIES_FILE.exists():
        return {}
    try:
        with open(SUMMARIES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_summaries(data: Dict[str, Any]) -> None:
    """Save summaries cache to disk"""
    SUMMARIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_summary(plan_number: int) -> str:
    """Get cached summary for a plan, returns empty string if not cached"""
    summaries = load_summaries()
    key = f"{plan_number:03d}"
    entry = summaries.get(key, {})
    return entry.get("summary", "")


def save_plan_summary(
    plan_number: int,
    summary: str,
    status: str = "",
    topic: str = "",
    file_path: str = ""
) -> None:
    """Save a summary to the cache"""
    summaries = load_summaries()
    key = f"{plan_number:03d}"
    summaries[key] = {
        "summary": summary,
        "status": status,
        "topic": topic,
        "file_path": file_path,
        "generated_at": datetime.now().isoformat(),
        "is_empty": not bool(summary)
    }
    save_summaries(summaries)


def generate_description_summary(plan_file: Path) -> str:
    """
    Extract a usable summary from a plan file.
    Uses the blockquote description line as summary.
    Falls back to empty string if no meaningful description found.

    Args:
        plan_file: Path to the plan file

    Returns:
        Summary string
    """
    description = extract_description(plan_file)
    if description:
        return description

    # Fallback: try to get the first line of the Vision section
    try:
        content = plan_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        in_vision = False
        for line in lines:
            if line.strip().startswith('## Vision'):
                in_vision = True
                continue
            if in_vision and line.strip() and not line.strip().startswith('#'):
                text = line.strip()
                if text != "What we're trying to achieve":
                    return text[:100]
                break
    except Exception:
        pass

    return ""
