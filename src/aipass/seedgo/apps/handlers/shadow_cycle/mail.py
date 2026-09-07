# =================== AIPass ====================
# Name: mail.py
# Description: hand the cycle summary to ai_mail through drone - email, never a dispatch
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-09-02
# =============================================

"""
EMAIL, NEVER DISPATCH. A weekly measurement is FYI: the recipient reads it when
they next look at their inbox. `drone @ai_mail dispatch` would WAKE a citizen at
whatever hour the daemon fired, for a report that will still be true in the
morning. The verb this handler calls is `email`, and the distinction is the
whole reason the handler exists rather than a raw subprocess line in the module.

WHY `drone` AND NOT AN IMPORT. ai_mail resolves the SENDER from the working
directory - it walks up looking for `.trinity/passport.json` - so a send has to
be made from inside the branch that is sending it. `cwd=SEEDGO_ROOT` is what
makes this mail arrive from @seedgo rather than from wherever a daemon happened
to start the process; @aipass's ping sweep learned the same lesson and the same
cure. Going through drone also means the address resolution that finds a
recipient is ai_mail's own, not a second copy living here.

A FAILED SEND IS REPORTED, NEVER RAISED. The three measurement passes have
already run and their artifacts are already on disk by the time this is called.
Losing the whole cycle because a mail daemon was down would throw away twenty
minutes of fleet measurement to protect a notification.
"""

import subprocess
from pathlib import Path
from typing import Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

MODULE_NAME = "shadow_cycle.mail"

#: The branch this mail is sent FROM - the directory ai_mail reads the sender's
#: passport out of.
SEEDGO_ROOT = module_file(__file__).parents[3]

#: The command, up to the arguments. `email` is deliberate: see the module
#: docstring - `dispatch` would wake the recipient.
MAIL_COMMAND: tuple = ("drone", "@ai_mail", "email")

#: Seconds a send may take. Generous for a local queue write, and finite so a
#: hung mail daemon cannot hold a scheduled cycle open forever.
SEND_TIMEOUT = 60


def send(recipient: str, subject: str, body: str, cwd: Optional[Path] = None) -> bool:
    """Email one branch. Returns True when drone accepted it, False otherwise.

    Args:
        recipient: The `@branch` address to deliver to.
        subject: One line, already summarised.
        body: The one-screen text. Paths, never reports.
        cwd: The directory the send is made from, i.e. whose passport names the
            sender. Defaults to this branch's root.

    Returns:
        True if drone exited zero.
    """
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

    warning, not error: every artifact the cycle measured is already published,
    so an undelivered notification degrades the run - it does not fail it.
    """
    logger.warning(f"[SHADOW_CYCLE] could not email {recipient}: {reason}")
    json_handler.log_operation(
        "shadow_cycle_mail_failed",
        {"recipient": recipient, "reason": reason},
        module_name=MODULE_NAME,
    )
    return False
