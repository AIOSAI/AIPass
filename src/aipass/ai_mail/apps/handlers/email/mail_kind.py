# =================== AIPass ====================
# Name: mail_kind.py
# Description: The one source of truth for what kind a mail is
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Mail Kind Handler: decides a mail's kind once, at delivery. Reference: docs/mail_kinds.md"""

import re
from typing import Dict, Optional

from aipass.prax import logger
from aipass.ai_mail.apps.handlers.json import json_handler

MAIL_KINDS = ("medic", "rounds", "job_failed", "notice", "mail")
DEFAULT_KIND = "mail"
URGENT_KINDS = ("medic", "rounds", "job_failed")

NOTICE_PREFIXES = ("dispatch complete:", "command job started:", "command job passed:")
JOB_FAILED_PREFIX = "command job failed:"
MEDIC_SENDER = "@trigger"
_TRIGGER_MACHINE_LANE_TAG = re.compile(r"^\[[A-Z]")
_ROUNDS_WORD = re.compile(r"\brounds\b", re.IGNORECASE)


def classify(sender: str, subject: str, declared: Optional[str] = None) -> str:
    """A mail's kind: the declared one (unknown raises ValueError), else guessed from sender and subject."""
    json_handler.log_operation("classify_mail_kind", {"sender": sender, "declared": declared})
    if declared is not None:
        if declared not in MAIL_KINDS:
            raise ValueError(f"unknown mail kind {declared!r}: one of {', '.join(MAIL_KINDS)}")
        return declared

    subject = str(subject or "").strip()
    lowered = subject.lower()
    if str(sender or "").strip().lower() == MEDIC_SENDER and _TRIGGER_MACHINE_LANE_TAG.match(subject):
        return "medic"
    if lowered.startswith(JOB_FAILED_PREFIX):
        return "job_failed"
    if lowered.startswith(NOTICE_PREFIXES):
        return "notice"
    if not lowered.startswith("re:") and _ROUNDS_WORD.search(subject):
        return "rounds"
    return DEFAULT_KIND


def stored_kind(message: Dict) -> str:
    """The kind of a message already in an inbox; one stored before kinds existed reads as notice or mail."""
    kind = message.get("kind")
    if kind is None:
        return "notice" if str(message.get("subject") or "").strip().lower().startswith(NOTICE_PREFIXES) else "mail"
    if kind not in MAIL_KINDS:
        logger.warning("[mail_kind] message %s stores unknown kind %r: read as mail", message.get("id"), kind)
        return DEFAULT_KIND
    return kind
