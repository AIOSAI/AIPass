# =================== AIPass ====================
# Name: service_control.py
# Description: systemd unit lifecycle for the trigger log watcher
# Version: 1.3.1
# Created: 2026-08-31
# Modified: 2026-10-24
# =============================================

"""The systemd user unit behind the log watcher, and nothing else.
medic imports these by name, so tests patch medic's bound symbols, not these.
Every systemctl call probes shutil.which first and refuses by name: no systemd is not "failed".
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.repo_root import find_repo_root

MODULE_NAME = "service_control"

SERVICE_NAME = "trigger-log-watcher.service"
_SERVICE_UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME
_TEMPLATE_PATH = TRIGGER_ROOT / "templates" / f"{SERVICE_NAME}.template"

NO_SYSTEMD_REASON = "this host has no systemctl — the log watcher service door needs systemd"


def systemd_available() -> bool:
    """True when this host has a systemctl to talk to."""
    return shutil.which("systemctl") is not None


def get_aipass_home() -> Path:
    """Resolve AIPASS_HOME from env var, else the registry-marker walk (never the cwd's checkout)."""
    env = os.environ.get("AIPASS_HOME")
    return Path(env) if env else find_repo_root(caller="medic")


def ensure_service_installed() -> bool:
    """Install systemd unit from template if missing. Returns True if ready."""
    # Probe before the exists check: a unit file left by another host is not a ready service.
    if shutil.which("systemctl") is None:
        logger.warning("[MEDIC] Service install refused: %s", NO_SYSTEMD_REASON)
        return False

    if _SERVICE_UNIT_PATH.exists():
        return True

    if not _TEMPLATE_PATH.exists():
        logger.warning("[MEDIC] Service template not found: %s", _TEMPLATE_PATH)
        return False

    aipass_home = get_aipass_home()
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

    _run_systemctl("daemon-reload")
    _run_systemctl("enable", SERVICE_NAME)
    return True


def _run_systemctl(*args: str) -> Optional[bool]:
    """Run ``systemctl --user <args>`` and report whether it succeeded.
    Takes the whole argv tail: daemon-reload takes no unit and exits 1 when given one.
    None (systemctl could not be asked) is not False (non-zero exit): a hung is-active is not stopped.
    """
    spelled = " ".join(args)
    try:
        if shutil.which("systemctl") is None:
            raise FileNotFoundError("systemctl is not on PATH")
        result = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except FileNotFoundError as exc:
        logger.warning("[MEDIC] systemctl %s refused: %s (%s)", spelled, NO_SYSTEMD_REASON, exc)
        return None
    except Exception as exc:
        logger.warning(f"[MEDIC] systemctl {spelled} could not be asked: {exc}")
        return None


def systemctl(action: str) -> Optional[bool]:
    """Run a systemctl --user action against the log watcher unit."""
    return _run_systemctl(action, SERVICE_NAME)


def is_service_active() -> Optional[bool]:
    """Check if the log watcher systemd service is running."""
    return systemctl("is-active")
