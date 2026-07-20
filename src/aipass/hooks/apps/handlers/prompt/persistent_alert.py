# =================== AIPass ====================
# Name: persistent_alert.py
# Version: 1.0.1
# Description: Injects advisory banners for active alerts on UserPromptSubmit
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-14
# Modified: 2026-07-14
# =============================================

"""Injects advisory banners for active alerts from .aipass/alerts.json."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

_GUARD_DIR = Path(tempfile.gettempdir())
_MAX_ALERTS_SHOWN = 10


def _find_aipass_dir() -> Path | None:
    """Walk up from CWD; return the nearest .aipass/ that contains alerts.json.

    Every branch has its own .aipass/ (branch prompt), so stopping at the first
    .aipass directory would never reach the project root where alerts.json lives.
    """
    search = Path.cwd()
    home = Path.home()
    while search != home and search.parent != search:
        aipass_dir = search / ".aipass"
        if (aipass_dir / "alerts.json").exists():
            return aipass_dir
        search = search.parent
    return None


def _load_and_clean(alerts_path: Path) -> list[dict]:
    """Load alerts, remove expired, write back if cleaned. Returns active alerts."""
    try:
        data = json.loads(alerts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[HOOKS] persistent_alert: read error: %s", exc)
        return []

    alerts = data.get("alerts", []) if isinstance(data, dict) else []
    if not alerts:
        return []

    now = datetime.now(timezone.utc)
    active = []
    cleaned = False
    for alert in alerts:
        expires = alert.get("expires_at")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt < now:
                    cleaned = True
                    continue
            except (ValueError, TypeError) as exc:
                logger.info("[HOOKS] persistent_alert: bad expires_at: %s", exc)
        active.append(alert)

    if cleaned:
        try:
            alerts_path.write_text(
                json.dumps({"alerts": active}, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.info("[HOOKS] persistent_alert: cleanup write error: %s", exc)

    return active


def _guard_path(session_id: str, alert_id: str) -> Path | None:
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-persistent-alert-{session_id}-{alert_id}"


def _already_announced(session_id: str, alert_id: str) -> bool:
    path = _guard_path(session_id, alert_id)
    return path is not None and path.exists()


def _mark_announced(session_id: str, alert_id: str) -> None:
    path = _guard_path(session_id, alert_id)
    if path is not None:
        try:
            path.touch()
        except OSError as exc:
            logger.info("[HOOKS] persistent_alert: guard write failed: %s", exc)


def _format_banner(alerts: list[dict]) -> str:
    """Format alert banners for prompt injection, capped at _MAX_ALERTS_SHOWN."""
    shown = alerts[:_MAX_ALERTS_SHOWN]
    hidden = len(alerts) - len(shown)

    lines = []
    for alert in shown:
        severity = alert.get("severity", "warning").upper()
        title = alert.get("title", "Untitled alert")
        body = alert.get("body", "")
        source = alert.get("source", "unknown")
        alert_id = alert.get("id", "?")
        lines.append(f"[{severity}] {title} (from @{source}, id: {alert_id})")
        if body:
            lines.append(f"  {body}")
    if hidden > 0:
        lines.append(f"...and {hidden} more (dismiss some to see the rest)")
    header = "# Active Alerts"
    dismiss_hint = "Dismiss with: drone @hooks dismiss <alert-id>"
    return "\n".join([header, ""] + lines + ["", dismiss_hint])


def handle(hook_data: dict) -> dict:
    """Inject advisory banners for active alerts.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (banner or empty) and exit_code.
    """
    aipass_dir = _find_aipass_dir()
    if not aipass_dir:
        return {"stdout": "", "exit_code": 0}

    alerts_path = aipass_dir / "alerts.json"
    if not alerts_path.exists():
        return {"stdout": "", "exit_code": 0}

    alerts = _load_and_clean(alerts_path)
    if not alerts:
        return {"stdout": "", "exit_code": 0}

    banner = _format_banner(alerts)

    session_id = hook_data.get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    new_ids = [a["id"] for a in alerts if a.get("id") and not _already_announced(session_id, a["id"])]
    sound = ""
    if new_ids:
        for alert_id in new_ids:
            _mark_announced(session_id, alert_id)
        count = len(alerts)
        plural = "s" if count != 1 else ""
        sound = f"alert: {count} active alert{plural}"

    json_handler.log_operation("inject_alerts", {"count": len(alerts)})
    logger.info("[HOOKS] persistent_alert: %d active alerts injected", len(alerts))
    result = {"stdout": banner, "exit_code": 0}
    if sound:
        result["sound"] = sound
    return result
