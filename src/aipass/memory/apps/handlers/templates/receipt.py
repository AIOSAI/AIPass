# =================== AIPass ====================
# Name: receipt.py
# Description: Per-branch .template_version.json receipt writer
# Version: 1.2.0
# Created: 2026-08-25
# Modified: 2026-10-17
# =============================================

"""Template Version Receipt

Only a lane that actually ran may stamp, so a skipped branch keeps its OLD stamp. Not the
template-side push log at ``memory/templates/.template_version.json``.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.write_fence import fence_write

RECEIPT_NAME = ".template_version.json"

# The three lanes allowed to stamp a branch, exactly as the standard names them.
STAMPED_BY_PUSH = "memory push"
STAMPED_BY_BIRTH = "spawn birth"
STAMPED_BY_RESET = "reset"
_SANCTIONED_LANES = (STAMPED_BY_PUSH, STAMPED_BY_BIRTH, STAMPED_BY_RESET)

_TEMPLATES_DIR = module_file(__file__).parents[3] / "templates"
_GOLD_SOURCE = {
    "local": "LOCAL.template.json",
    "observations": "OBSERVATIONS.template.json",
}


def _now() -> str:
    """Timestamp in the shape the standard specifies (seconds, no microseconds)."""
    return datetime.now().isoformat(timespec="seconds")


def template_versions() -> dict[str, str]:
    """Read the structural version each gold-source template carries; raises rather than defaulting."""
    versions: dict[str, str] = {}
    for key, name in _GOLD_SOURCE.items():
        data = json.loads((_TEMPLATES_DIR / name).read_text(encoding="utf-8"))
        version = data.get("document_metadata", {}).get("schema_version")
        if not isinstance(version, str):
            raise ValueError(f"{name}: document_metadata.schema_version is missing or not a string")
        versions[key] = version
    return versions


class ReceiptUnreadable(ValueError):
    """A receipt file exists and cannot be read as a receipt."""


def read_receipt(trinity_dir: Path) -> dict[str, Any] | None:
    """Return a branch's receipt, or ``None`` when it has none.

    A present but unreadable file raises ReceiptUnreadable, never None: broken is not missing.
    """
    path = Path(trinity_dir) / RECEIPT_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ReceiptUnreadable(f"Unreadable receipt at {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReceiptUnreadable(f"Unreadable receipt at {path}: root is {type(data).__name__}, not an object")
    return data


def _write(path: Path, payload: dict[str, Any]) -> bool:
    """Atomic write: tmp file then replace, same contract as the config writer. Never outside the AIPass root."""
    if fence_write(path, lane="template_receipt") is not None:
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.error(f"[receipt] Failed to write {path}: {exc}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False
    return True


def write_receipt(
    trinity_dir: Path,
    stamped_by: str,
    config_rendered: str | None = None,
) -> dict[str, Any]:
    """Stamp a branch's receipt after a lane has actually touched its templates (sanctioned lanes only)."""
    if stamped_by not in _SANCTIONED_LANES:
        error = f"Unknown lane '{stamped_by}' — receipts may be stamped by: {', '.join(_SANCTIONED_LANES)}"
        logger.error(f"[receipt] {error}")
        return {"success": False, "error": error}

    trinity_dir = Path(trinity_dir)
    if not trinity_dir.is_dir():
        error = f"No .trinity directory at {trinity_dir}"
        logger.warning(f"[receipt] {error}")
        return {"success": False, "error": error}

    try:
        versions = template_versions()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = f"Cannot read gold-source templates: {exc}"
        logger.error(f"[receipt] {error}")
        return {"success": False, "error": error}

    stamped = _now()
    try:
        existing = read_receipt(trinity_dir) or {}
    except ReceiptUnreadable as exc:
        # This lane delivered the templates, so the receipt it writes is a fact; only config_rendered is lost.
        logger.warning(f"[receipt] {exc} — replaced by the {stamped_by} stamp")
        existing = {}
    rendered = config_rendered or existing.get("config_rendered") or stamped

    payload = {
        "template_versions": versions,
        "stamped": stamped,
        "stamped_by": stamped_by,
        "config_rendered": rendered,
    }

    path = trinity_dir / RECEIPT_NAME
    if not _write(path, payload):
        return {"success": False, "error": f"Failed to write {path}"}

    json_handler.log_operation(
        "write_receipt",
        {"branch_dir": str(trinity_dir.parent.name), "stamped_by": stamped_by, "versions": versions},
        module_name="receipt",
    )
    return {"success": True, "path": str(path), "receipt": payload}


def bump_config_rendered(trinity_dir: Path) -> dict[str, Any]:
    """Record that caps and meta lines were just re-rendered for this branch.

    Touches only ``config_rendered``, and refuses to create a receipt: the renderer cannot know the version.
    """
    trinity_dir = Path(trinity_dir)
    try:
        existing = read_receipt(trinity_dir)
    except ReceiptUnreadable as exc:
        logger.error(f"[receipt] {exc}")
        return {"success": False, "error": str(exc)}
    if existing is None:
        return {
            "success": False,
            "error": f"No receipt at {trinity_dir / RECEIPT_NAME} — only a push, birth, or reset may create one",
        }

    existing["config_rendered"] = _now()
    if not _write(trinity_dir / RECEIPT_NAME, existing):
        return {"success": False, "error": f"Failed to write {trinity_dir / RECEIPT_NAME}"}
    return {"success": True, "receipt": existing}
