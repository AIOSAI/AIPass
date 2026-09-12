# =================== AIPass ====================
# Name: service_control.py
# Description: systemd unit lifecycle for the trigger log watcher
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-09-12
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

SYSTEMD IS A HOST FACT, NOT A GIVEN (2026-09-12, seedgo host_portability).
``systemctl`` exists only where systemd runs: macOS has none, Windows has none,
and a Linux container may have none either. A missing binary raises
FileNotFoundError out of exec, so ``check=False`` does not help — every call
probes with ``shutil.which("systemctl")`` first and refuses BY NAME when the
answer is None. The refusal is the point: a door that reads "failed" where the
truth is "there is no systemd here" sends its caller looking for a broken unit
that was never installed.
"""

import os
import shutil
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

#: Said in one place so the log, the CLI and the tests all quote the same fact.
NO_SYSTEMD_REASON = "this host has no systemctl — the log watcher service door needs systemd"


def systemd_available() -> bool:
    """True when this host has a systemctl to talk to.

    Public on purpose: medic prints the difference between "the unit is
    stopped" and "there is no systemd here", and that is not a distinction a
    caller can make from a False return.
    """
    return shutil.which("systemctl") is not None


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
    """Install systemd unit from template if missing. Returns True if ready.

    The systemd probe comes before the ``exists`` short-circuit: a unit file
    left behind by another host is not a ready service, and answering True for
    one is exactly the assumed-running the standard refuses.
    """
    if shutil.which("systemctl") is None:
        logger.warning("[MEDIC] Service install refused: %s", NO_SYSTEMD_REASON)
        return False

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

    _run_systemctl("daemon-reload")
    _run_systemctl("enable", SERVICE_NAME)
    return True


def _run_systemctl(*args: str) -> bool:
    """Run ``systemctl --user <args>`` and report whether it succeeded.

    Takes the argv tail whole rather than one action, because two of the four
    calls are not unit-scoped: ``daemon-reload`` takes no unit at all, and
    ``systemctl --user daemon-reload trigger-log-watcher.service`` exits 1 with
    "Too many arguments." — measured 2026-09-12 — so the reload that was meant
    to run between installing the unit and enabling it had never run once.

    Args:
        args: the systemctl argv after ``--user``

    Returns:
        True if the command succeeded (exit code 0); False when it failed and
        False when this host has no systemd, each said by name in the log.
    """
    spelled = " ".join(args)
    if shutil.which("systemctl") is None:
        logger.warning("[MEDIC] systemctl %s refused: %s", spelled, NO_SYSTEMD_REASON)
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except FileNotFoundError as exc:
        logger.warning("[MEDIC] systemctl %s refused: %s (%s)", spelled, NO_SYSTEMD_REASON, exc)
        return False
    except Exception as exc:
        logger.warning(f"[MEDIC] systemctl {spelled} failed: {exc}")
        return False


def _systemctl(action: str) -> bool:
    """Run a systemctl --user action against the log watcher unit.

    Args:
        action: unit-scoped systemctl action (start, stop, restart, is-active)

    Returns:
        True if command succeeded (exit code 0)
    """
    return _run_systemctl(action, SERVICE_NAME)


def _is_service_active() -> bool:
    """Check if the log watcher systemd service is running."""
    return _systemctl("is-active")
