# =================== AIPass ====================
# Name: admin_lane.py
# Description: Admin-lane state reporting for doctor — read-only, never a verdict
# Version: 1.0.2
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""Admin-lane state for ``aipass doctor`` (DPLAN-0319 train, the owner's ruling).

Reports presence, never validity: the verdict's one home is ``drone @devpulse admin_grant verify``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.shared.registry_discovery import find_registry as _discover_registry

from aipass.aipass.apps.handlers.ui.progress import GLYPH_PASS

_LABEL = "admin lane"
_MODULE_NAME = "admin_lane"

#: Not a parameter: admin is bolted to devpulse and no transfer ceremony exists.
ADMIN_HOLDER = "devpulse"

#: Per-machine signing key. Lives outside every repo, so a clone never gets it.
KEY_PATH = Path.home() / ".aipass" / "admin_grant.key"

#: Doctor names the doc, never the ceremony commands: lighting the lane is a human decision.
DOC_HINT = "Optional — see aipass/docs/admin_setup.md"


def _registry_path() -> Path | None:
    """Locate the root ``*_REGISTRY.json``, or None."""
    branch_root = Path(__file__).resolve().parents[2]
    result = _discover_registry(package_root=str(branch_root))
    return result if result is not None and result.exists() else None


class _Unreadable(Exception):
    """A registry or cert that exists but could not be read; the message names the file."""


def _read_json(path: Path) -> dict | None:
    """Read a JSON object from *path*; None when absent, _Unreadable when unreadable.

    Unreadable raises so the row can name it; None would report its legs as missing.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[admin_lane] could not read %s: %s", path, exc)
        raise _Unreadable(str(path)) from exc
    return data if isinstance(data, dict) else None


def _holder_entry() -> dict | None:
    """Return the registry entry for the admin holder, or None."""
    reg_path = _registry_path()
    if reg_path is None:
        return None
    data = _read_json(reg_path)
    if data is None:
        return None
    branches = data.get("branches")
    if not isinstance(branches, list):
        return None
    for entry in branches:
        if isinstance(entry, dict) and str(entry.get("name", "")).lower() == ADMIN_HOLDER:
            return entry
    return None


def _holder_cert() -> dict | None:
    """Read the admin holder's birth certificate, resolved via the registry."""
    entry = _holder_entry()
    if entry is None:
        return None
    raw_path = entry.get("path")
    if not raw_path:
        return None
    return _read_json(Path(str(raw_path)) / "artifacts" / "birth_certificate.json")


def admin_lane_state() -> dict:
    """Observe the three lane facts. Returns a dict, prints nothing.

    ``state`` is lit (all present), dark (none) or partial; an ``unreadable`` file's
    facts count as absent.
    """
    key = KEY_PATH.is_file()
    unreadable: List[str] = []

    try:
        cert = _holder_cert()
    except _Unreadable as exc:
        cert = None
        unreadable.append(str(exc))
    privileges = cert.get("privileges") if cert else None
    granted = isinstance(privileges, dict) and privileges.get("admin") is True
    signed = bool(cert and cert.get("signature"))

    try:
        entry = _holder_entry()
    except _Unreadable as exc:
        # Already named above by _holder_cert; caught so a second read never crashes.
        logger.info("[admin_lane] registry already named unreadable: %s", exc)
        entry = None
    registry_flag = bool(entry and entry.get("admin") is True)

    facts = (key, granted, signed, registry_flag)
    if all(facts):
        state = "lit"
    elif not any(facts):
        state = "dark"
    else:
        state = "partial"

    return {
        "key": key,
        "granted": granted,
        "signed": signed,
        "registry_flag": registry_flag,
        "state": state,
        "unreadable": unreadable,
    }


def _missing_legs(status: dict) -> str:
    """Name the absent facts for a partial lane, in ceremony order."""
    order = (("key", "key"), ("granted", "grant"), ("signed", "signature"), ("registry_flag", "registry flag"))
    return ", ".join(label for field, label in order if not status[field])


def check_admin_lane() -> List[Tuple[str, str, str, str]]:
    """Doctor row for the admin lane — informational, never an error (a dark lane fails closed)."""
    status = admin_lane_state()
    state = status["state"]

    if state == "lit":
        detail = f"lit — {ADMIN_HOLDER} holds a signed grant on this machine"
        remediation = f"Authoritative check: drone @{ADMIN_HOLDER} admin_grant verify"
    elif state == "dark":
        detail = "dark — no admin grant on this machine (valid; admin actions refuse)"
        remediation = DOC_HINT
    else:
        detail = f"partial — ceremony incomplete, missing: {_missing_legs(status)}"
        remediation = DOC_HINT
    if status["unreadable"]:
        detail = f"{detail}; could not read: {', '.join(status['unreadable'])}"

    logger.info("[admin_lane] state=%s", state)
    # Facts only: never key material, never the certificate's signature value.
    json_handler.log_operation(
        "check_admin_lane",
        data={k: v for k, v in status.items()},
        module_name=_MODULE_NAME,
    )
    return [(_LABEL, GLYPH_PASS, detail, remediation)]
