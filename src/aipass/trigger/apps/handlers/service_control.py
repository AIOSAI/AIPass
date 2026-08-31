# =================== AIPass ====================
# Name: service_control.py
# Description: systemd unit lifecycle for the trigger log watcher
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""The systemd user unit behind the log watcher, and nothing else.

Extracted from ``modules/medic.py`` 2026-08-31. medic.py had grown to 599 lines
— two hundred past the point the standard asks you to split by domain — and it
was carrying two unrelated jobs: the medic CLI (on/off/status/mute) and the
management of a systemd unit. This is the second one. It is a handler because
installing a unit file and shelling out to systemctl is an implementation
detail; which branch is muted is not.

Every name here is imported back into medic under its original spelling, so
``patch.object(medic, "_systemctl", ...)`` in the suite still binds the symbol
medic's own code resolves. The move is a move: no behaviour changed with it.
"""

import os
import subprocess
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.repo_root import find_repo_root

MODULE_NAME = "service_control"

SERVICE_NAME = "trigger-log-watcher.service"
_SERVICE_UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME
_TEMPLATE_PATH = TRIGGER_ROOT / "templates" / f"{SERVICE_NAME}.template"


def _get_aipass_home() -> Path:
    """Resolve AIPASS_HOME from env var or git repo root."""
    env = os.environ.get("AIPASS_HOME")
    if env:
        return Path(env)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception as exc:
        logger.warning("[MEDIC] git repo root detection failed: %s", exc)
    return find_repo_root(caller="medic")


def _ensure_service_installed() -> bool:
    """Install systemd unit from template if missing. Returns True if ready."""
    if _SERVICE_UNIT_PATH.exists():
        return True

    if not _TEMPLATE_PATH.exists():
        logger.warning("[MEDIC] Service template not found: %s", _TEMPLATE_PATH)
        return False

    aipass_home = _get_aipass_home()
    from aipass.trigger.apps.config import read_text_file, write_text_file

    template = read_text_file(_TEMPLATE_PATH)
    rendered = template.replace("{{AIPASS_HOME}}", str(aipass_home))

    write_text_file(_SERVICE_UNIT_PATH, rendered)
    logger.info("[MEDIC] Installed systemd unit to %s", _SERVICE_UNIT_PATH)
    json_handler.log_operation(
        "systemd_unit_installed",
        {"unit": str(_SERVICE_UNIT_PATH), "aipass_home": str(aipass_home)},
        module_name=MODULE_NAME,
    )

    _systemctl("daemon-reload")
    subprocess.run(
        ["systemctl", "--user", "enable", SERVICE_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return True


def _systemctl(action: str) -> bool:
    """Run systemctl --user action on the log watcher service.

    Args:
        action: systemctl action (start, stop, restart, is-active)

    Returns:
        True if command succeeded (exit code 0)
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", action, SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.warning(f"[MEDIC] systemctl {action} failed: {exc}")
        return False


def _is_service_active() -> bool:
    """Check if the log watcher systemd service is running."""
    return _systemctl("is-active")
