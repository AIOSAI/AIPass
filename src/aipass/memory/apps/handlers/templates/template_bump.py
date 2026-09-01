# =================== AIPass ====================
# Name: template_bump.py
# Description: The gold-template bump site — announces the bump and heals the fleet through the push's gates
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Template Bump

When the gold-source templates change version, every branch's memory files
are carrying an older structure.  This module is the BUMP SITE: the one place
that notices, announces it on the event bus, and heals the fleet by running
the trinity push.

TRIGGER-DRIVEN, NEVER A DAEMON
------------------------------
Nothing here watches anything.  ``bump_pending()`` is a comparison between two
files that are already on disk — the gold templates and the bump ledger — and
it only runs when somebody invokes the lane.  There is no timer, no poller and
no background process; idle costs nothing, which is the law of the marker.

The bump is ANNOUNCED as well as acted on, but not from here: this handler
owns the NAME of the event (``BUMP_EVENT``) and the module layer does the
firing.  Reaching @trigger's bus means importing ``trigger.apps.modules``, and
a handler that imports another branch's module layer is orchestration wearing
domain-logic clothes — @seedgo's audit says so and it is right.  The name lives
with the fact it describes; the announcement lives with the caller.

THE GATES STAY ON
-----------------
A bump runs the push as a DRY RUN by default and prints the report.  It would
be trivial to make a version bump rewrite 22 branches' memory files
automatically, and that is precisely the fleet-wide unprompted write that
``--confirm`` exists to prevent — this branch has already performed one of
those by accident and it is the reason the push has gates at all.  Self-healing
that no operator has read is not healing, it is an unattended fleet write with
better branding.  ``--confirm`` runs it for real; everything downstream (the
vectorize-verify-prune order, the receipts, the todo exemption) is the push's
own machinery, untouched.

THE LEDGER
----------
``memory/templates/.template_version.json`` records which gold version the
fleet was last pushed at.  It is stamped ONLY by a push that actually ran and
actually succeeded: a dry-run that stamped it would tell the next bump the
work was already done, and a failed push that stamped it would do the same
while leaving the fleet stale.  No ledger at all reads as "bump pending",
never as "nothing to do" — absent and up-to-date are opposite answers.

Not to be confused with a branch's own ``.trinity/.template_version.json``
receipt, which records what THAT branch carries. This one is fleet-side.
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
    """The structural version the gold templates currently carry.

    Reuses ``receipt.template_versions`` — the receipt writer and the bump
    detector must never disagree about what "the current version" is, and two
    readers of the same field is exactly how they would.
    """
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
    """Whether the gold templates have moved past the last pushed version.

    Returns:
        ``{"pending": bool, "was": dict | None, "now": dict, "reason": str}``.
        ``was`` is None when there is no readable ledger, which counts as
        PENDING: a missing record of a push is not a record of a push.
    """
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
    """The bump site: announce, then heal the fleet through the push.

    Args:
        confirm: False (default) runs the push as a DRY RUN and writes
            nothing anywhere. True executes it and, only on success, stamps
            the ledger.

    Returns:
        ``{"pending", "was", "now", "dry_run", "push", "stamped", "reason"}``.
        ``push`` is None when there was no bump to act on. The caller announces
        this outcome on the bus under ``BUMP_EVENT``.
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
        # A ledger stamped after a refused push would tell the NEXT bump the
        # work was done, and the fleet would stay stale with a clean record.
        logger.error("[template_bump] Push did not succeed — ledger deliberately NOT stamped")

    json_handler.log_operation(
        "template_bump",
        {"pending": pending["pending"], "dry_run": not confirm, "stamped": out["stamped"]},
        module_name="template_bump",
    )
    return out


def receipt_status() -> dict[str, Any]:
    """What every branch's receipt says it carries, against the gold source.

    This replaces the old ``template-status``, which read the fleet-side push
    log and reported a date only the retired pre-``.trinity`` lane could ever
    have moved.  The per-branch receipts are written by lanes that are alive,
    so this answers the question the verb always claimed to: *who actually
    carries the current standard?*

    Returns:
        ``{"gold", "ledger", "branches": [{"branch", "carries", "current",
        "stamped", "stamped_by"}]}``. A branch with no receipt is listed with
        ``carries: None`` — absent is an answer, not an omission.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope

    try:
        gold = gold_versions()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error(f"[template_bump] Cannot read gold templates: {exc}")
        gold = {}

    rows = []
    for item in registry_scope.fleet_branches():
        data = receipt.read_receipt(Path(item["path"]) / ".trinity")
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
