# =================== AIPass ====================
# Name: trust_registry.py
# Version: 1.0.0
# Description: Trusted-project registry — DPLAN-0244 Layer B
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-07-15
# Modified: 2026-07-15
# =============================================

"""Trusted-project registry for hook config loading.

Single source of truth for which projects are trusted to have their
.aipass/hooks.json loaded by the hook engine. Registry lives at
~/.aipass/trusted_projects.json. @aipass CLI (init/trust/revoke)
imports this module for enrollment operations.
"""

import hashlib
import json
import os
from pathlib import Path

from aipass.hooks.apps.handlers.json import files as json_files
from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

REGISTRY_PATH = Path.home() / ".aipass" / "trusted_projects.json"


def _hash_file(path: Path) -> str:
    """Compute sha256 of a file's contents."""
    data = path.read_bytes()
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def read_registry() -> dict:
    """Read the trusted-project registry. Returns empty registry if absent or corrupt."""
    if not REGISTRY_PATH.exists():
        return {"version": 1, "projects": {}}
    try:
        data = json_files.read_json_file(REGISTRY_PATH)
        if not isinstance(data.get("projects"), dict):
            return {"version": 1, "projects": {}}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[HOOKS] bad trust registry %s: %s", REGISTRY_PATH, exc)
        return {"version": 1, "projects": {}}


def _write_registry(registry: dict) -> None:
    """Write the registry to disk, creating parent dirs if needed."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    json_files.write_json_file(REGISTRY_PATH, registry)


def enroll(project_dir: str) -> bool:
    """Enroll a project in the trusted registry. Returns True on success."""
    project_path = Path(project_dir).resolve()
    config_path = project_path / ".aipass" / "hooks.json"
    if not config_path.exists():
        logger.warning("[HOOKS] cannot enroll %s: no .aipass/hooks.json", project_path)
        return False
    config_hash = _hash_file(config_path)
    registry, dropped = prune_stale(read_registry())
    if dropped:
        logger.info("[HOOKS] enroll: pruned %d stale registry entries", dropped)
    registry["projects"][str(project_path)] = {
        "enrolled": _isoformat_now(),
        "config_hash": config_hash,
        "config_path": str(config_path),
    }
    _write_registry(registry)
    json_handler.log_operation("enroll", {"project": str(project_path)}, module_name="trust_registry")
    logger.info("[HOOKS] enrolled %s (hash=%s)", project_path, config_hash)
    return True


def revoke(project_dir: str) -> bool:
    """Remove a project from the trusted registry. Returns True if it was present."""
    project_path = str(Path(project_dir).resolve())
    registry = read_registry()
    if project_path not in registry["projects"]:
        return False
    del registry["projects"][project_path]
    _write_registry(registry)
    json_handler.log_operation("revoke", {"project": project_path}, module_name="trust_registry")
    logger.info("[HOOKS] revoked %s", project_path)
    return True


def is_trusted(project_dir: str) -> bool:
    """Check if a project is enrolled with a matching config hash."""
    project_path = str(Path(project_dir).resolve())
    registry = read_registry()
    entry = registry["projects"].get(project_path)
    if entry is None:
        return False
    config_path = Path(project_dir).resolve() / ".aipass" / "hooks.json"
    if not config_path.exists():
        return False
    current_hash = _hash_file(config_path)
    return current_hash == entry.get("config_hash", "")


def is_unenrolled(project_dir: str) -> bool:
    """True when a project has hooks.json but no registry entry at all.

    Distinct from is_hash_mismatch() — that flags an existing enrollment gone
    stale. This flags the normal first-run state: hooks.json exists, nobody
    has ever run `aipass init update` for this project, so hooks are
    silently off. Mutually exclusive with is_hash_mismatch() (an entry can't
    be both absent and present).
    """
    project_path = str(Path(project_dir).resolve())
    registry = read_registry()
    if project_path in registry["projects"]:
        return False
    config_path = Path(project_dir).resolve() / ".aipass" / "hooks.json"
    return config_path.exists()


def prune_stale(registry: dict) -> tuple[dict, int]:
    """Drop registry entries whose project path no longer exists on disk.

    Generic dead-path detection, not tmpdir-pattern matching -- catches any
    deleted or moved project, not just pytest tmp dirs. Returns the pruned
    registry and the number of entries dropped.
    """
    live = {path: entry for path, entry in registry["projects"].items() if Path(path).exists()}
    dropped = len(registry["projects"]) - len(live)
    return {**registry, "projects": live}, dropped


def is_hash_mismatch(project_dir: str) -> bool:
    """True only when a project WAS enrolled but its hooks.json hash has since changed.

    Distinct from is_trusted()==False for a never-enrolled project (normal
    first-run state, not a break). This flags a genuine trust break — an
    existing enrollment gone stale — so callers can warn loudly instead of
    treating it the same as "not set up yet".
    """
    project_path = str(Path(project_dir).resolve())
    registry = read_registry()
    entry = registry["projects"].get(project_path)
    if entry is None:
        return False
    config_path = Path(project_dir).resolve() / ".aipass" / "hooks.json"
    if not config_path.exists():
        return False
    return _hash_file(config_path) != entry.get("config_hash", "")


def bootstrap() -> bool:
    """Bootstrap the registry with ONLY the AIPass install. Returns True on success.

    Called when the registry file does not exist. Enrolls the AIPass
    install identified by $AIPASS_HOME — never the current CWD.
    """
    aipass_home = os.environ.get("AIPASS_HOME", "")
    if not aipass_home:
        logger.warning("[HOOKS] registry absent and AIPASS_HOME not set — cannot bootstrap")
        return False
    aipass_path = Path(aipass_home).resolve()
    config_path = aipass_path / ".aipass" / "hooks.json"
    if not config_path.exists():
        logger.warning(
            "[HOOKS] registry absent and AIPass hooks.json not found at %s",
            config_path,
        )
        return False
    config_hash = _hash_file(config_path)
    registry = {"version": 1, "projects": {}}
    registry["projects"][str(aipass_path)] = {
        "enrolled": _isoformat_now(),
        "config_hash": config_hash,
        "config_path": str(config_path),
    }
    _write_registry(registry)
    json_handler.log_operation("bootstrap", {"aipass_home": str(aipass_path)}, module_name="trust_registry")
    logger.info("[HOOKS] registry bootstrapped, enrolled AIPass install: %s", aipass_path)
    return True


def _isoformat_now() -> str:
    """Return current UTC time as ISO string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
