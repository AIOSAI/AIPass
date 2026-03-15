# =================== AIPass ====================
# Name: bootstrap.py
# Description: Init handler — bootstrap an AIPass project in any directory
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""
Init Bootstrap Handler - PRIVATE implementation

Business logic for `aipass init`. Creates the project scaffold:
  1. {NAME}_REGISTRY.json  — project registry with UUID
  2. .trinity/passport.json — project identity
  3. .trinity/local.json    — local context (empty)
  4. .trinity/observations.json — observations (empty)
  5. .aipass/aipass_local_prompt.md — local prompt
  6. AIPASS.md — project prompt

RULES:
  - Pure Python only (no module/prax/cli imports)
  - Returns dict, raises exceptions on errors
  - No hardcoded paths
"""

import json
import re
import uuid
from datetime import date
from pathlib import Path


def _sanitize_name(raw: str) -> str:
    """Sanitize a project name for use in filenames.

    Replaces non-alphanumeric characters (except underscore/hyphen) with
    underscores and strips leading/trailing underscores.
    """
    return re.sub(r"[^A-Z0-9_-]", "_", raw.upper()).strip("_")


def init_project(target: Path, project_name: str | None = None) -> dict:
    """Initialize an AIPass project in the target directory.

    Args:
        target: Directory to initialize
        project_name: Name for the registry (defaults to directory name)

    Returns:
        dict with registry_id, registry_file, project_name, target, created_files

    Raises:
        ValueError: If project name is empty after sanitization
        FileExistsError: If passport or registry already exists
    """
    target = target.resolve()
    if not target.exists():
        target.mkdir(parents=True)

    raw_name = project_name or target.name
    name = _sanitize_name(raw_name)
    if not name:
        raise ValueError(
            f"Cannot derive project name from '{raw_name}'. "
            "Pass a project name explicitly."
        )

    registry_id = str(uuid.uuid4())
    today = date.today().isoformat()
    created = []

    # 1. Registry
    registry_filename = f"{name}_REGISTRY.json"
    registry_path = target / registry_filename
    if registry_path.exists():
        raise FileExistsError(f"Registry already exists: {registry_path}")

    registry_data = {
        "metadata": {
            "id": registry_id,
            "name": name,
            "version": "1.0.0",
            "created": today,
            "last_updated": today,
            "total_branches": 0,
        },
        "branches": [],
    }
    registry_path.write_text(
        json.dumps(registry_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    created.append(str(registry_path))

    # 2. .trinity/
    trinity_dir = target / ".trinity"
    trinity_dir.mkdir(exist_ok=True)

    passport = {
        "document_metadata": {
            "document_type": "project_identity",
            "document_name": f"{name}.PASSPORT",
            "version": "1.0.0",
            "created": today,
            "last_updated": today,
        },
        "identity": {
            "project_name": name,
            "role": "project_root",
            "purpose": "",
        },
        "citizenship": {
            "registered": True,
            "registry_id": registry_id,
            "registry_name": name,
        },
    }
    passport_path = trinity_dir / "passport.json"
    if passport_path.exists():
        raise FileExistsError(
            f"Passport already exists: {passport_path}. "
            "Remove .trinity/passport.json to re-initialize."
        )
    passport_path.write_text(
        json.dumps(passport, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    created.append(str(passport_path))

    # local.json + observations.json
    for filename in ("local.json", "observations.json"):
        p = trinity_dir / filename
        if not p.exists():
            p.write_text("{}\n", encoding="utf-8")
            created.append(str(p))

    # 3. .aipass/
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    prompt_path = aipass_dir / "aipass_local_prompt.md"
    if not prompt_path.exists():
        prompt_path.write_text(
            f"# {name} — Local Prompt\n\nInjected every turn. Add project-specific context here.\n",
            encoding="utf-8",
        )
        created.append(str(prompt_path))

    # 4. AIPASS.md
    aipass_md = target / "AIPASS.md"
    if not aipass_md.exists():
        aipass_md.write_text(
            "# AIPass — Project Prompt\n\n"
            "Project-level instructions. Persists in context for the entire conversation.\n\n"
            "## Startup\n\n"
            "On any greeting, silently read these files from CWD and run the commands "
            "— no narration, no announcing steps. Just do it and respond with the status.\n\n"
            "**Read:** `.trinity/passport.json`, `.trinity/local.json`, "
            "`.trinity/observations.json`, `README.md`\n"
            "**Run:** `git status`\n\n"
            "## Memories\n\n"
            "Update `.trinity/` at natural breakpoints, after milestones, and on `/memo`. "
            "If compaction hits before you save, it's gone.\n",
            encoding="utf-8",
        )
        created.append(str(aipass_md))

    return {
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "project_name": name,
        "target": str(target),
        "created_files": created,
    }
