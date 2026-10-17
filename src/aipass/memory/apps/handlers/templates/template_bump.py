# =================== AIPass ====================
# Name: template_bump.py
# Description: The gold-template bump site — announces the bump and heals the fleet through the push's gates
# Version: 1.0.1
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Template Bump

The ledger is stamped only by a push that ran and succeeded; no ledger reads as pending.
Reference: docs/templates_and_tabs.md
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.templates import receipt
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parents[3]
_TEMPLATES_DIR = _MEMORY_ROOT / "templates"
LEDGER_NAME = ".template_version.json"

BUMP_EVENT = "trinity_template_bumped"


def _ledger_path() -> Path:
    """The fleet-side bump ledger. A function so tests can point it elsewhere."""
    return _TEMPLATES_DIR / LEDGER_NAME


def gold_versions() -> dict[str, str]:
    """The gold version, via ``receipt.template_versions`` so receipt and bump never disagree."""
    return receipt.template_versions()


def _read_ledger() -> dict[str, Any] | None:
    """The ledger, or None when it is absent or unreadable."""
    path = _ledger_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.error(f"[template_bump] Unreadable ledger at {path}: {exc}")
        return None
    return data if isinstance(data, dict) else None


def bump_pending() -> dict[str, Any]:
    """Whether the gold templates have moved past the last pushed version; no ledger is PENDING."""
    try:
        now = gold_versions()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error(f"[template_bump] Cannot read gold templates: {exc}")
        return {"pending": False, "was": None, "now": {}, "reason": f"gold templates unreadable: {exc}"}

    ledger = _read_ledger()
    was = ledger.get("template_versions") if isinstance(ledger, dict) else None
    if not isinstance(was, dict):
        return {"pending": True, "was": None, "now": now, "reason": "no readable bump ledger — never pushed, or lost"}
    if was == now:
        return {"pending": False, "was": was, "now": now, "reason": "fleet was last pushed at the current version"}
    return {"pending": True, "was": was, "now": now, "reason": "gold templates moved past the last pushed version"}


def _stamp_ledger(versions: dict[str, str]) -> bool:
    """Record that the fleet was pushed at *versions*. Atomic write."""
    path = _ledger_path()
    payload = {
        "template_versions": versions,
        "last_push": datetime.now().isoformat(timespec="seconds"),
        "stamped_by": "memory push",
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.error(f"[template_bump] Failed to stamp ledger {path}: {exc}")
        tmp.unlink(missing_ok=True)
        return False
    return True


def _run_push(dry_run: bool) -> dict[str, Any]:
    """Run the trinity push over the whole fleet, gates intact."""
    from aipass.memory.apps.handlers.templates import trinity_push

    return trinity_push.push(branch=None, dry_run=dry_run)


def on_bump(confirm: bool = False) -> dict[str, Any]:
    """The bump site: heal the fleet through the push, a DRY RUN unless *confirm*.

    The caller announces the outcome on the bus under ``BUMP_EVENT``.
    """
    pending = bump_pending()
    out: dict[str, Any] = {
        "pending": pending["pending"],
        "was": pending["was"],
        "now": pending["now"],
        "reason": pending["reason"],
        "dry_run": not confirm,
        "push": None,
        "stamped": False,
    }

    if not pending["pending"]:
        return out

    result = _run_push(dry_run=not confirm)
    out["push"] = result

    if confirm and isinstance(result, dict) and result.get("success"):
        out["stamped"] = _stamp_ledger(pending["now"])
    elif confirm:
        # A stamp after a refused push would tell the next bump the work was done.
        logger.error("[template_bump] Push did not succeed — ledger deliberately NOT stamped")

    json_handler.log_operation(
        "template_bump",
        {"pending": pending["pending"], "dry_run": not confirm, "stamped": out["stamped"]},
        module_name="template_bump",
    )
    return out


def receipt_status() -> dict[str, Any]:
    """What every branch's receipt says it carries, against the gold source; no receipt lists as None."""
    from aipass.memory.apps.handlers.monitor import registry_scope

    try:
        gold = gold_versions()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error(f"[template_bump] Cannot read gold templates: {exc}")
        gold = {}

    rows = []
    for item in registry_scope.fleet_branches():
        try:
            data = receipt.read_receipt(Path(item["path"]) / ".trinity")
        except receipt.ReceiptUnreadable as exc:
            logger.error(f"[template_bump] {exc}")
            data = None
        carries = data.get("template_versions") if isinstance(data, dict) else None
        rows.append(
            {
                "branch": item["name"],
                "carries": carries if isinstance(carries, dict) else None,
                "current": bool(gold) and carries == gold,
                "stamped": data.get("stamped") if isinstance(data, dict) else None,
                "stamped_by": data.get("stamped_by") if isinstance(data, dict) else None,
            }
        )

    return {"gold": gold, "ledger": _read_ledger(), "branches": rows}
