# =================== AIPass ====================
# Name: temporal.py
# Version: 1.0.0
# Description: Every-turn local date/time/weekday/part-of-day injection (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-21
# Modified: 2026-07-21
# =============================================

"""Tiny always-on temporal grounding line — no cadence gating, fires every
turn. Reads the live clock each fire (no caching) and injects one short line:
weekday, date, 24h time, tz abbreviation, part of day. Timezone comes from
the host system (astimezone()) — never hardcoded, so clones running outside
Vancouver still show their own local time. Keep it to one line — every-turn
cost matters."""

from datetime import datetime

from aipass.prax.apps.modules.logger import system_logger as logger


def _part_of_day(hour: int) -> str:
    """Bucket an hour (0-23) into morning/afternoon/evening/night."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _format_line(now: datetime) -> str:
    weekday = now.strftime("%a")
    date = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    tz = now.strftime("%Z")
    part = _part_of_day(now.hour)
    clock = f"{weekday} {date} {time_str} {tz}" if tz else f"{weekday} {date} {time_str}"
    return f"Temporal: {clock} ({part})"


def handle(hook_data: dict) -> dict:
    """Inject the current local temporal line — every turn, no cadence."""
    try:
        line = _format_line(datetime.now().astimezone())
        return {"stdout": line, "exit_code": 0, "sound": "temporal"}
    except Exception as exc:
        logger.info("[HOOKS] temporal: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
