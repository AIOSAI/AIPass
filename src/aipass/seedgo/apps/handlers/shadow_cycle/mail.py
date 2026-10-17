# =================== AIPass ====================
# Name: mail.py
# Description: hand the cycle summary to ai_mail through drone - email, never a dispatch
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-10-17
# =============================================

"""
EMAIL, NEVER DISPATCH. A weekly measurement is FYI: the recipient reads it when
they next look; `dispatch` would wake a citizen. A failed send is reported, never raised."""

import subprocess
from pathlib import Path
from typing import Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

MODULE_NAME = "shadow_cycle.mail"

#: ai_mail reads the sender's passport from the cwd, so the send runs from here.
SEEDGO_ROOT = module_file(__file__).parents[3]

MAIL_COMMAND: tuple = ("drone", "@ai_mail", "email")

SEND_TIMEOUT = 60


def send(recipient: str, subject: str, body: str, cwd: Optional[Path] = None) -> bool:
    """Email one branch. Returns True when drone accepted it, False otherwise."""
    command = [*MAIL_COMMAND, recipient, subject, body]
    working = str(cwd or SEEDGO_ROOT)

    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=SEND_TIMEOUT, cwd=working)
    except FileNotFoundError as exc:
        return _failed(recipient, f"drone is not on PATH: {exc}")
    except (OSError, subprocess.SubprocessError) as exc:
        return _failed(recipient, f"{type(exc).__name__}: {exc}")

    if completed.returncode != 0:
        return _failed(recipient, f"drone exited {completed.returncode}: {completed.stderr.strip()[:300]}")

    json_handler.log_operation(
        "shadow_cycle_mailed",
        {"recipient": recipient, "subject": subject, "characters": len(body)},
        module_name=MODULE_NAME,
    )
    logger.info(f"[SHADOW_CYCLE] cycle summary emailed to {recipient}")
    return True


def _failed(recipient: str, reason: str) -> bool:
    """Record a send that did not happen, and answer False.

    Warning, not error: the cycle's artifacts are already published."""
    logger.warning(f"[SHADOW_CYCLE] could not email {recipient}: {reason}")
    json_handler.log_operation(
        "shadow_cycle_mail_failed",
        {"recipient": recipient, "reason": reason},
        module_name=MODULE_NAME,
    )
    return False
