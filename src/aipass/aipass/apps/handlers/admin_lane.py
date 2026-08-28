# =================== AIPass ====================
# Name: admin_lane.py
# Description: Admin-lane state reporting for doctor — read-only, never a verdict
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Admin-lane state for ``aipass doctor`` (DPLAN-0319 train, Patrick's ruling).

Reports whether this machine's admin lane is LIT or DARK, and nothing more.

WHY THIS ONLY REPORTS PRESENCE, NEVER VALIDITY
----------------------------------------------
The admin grant is a signed contract with five legs (@devpulse's
``admin_grant.py`` is its single reference implementation, FPLAN-0401):
verified caller · cert path from the registry · cert content · HMAC-SHA256
signature · registry ``admin: true``. Only devpulse can pass leg 1, and the
signature check needs the key.

This module deliberately does NOT re-implement any of that. It observes three
cheap, non-secret FACTS — key file present, cert carries a privileges block and
a signature, registry entry carries ``admin: true`` — and reports them as lane
state. A doctor that re-derived the verdict would be a second implementation of
a security contract, free to drift from the real one and to disagree with it in
the direction that matters. The authoritative answer has one home and doctor
points at it: ``drone @devpulse admin_grant verify``.

Nothing here reads key MATERIAL — only whether the file exists. No cross-branch
import: devpulse owns that module, and an importer of it would make every
consumer share its import graph.

A DARK LANE IS A VALID INSTALL. AIPass runs fine with no admin grant; admin
actions simply refuse (fail closed). So this never reports an error and never
pushes the ceremony — it names the doc and stops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.shared.registry_discovery import find_registry as _discover_registry

# Doctor's glyph vocabulary. Imported rather than redefined so a glyph change
# in the UI handler cannot leave this row rendering in a stale style.
from aipass.aipass.apps.handlers.ui.progress import GLYPH_PASS

_LABEL = "admin lane"
_MODULE_NAME = "admin_lane"

#: The one seat. Not parameterizable — admin is bolted to devpulse by ruling
#: (DPLAN-0288), and there is no transfer ceremony to make this a variable.
ADMIN_HOLDER = "devpulse"

#: Per-machine signing key. Lives outside every repo, so a clone never gets it.
KEY_PATH = Path.home() / ".aipass" / "admin_grant.key"

#: Where the human-facing ceremony is written down. Doctor names this, never
#: the ceremony commands themselves — lighting the lane is a human decision.
DOC_HINT = "Optional — see aipass/docs/admin_setup.md"


def _registry_path() -> Path | None:
    """Locate the root ``*_REGISTRY.json``, or None."""
    branch_root = Path(__file__).resolve().parents[2]
    result = _discover_registry(package_root=str(branch_root))
    return result if result.exists() else None


def _read_json(path: Path) -> dict | None:
    """Read a JSON object from *path*; None when absent or unreadable.

    Loud on a real read failure, quiet on absence: a missing cert is the
    ordinary fresh-install state, an unparseable one is worth a log line.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[admin_lane] could not read %s: %s", path, exc)
        return None
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
    """Read the admin holder's birth certificate, resolved via the registry.

    The path comes from the registry entry, never from a guess about layout —
    the same rule the real contract's leg 2 follows.
    """
    entry = _holder_entry()
    if entry is None:
        return None
    raw_path = entry.get("path")
    if not raw_path:
        return None
    return _read_json(Path(str(raw_path)) / "artifacts" / "birth_certificate.json")


def admin_lane_state() -> dict:
    """Observe the three lane facts. Returns a dict, prints nothing.

    Returns:
        ``{"key": bool, "granted": bool, "signed": bool, "registry_flag": bool,
        "state": "lit" | "dark" | "partial"}``

        - ``lit``     — all three facts present (verify still belongs to devpulse)
        - ``dark``    — none present; the ordinary fresh-install state
        - ``partial`` — some present: a half-run ceremony, worth naming
    """
    key = KEY_PATH.is_file()

    cert = _holder_cert()
    privileges = cert.get("privileges") if cert else None
    granted = isinstance(privileges, dict) and privileges.get("admin") is True
    signed = bool(cert and cert.get("signature"))

    entry = _holder_entry()
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
    }


def _missing_legs(status: dict) -> str:
    """Name the absent facts for a partial lane, in ceremony order."""
    order = (("key", "key"), ("granted", "grant"), ("signed", "signature"), ("registry_flag", "registry flag"))
    return ", ".join(label for field, label in order if not status[field])


def check_admin_lane() -> List[Tuple[str, str, str, str]]:
    """Doctor row for the admin lane — informational, never an error.

    Always GLYPH_PASS: a dark lane is a correct, fail-closed install, and a lit
    one is equally fine. Doctor's job here is to end the silence, not to grade.
    The remediation column names the DOC, never a ceremony command.

    Returns:
        One ``(label, glyph, detail, remediation)`` tuple, doctor's row shape.
    """
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

    logger.info("[admin_lane] state=%s", state)
    # Facts only — the audit trail records WHICH legs were observed, never key
    # material and never the certificate's signature value.
    json_handler.log_operation(
        "check_admin_lane",
        data={k: v for k, v in status.items()},
        module_name=_MODULE_NAME,
    )
    return [(_LABEL, GLYPH_PASS, detail, remediation)]
