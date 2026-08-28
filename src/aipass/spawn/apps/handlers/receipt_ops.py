# =================== AIPass ====================
# Name: receipt_ops.py
# Description: Birth receipt — stamp .trinity/.template_version.json onto a newborn
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Stamp the trinity template receipt at birth.

The receipt answers one question for the machinery that caps, rolls and scores
memory files: *which version of the trinity templates does this citizen carry?*
@memory's push stamps it for living branches. Nothing stamped it at birth, so a
newborn scored 0 on the receipt group and 80 on the file set from its first
minute — in violation before it had written a single entry.

THE SHAPE IS @memory's, COPIED NOT IMPORTED. Four keys, no more:
``template_versions`` (str ``local`` and ``observations``), ``stamped``,
``stamped_by``, ``config_rendered``. Birth must not acquire a runtime dependency
on another branch's handlers — a citizen that cannot be born because @memory's
package failed to import is a worse failure than a missing receipt. The copy is
held honest by ``tests/test_birth_receipt.py``, which parses their source for
the sanctioned lane name and goes red if it moves.

THE VERSIONS COME FROM THE GOLD SOURCE, NOT FROM SPAWN'S OWN SEEDS. @seedgo's
receipt check compares the receipt against ``memory/templates/*.template.json``
— so reading spawn's copies here would let a drifted seed mint a citizen whose
receipt claims a version the fleet's gold source never issued, and the lie would
score green. Seed drift is caught separately, by a test, where it belongs.

A gold source that cannot be read yields NO receipt and an error the caller
surfaces. A receipt naming a version nobody can verify is worse than no receipt:
the checker reads it as a claim, not as an absence.
"""

import json
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler

__all__ = ["STAMPED_BY_BIRTH", "RECEIPT_NAME", "gold_template_versions", "write_birth_receipt"]


RECEIPT_NAME = ".template_version.json"

# @memory's sanctioned lane names — their writer refuses anything else. Spawn
# owns exactly one of them.
STAMPED_BY_BIRTH = "spawn birth"

# The gold trinity templates: @memory owns them, @seedgo scores against them.
_GOLD_TEMPLATES = {"local": "LOCAL.template.json", "observations": "OBSERVATIONS.template.json"}


def _gold_dir() -> Path:
    """Directory holding the fleet's gold trinity templates."""
    return Path(__file__).resolve().parents[3] / "memory" / "templates"


def gold_template_versions() -> dict:
    """Read the trinity template versions the fleet currently ships.

    Raises:
        ValueError: a gold template is missing, unparseable, or carries no
            readable ``document_metadata.schema_version``.
    """
    versions = {}
    for key, filename in _GOLD_TEMPLATES.items():
        path = _gold_dir() / filename
        try:
            data = json_handler.read_json(path)
        except OSError as exc:
            raise ValueError(f"gold template unreadable: {path} ({exc})") from exc
        if not isinstance(data, dict):
            raise ValueError(f"gold template unreadable: {path}")
        # schema_version is THE version field for this receipt, not document
        # metadata's own `version` — the two differ in the gold templates
        # (LOCAL 2.0.0 / OBSERVATIONS 1.0.0) and only schema_version tracks the
        # trinity standard both branches score against.
        value = data.get("document_metadata", {}).get("schema_version")
        if not isinstance(value, str) or not value:
            raise ValueError(f"gold template has no readable schema_version: {path}")
        versions[key] = value
    return versions


def write_birth_receipt(trinity_dir) -> dict:
    """Stamp the receipt into a newborn's ``.trinity/``.

    Args:
        trinity_dir: The newborn's ``.trinity`` directory.

    Returns:
        Dict with ``success`` and either ``receipt``/``path`` or ``error``.
        Never raises: a birth is not abandoned over a receipt, but the caller
        is told so it can surface the miss rather than swallow it.
    """
    trinity_dir = Path(trinity_dir)
    try:
        versions = gold_template_versions()
    except ValueError as exc:
        logger.error("[spawn] Birth receipt NOT stamped for %s: %s", trinity_dir, exc)
        return {"success": False, "error": str(exc)}

    stamped = datetime.now().isoformat(timespec="seconds")
    payload = {
        "template_versions": versions,
        "stamped": stamped,
        "stamped_by": STAMPED_BY_BIRTH,
        # A fresh receipt has never had config rendered into it separately, so
        # the two timestamps are the same fact until @memory's renderer moves one.
        "config_rendered": stamped,
    }

    path = trinity_dir / RECEIPT_NAME
    try:
        atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("[spawn] Birth receipt write failed for %s: %s", path, exc)
        return {"success": False, "error": f"receipt write failed: {exc}"}

    logger.info(
        "[spawn] Birth receipt stamped: %s (local=%s observations=%s)",
        path,
        versions["local"],
        versions["observations"],
    )
    json_handler.log_operation("birth_receipt_stamped", data={"path": str(path), "template_versions": versions})
    return {"success": True, "receipt": payload, "path": str(path)}
