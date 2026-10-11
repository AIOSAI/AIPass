# =================== AIPass ====================
# Name: receipt_ops.py
# Description: Birth receipt — stamp .trinity/.template_version.json onto a newborn
# Version: 1.1.1
# Created: 2026-08-27
# Modified: 2026-09-25
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

# @memory's sanctioned lane names — their writer refuses anything else. Spawn
# owns exactly one of them.
STAMPED_BY_BIRTH = "spawn birth"

# @seedgo's lane name for the receipt spawn stamps into a newborn's tests/.
# Their own bump writes "seedgo tests template bump"; this one says who stamped
# it, so a reader can tell a birth stamp from a fleet bump.
STAMPED_BY_SCAFFOLD = "spawn scaffold"

# The gold trinity templates: @memory owns them, @seedgo scores against them.
_GOLD_TEMPLATES = {"local": "LOCAL.template.json", "observations": "OBSERVATIONS.template.json"}

# @seedgo's gold test template (DPLAN-0354): the manifest names the versions and
# the page each branch receives. Same gold-source rule as the trinity receipt —
# read the owner's manifest, never a copy of it held here.
_TEST_TEMPLATE_MANIFEST = "templates.json"


def _gold_dir() -> Path:
    """Directory holding the fleet's gold trinity templates."""
    return Path(__file__).resolve().parents[3] / "memory" / "templates"


def _seedgo_templates_dir() -> Path:
    """Directory holding @seedgo's gold test template and its manifest.

    Resolved at the call, never at import: resolve() reads the working
    directory, and importing this module must not touch the filesystem.
    """
    return Path(__file__).resolve().parents[3] / "seedgo" / "templates"


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


def seedgo_test_template() -> tuple:
    """Read @seedgo's gold test template manifest.

    Returns:
        Tuple of (versions, pages): the ``template_versions`` dict to copy into
        the receipt, and a list of ``(source_path, distributed_name)`` pairs for
        the pages a newborn receives.

    Raises:
        ValueError: the manifest is missing, unparseable, carries no usable
            ``template_versions``, or names a page that cannot be read. All of
            it or none of it — a receipt stamped against a half-read manifest
            would claim a version the newborn does not carry.
    """
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
    """Stamp @seedgo's test template receipt into a newborn's ``tests/`` (DPLAN-0354).

    The same shape as the trinity receipt one step over: read the owner's gold
    manifest, copy the versions it publishes, stamp who did it and when, and
    hand the newborn the page itself. Three keys, no more — @seedgo's own bump
    writes the same three.

    Args:
        tests_dir: The newborn's ``tests`` directory.

    Returns:
        Dict with ``success`` and either ``receipt``/``path``/``pages`` or
        ``error``. Never raises: a birth is not abandoned over a receipt, but
        the caller is told so it can surface the miss rather than swallow it.
        A manifest that cannot be read leaves NO receipt behind — an absent
        receipt reads as unstamped, which is true; an empty one would read as
        stamped against nothing.
    """
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
