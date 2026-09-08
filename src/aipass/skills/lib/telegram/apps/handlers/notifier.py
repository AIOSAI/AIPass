# =================== AIPass ====================
# Name: notifier.py
# Description: Telegram Push Notifications via scheduler bot
# Version: 1.1.0
# Created: 2026-02-17
# Modified: 2026-02-18
# =============================================

"""
Telegram notification sender for the scheduler bot.

Can be used two ways:
1. Import (within API branch): send_telegram_notification("message")
2. CLI (cross-branch, no import guard): notifier.py "message"
   Flags: --silent (silent push), --markdown (Markdown parse mode)

Reads bot token and chat_id from the API secrets store via _get_secret.
"""

# Standard library
import json
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

# Logging
from aipass.prax import logger

# JSON handler (seedgo standard)
from aipass.skills.apps.handlers.json import json_handler  # noqa: F401

# Sibling imports
from .config import load_bot_config

# =============================================
# PUBLIC API
# =============================================


def send_telegram_notification(
    message: str,
    silent: bool = False,
    parse_mode: str | None = None,
) -> bool:
    """
    Send a message to Telegram via the scheduler bot.

    Args:
        message: Text to send (plain text or Markdown)
        silent: If True, send as silent notification (no sound on phone)
        parse_mode: Telegram parse mode ("Markdown" or "HTML"). None for plain text.

    Returns:
        True if sent successfully, False otherwise
    """
    # Merged loader, not the raw secret: chat_id is ordinary config and lives
    # in the plain file, only the token comes out of the secret store.
    config = load_bot_config("scheduler")
    bot_token = config.get("bot_token") if config else None
    chat_id = config.get("chat_id") if config else None

    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload_dict: dict[str, object] = {"chat_id": chat_id, "text": message}
    if silent:
        payload_dict["disable_notification"] = True
    if parse_mode:
        payload_dict["parse_mode"] = parse_mode

    data = json.dumps(payload_dict).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            json_handler.log_operation("send_telegram_notification", {"chat_id": chat_id, "silent": silent})
            return result.get("ok", False)
    except (URLError, Exception) as e:
        logger.warning("Failed to send Telegram notification: %s", e)
        return False


# =============================================
# CLI INTERFACE (cross-branch use)
# =============================================

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print('Usage: notifier.py [--silent] [--markdown] "message"')
        print("  --silent    Send as silent notification (no sound)")
        print("  --markdown  Use Telegram Markdown parse mode")
        sys.exit(0)

    silent_flag = "--silent" in args
    markdown_flag = "--markdown" in args
    msg_args = [a for a in args if not a.startswith("--")]

    if not msg_args:
        print("Error: no message provided", file=sys.stderr)
        sys.exit(1)

    msg = " ".join(msg_args)
    mode = "Markdown" if markdown_flag else None
    ok = send_telegram_notification(msg, silent=silent_flag, parse_mode=mode)
    sys.exit(0 if ok else 1)
