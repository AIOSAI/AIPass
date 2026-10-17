# =================== AIPass ====================
# Name: receipt_ops.py
# Description: Birth receipt — stamp .trinity/.template_version.json onto a newborn
# Version: 1.1.1
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Stamp the trinity template receipt at birth.

The shape is @memory's, copied not imported, so birth never fails on another branch's import.
Versions come from the gold source, never spawn's seeds. Reference: docs/birth.md"""

import json
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler

__all__ = [
    "STAMPED_BY_BIRTH",
    "STAMPED_BY_SCAFFOLD",
    "RECEIPT_NAME",
    "gold_template_versions",
    "seedgo_test_template",
    "write_birth_receipt",
    "write_test_template_receipt",
]


RECEIPT_NAME = ".template_version.json"

# @memory's sanctioned lane name; their writer refuses anything else.
STAMPED_BY_BIRTH = "spawn birth"

# Distinct from @seedgo's own "seedgo tests template bump" so a birth stamp reads apart from a fleet bump.
STAMPED_BY_SCAFFOLD = "spawn scaffold"

_GOLD_TEMPLATES = {"local": "LOCAL.template.json", "observations": "OBSERVATIONS.template.json"}

# Read @seedgo's own manifest, never a copy of it held here.
_TEST_TEMPLATE_MANIFEST = "templates.json"


def _gold_dir() -> Path:
    """Directory holding the fleet's gold trinity templates."""
    return Path(__file__).resolve().parents[3] / "memory" / "templates"


def _seedgo_templates_dir() -> Path:
    """Directory holding @seedgo's gold test template and its manifest.

    Resolved at the call, never at import: importing this module must not touch the filesystem."""
    return Path(__file__).resolve().parents[3] / "seedgo" / "templates"


def gold_template_versions() -> dict:
    """Read the trinity template versions the fleet currently ships.

    Raises ValueError when a gold template or its schema_version is unreadable."""
    versions = {}
    for key, filename in _GOLD_TEMPLATES.items():
        path = _gold_dir() / filename
        try:
            data = json_handler.read_json(path)
        except OSError as exc:
            raise ValueError(f"gold template unreadable: {path} ({exc})") from exc
        if not isinstance(data, dict):
            raise ValueError(f"gold template unreadable: {path}")
        # schema_version, not document_metadata.version: only schema_version tracks the scored standard.
        value = data.get("document_metadata", {}).get("schema_version")
        if not isinstance(value, str) or not value:
            raise ValueError(f"gold template has no readable schema_version: {path}")
        versions[key] = value
    return versions


def seedgo_test_template() -> tuple:
    """Read @seedgo's gold test template manifest as (versions, [(source_path, distributed_name)]).

    All or nothing: raises ValueError on any unreadable part rather than return a half-read manifest."""
    gold_dir = _seedgo_templates_dir()
    manifest_path = gold_dir / _TEST_TEMPLATE_MANIFEST
    try:
        data = json_handler.read_json(manifest_path)
    except OSError as exc:
        raise ValueError(f"test template manifest unreadable: {manifest_path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"test template manifest unreadable: {manifest_path}")

    versions = data.get("template_versions")
    if not isinstance(versions, dict) or not versions:
        raise ValueError(f"test template manifest has no readable template_versions: {manifest_path}")

    pages = []
    for name in versions:
        entry = data.get("files", {}).get(name, {})
        page, distributed_as = entry.get("page"), entry.get("distributed_as")
        if not isinstance(page, str) or not isinstance(distributed_as, str) or not page or not distributed_as:
            raise ValueError(f"test template manifest does not name the page for '{name}': {manifest_path}")
        source = gold_dir / page
        if not source.is_file():
            raise ValueError(f"test template page missing: {source}")
        pages.append((source, distributed_as))

    return dict(versions), pages


def write_test_template_receipt(tests_dir) -> dict:
    """Stamp @seedgo's test template receipt into a newborn's ``tests/``.

    Three keys, the same three @seedgo's bump writes. Never raises; an unreadable manifest leaves no receipt."""
    tests_dir = Path(tests_dir)
    try:
        versions, pages = seedgo_test_template()
    except ValueError as exc:
        logger.error("[spawn] Test template receipt NOT stamped for %s: %s", tests_dir, exc)
        return {"success": False, "error": str(exc)}

    payload = {
        "template_versions": versions,
        "stamped": datetime.now().isoformat(timespec="seconds"),
        "stamped_by": STAMPED_BY_SCAFFOLD,
    }

    path = tests_dir / RECEIPT_NAME
    written = []
    try:
        for source, distributed_as in pages:
            atomic_write_text(tests_dir / distributed_as, source.read_text(encoding="utf-8"))
            written.append(distributed_as)
        atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("[spawn] Test template receipt write failed for %s: %s", path, exc)
        return {"success": False, "error": f"test template receipt write failed: {exc}"}

    logger.info("[spawn] Test template receipt stamped: %s (%s)", path, versions)
    json_handler.log_operation(
        "test_template_receipt_stamped",
        data={"path": str(path), "template_versions": versions, "pages": written},
    )
    return {"success": True, "receipt": payload, "path": str(path), "pages": written}


def write_birth_receipt(trinity_dir) -> dict:
    """Stamp the receipt into a newborn's ``.trinity/``.

    Never raises: a birth is not abandoned over a receipt; the caller gets ``error`` to surface."""
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
