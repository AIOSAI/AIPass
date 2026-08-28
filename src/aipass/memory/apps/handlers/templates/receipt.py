# =================== AIPass ====================
# Name: receipt.py
# Description: Per-branch .template_version.json receipt writer
# Version: 1.0.0
# Created: 2026-08-25
# Modified: 2026-08-25
# =============================================

"""Template Version Receipt

Writes the per-branch ``.trinity/.template_version.json`` receipt defined by
the trinity standard: which gold-source template version each memory file's
structure carries, when the templates last touched this branch, by which lane,
and when the caps/meta lines were last re-rendered.

Its entire job is to make *"who actually carries the current standard"* a
lookup instead of an audit.

Honesty rules baked in here:

- A branch a push **skipped** shows its OLD stamp, never the fleet's intent.
  Nothing in this module writes a stamp on behalf of a lane that did not run.
- ``bump_config_rendered`` refuses to create a receipt. The renderer re-renders
  numbers; it has no idea which template version the files were built from, so
  claiming one would be a guess written down as a fact.
- Only the three sanctioned lanes may stamp. A free-text ``stamped_by`` would
  turn the receipt into a rumour.

Not to be confused with ``memory/templates/.template_version.json`` — a
different, template-side push log with its own shape and its own role.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

RECEIPT_NAME = ".template_version.json"

# The three lanes allowed to stamp a branch, exactly as the standard names them.
STAMPED_BY_PUSH = "memory push"
STAMPED_BY_BIRTH = "spawn birth"
STAMPED_BY_RESET = "reset"
_SANCTIONED_LANES = (STAMPED_BY_PUSH, STAMPED_BY_BIRTH, STAMPED_BY_RESET)

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"
_GOLD_SOURCE = {
    "local": "LOCAL.template.json",
    "observations": "OBSERVATIONS.template.json",
}


def _now() -> str:
    """Timestamp in the shape the standard specifies (seconds, no microseconds)."""
    return datetime.now().isoformat(timespec="seconds")


def template_versions() -> dict[str, str]:
    """Read the structural version each gold-source template carries.

    Raises rather than defaulting: a receipt naming a version nobody can read
    off the templates is worse than no receipt at all.
    """
    versions: dict[str, str] = {}
    for key, name in _GOLD_SOURCE.items():
        data = json.loads((_TEMPLATES_DIR / name).read_text(encoding="utf-8"))
        version = data.get("document_metadata", {}).get("schema_version")
        if not isinstance(version, str):
            raise ValueError(f"{name}: document_metadata.schema_version is missing or not a string")
        versions[key] = version
    return versions


def read_receipt(trinity_dir: Path) -> dict[str, Any] | None:
    """Return a branch's receipt, or ``None`` when it has none.

    An unreadable receipt also reads as ``None`` — with an ERROR logged. The
    caller's next move (write a fresh one, or refuse) is theirs to choose;
    this function does not silently repair someone's file.
    """
    path = Path(trinity_dir) / RECEIPT_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.error(f"[receipt] Unreadable receipt at {path}: {type(exc).__name__}: {exc}")
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, payload: dict[str, Any]) -> bool:
    """Atomic write: tmp file then replace, same contract as the config writer."""
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
    """Stamp a branch's receipt after a lane has actually touched its templates.

    Args:
        trinity_dir: The branch's ``.trinity/`` directory.
        stamped_by: One of ``STAMPED_BY_PUSH``, ``STAMPED_BY_BIRTH``,
            ``STAMPED_BY_RESET``. Anything else is refused.
        config_rendered: Optional explicit render timestamp. When omitted, an
            existing value is preserved and a new receipt gets the stamp time.

    Returns:
        ``{"success": True, "path": str, "receipt": dict}`` or
        ``{"success": False, "error": str}``.
    """
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
    existing = read_receipt(trinity_dir) or {}
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

    Touches ``config_rendered`` and nothing else — ``stamped``/``stamped_by``
    belong to the lane that delivered the templates and must survive a render.

    Refuses when there is no receipt yet. The renderer knows the numbers, not
    which template version the files were built from; creating one here would
    put a guess where the standard expects a fact.
    """
    trinity_dir = Path(trinity_dir)
    existing = read_receipt(trinity_dir)
    if existing is None:
        return {
            "success": False,
            "error": f"No receipt at {trinity_dir / RECEIPT_NAME} — only a push, birth, or reset may create one",
        }

    existing["config_rendered"] = _now()
    if not _write(trinity_dir / RECEIPT_NAME, existing):
        return {"success": False, "error": f"Failed to write {trinity_dir / RECEIPT_NAME}"}
    return {"success": True, "receipt": existing}
