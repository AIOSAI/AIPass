# =================== AIPass ====================
# Name: telegram_readiness.py
# Description: Report BotFather automation readiness on Telegram host machines
# Version: 1.0.0
# Created: 2026-08-07
# Modified: 2026-08-07
# =============================================

"""telegram_readiness — surface BotFather automation gaps at doctor time.

`/create chat <branch>` drives @BotFather automatically when the optional
`telegram` extra is installed and authenticated. Without it the flow still
works — base_bot falls back to a manual token paste and says so in the chat
— so a gap here is a convenience warning, never an error.

The check stays silent on machines that host no Telegram bots: a plain
AIPass install has no reason to be nagged about an opt-in extra.

Mirrors the prerequisite order of the authoritative runtime check in
skills/lib/telegram/.../botfather_client.py check_telethon_setup(), and
reports the first blocking gap. Cross-branch handler imports are barred,
so the conditions are re-derived here rather than imported.

Existence-only: a passing result means the prerequisites are present, not
that the credentials parse or that the session is still authorized — both
need a live MTProto connect and cannot be proven offline.
"""

from __future__ import annotations

import importlib.util
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

_MODULE_NAME = "telegram_readiness"

# Re-declared rather than imported from ui.progress — handlers do not import
# each other (seedgo handlers rule). Mirrors provider_reconcile.py:23-24.
GLYPH_PASS = "[green]✓[/green]"
GLYPH_WARN = "[yellow]![/yellow]"

# Stable literal — doctor splices rows by exact label match.
_LABEL = "telegram automation"

# "\[" escapes the bracket for Rich — an unescaped [telegram] is parsed as markup and vanishes.
_INSTALL_HINT = "Optional — /create still works via manual token paste. Enable: pip install -e '.\\[telegram]'"
_CREDS_HINT = 'Run: drone @api set-secret telegram telethon_config \'{"api_id": ..., "api_hash": "..."}\''
_AUTH_HINT = "One-time phone auth — run src/aipass/skills/lib/telegram/telethon_auth.py"


def _telethon_version() -> str | None:
    """Return the installed telethon version, or None when absent.

    Uses find_spec so telethon is never actually imported — a health check
    should not pay its import cost or trigger its side effects.

    Returns:
        Version string, "installed" when metadata is unavailable, else None.
    """
    try:
        spec = importlib.util.find_spec("telethon")
    except (ImportError, ValueError, ModuleNotFoundError) as exc:
        logger.info("telethon spec lookup failed: %s", exc)
        return None

    if spec is None:
        return None

    try:
        return version("telethon")
    except PackageNotFoundError:
        logger.info("telethon importable but has no distribution metadata")
        return "installed"


def check_telegram_readiness() -> list:
    """Report BotFather automation readiness for this machine.

    Returns:
        List of (label, glyph, detail, remediation) tuples matching
        doctor.CheckResult's shape — plain tuples avoid a circular import.
        Empty when this machine hosts no Telegram bots.
    """
    results: list = []

    bot_config_dir = Path.home() / ".aipass" / "telegram_bots"
    if not bot_config_dir.is_dir() or not any(bot_config_dir.glob("*.json")):
        json_handler.log_operation(
            "check_telegram_readiness",
            data={"skipped": "no telegram bots configured"},
            module_name=_MODULE_NAME,
        )
        return results

    secrets_dir = Path.home() / ".secrets" / "aipass" / "telegram"
    config_file = secrets_dir / "telethon_config.json"
    # Telethon appends ".session" to the configured session stem (".telethon").
    session_file = secrets_dir / ".telethon.session"

    telethon_version = _telethon_version()
    has_config = config_file.exists()
    has_session = session_file.exists()

    if telethon_version is None:
        results.append((_LABEL, GLYPH_WARN, "telethon not installed", _INSTALL_HINT))
    elif not has_config:
        results.append((_LABEL, GLYPH_WARN, "credentials not set", _CREDS_HINT))
    elif not has_session:
        results.append((_LABEL, GLYPH_WARN, f"telethon {telethon_version}, not authenticated", _AUTH_HINT))
    else:
        results.append((_LABEL, GLYPH_PASS, f"BotFather prerequisites present (telethon {telethon_version})", ""))

    logger.info(
        "[doctor] telegram readiness: telethon=%s config=%s session=%s",
        telethon_version or "missing",
        has_config,
        has_session,
    )
    json_handler.log_operation(
        "check_telegram_readiness",
        data={"telethon": telethon_version or "missing", "config": has_config, "session": has_session},
        module_name=_MODULE_NAME,
    )

    return results
