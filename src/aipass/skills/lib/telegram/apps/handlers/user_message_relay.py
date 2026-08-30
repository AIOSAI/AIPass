# =================== AIPass ====================
# Name: user_message_relay.py
# Description: Relay user messages from non-TG doors to the branch TG chat
# Version: 1.5.0
# Created: 2026-07-14
# Modified: 2026-08-28
# =============================================

"""
User message relay — posts user messages from non-TG doors to the branch TG chat.

UserPromptSubmit hook handler. When a user types in terminal or remote, their
message is posted to the branch's Telegram chat so the chat reads like the full
conversation. TG-origin messages are skipped (already visible in chat).

Registration: @hooks adds this to .aipass/hooks.json + ~/.claude/settings.json.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from aipass.prax import logger


MIRROR_DIR = Path.home() / ".aipass" / "telegram_bots"
PENDING_DIR = Path.home() / ".aipass" / "telegram_pending"
TG_ORIGIN_MARKER = "via Telegram:"
TELEGRAM_MAX_LENGTH = 4096

# Dispatch-wake detection: AIPASS_SESSION_TYPE env var ("dispatched"/"daemon") is
# session-wide, not per-prompt — a dispatched session can still receive genuine
# user input mid-flight. No per-prompt structural indicator exists in hook_data
# (confirmed by inspecting all handlers + hook_test.py mock payloads). Fallback:
# match the known automated wake-prompt prefix.
_DISPATCH_WAKE_PREFIX = "Hi. Check inbox, process new emails"

_last_relay_hash: str = ""

_SKILL_NAME = "telegram"


def _relay_is_switched_off() -> bool:
    """Report whether the telegram skill is switched OFF for this relay.

    The third door (APLAN-0016, S115). The off-switch has two gates already —
    systemd masking, and the one inside run_skill — and both hold. Neither is on
    THIS path: the hooks bridge invokes this file by its file path, so run_skill
    is never entered and its gate is never consulted. Without this check a skill
    that `drone @skills switch` reports as OFF still sends on every prompt;
    measured at 508 relayed user messages in the ten days after telegram was
    switched off on 2026-08-18.

    Fails CLOSED, deliberately. Unreadable state, an unimportable switch handler,
    any error at all is treated as OFF. Answering "cannot tell" with a send
    resurrects exactly the traffic an operator deliberately stopped — which is
    the same defect this function exists to close.

    Returns:
        bool: True when nothing may be sent.
    """
    try:
        from aipass.skills.apps.handlers.switch_handler import is_enabled

        return not is_enabled(_SKILL_NAME)
    except Exception as exc:
        logger.warning("[TG] relay gate cannot read the skills switch, staying silent: %s", exc)
        return True


def _try_load_bot(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or not data.get("bot_token"):
        return None
    if data.get("chat_id"):
        return data
    # Telegram private chats: chat.id == the user's numeric ID. Safe fallback
    # only when there's exactly one authorized user (every bot in this fleet) —
    # config shadow files don't get chat_id back-filled after first contact.
    allowed = data.get("allowed_user_ids")
    if isinstance(allowed, list) and len(allowed) == 1:
        return {**data, "chat_id": allowed[0]}
    return None


def _find_in_dir(search_dir: Path, pattern: str, cwd_path: Path) -> dict | None:
    if not search_dir.exists():
        return None
    for bot_file in sorted(search_dir.glob(pattern)):
        data = _try_load_bot(bot_file)
        if not data or not data.get("work_dir"):
            continue
        try:
            cwd_path.relative_to(Path(data["work_dir"]))
            return data
        except ValueError:
            continue
    return None


def find_bot_for_cwd(cwd: str) -> dict | None:
    """Find a mirror/pending bot file whose work_dir contains the given CWD.

    MIRROR_DIR configs are the bot_factory.py shadow files, named
    {bot_id}.json. PENDING_DIR files keep the older bot-{bot_id}.json naming
    (transcript-relay stream state) — the two directories use different
    conventions, so they're searched with different glob patterns.
    """
    cwd_path = Path(cwd)

    env_bot_id = os.environ.get("AIPASS_BOT_ID")
    if env_bot_id:
        data = _try_load_bot(MIRROR_DIR / f"{env_bot_id}.json")
        if data:
            return data
        data = _try_load_bot(PENDING_DIR / f"bot-{env_bot_id}.json")
        if data:
            return data

    return _find_in_dir(MIRROR_DIR, "*.json", cwd_path) or _find_in_dir(PENDING_DIR, "bot-*.json", cwd_path)


def send_user_message(bot_token: str, chat_id: int, text: str, origin: str = "\U0001f5a5️") -> bool:
    """Post a user message to the TG chat with origin tag."""
    formatted = f"{origin}\n{text}"
    if len(formatted) > TELEGRAM_MAX_LENGTH:
        formatted = formatted[:TELEGRAM_MAX_LENGTH]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": formatted,
            "disable_notification": True,
        }
    ).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except (URLError, Exception) as e:
        logger.warning("[TG] user message relay send failed: %s", e)
        return False


_PENDING_TTL = 120


def _is_pending_tg_message(prompt: str, bot_data: dict) -> bool:
    """Check if prompt matches a fresh pending TG injection for this bot."""
    bot_id = bot_data.get("bot_id")
    if not bot_id:
        return False
    pending_path = PENDING_DIR / f"bot-{bot_id}.json"
    if not pending_path.exists():
        return False
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if pending.get("delivered"):
        return False
    ts = pending.get("timestamp", 0)
    if time.time() - ts > _PENDING_TTL:
        return False
    return pending.get("injected_prompt", "") == prompt


def _is_system_noise(prompt: str) -> bool:
    """Detect non-human system noise that should not be mirrored to TG."""
    if prompt.startswith("[SYSTEM NOTIFICATION"):
        return True
    if "<task-notification>" in prompt:
        return True
    if "<command-name>" in prompt or "<local-command-stdout>" in prompt:
        return True
    if "messages below were generated by the user while running local commands" in prompt:
        return True
    if prompt.startswith(_DISPATCH_WAKE_PREFIX):
        return True
    return False


def handle(hook_data: dict) -> dict:
    """UserPromptSubmit hook handler — relay user message to branch TG chat.

    Skips: a switched-off telegram skill (checked first, fails closed),
    identified subagents (non-empty agent_id), system noise (notifications,
    local-command output, dispatch wakes), TG-origin messages, duplicate
    consecutive messages, and branches with no TG bot configured.
    """
    global _last_relay_hash  # noqa: PLW0603
    try:
        # The switch gate comes first, before any other consideration: a skill
        # that is switched off does no work at all on this path, not even the
        # cheap checks below.
        if _relay_is_switched_off():
            return {"stdout": "", "exit_code": 0}

        # agent_type is NOT a reliable subagent indicator — main branch chats run
        # with agent_type="claude" (--agent claude). Subagents spawned by tools
        # never fire UserPromptSubmit. Defensive: skip only if agent_id is
        # non-empty, which would indicate a future CC subagent prompt route.
        if hook_data.get("agent_id", ""):
            return {"stdout": "", "exit_code": 0}

        prompt = hook_data.get("prompt", "")
        if not prompt or not prompt.strip():
            return {"stdout": "", "exit_code": 0}

        if _is_system_noise(prompt):
            return {"stdout": "", "exit_code": 0}

        if TG_ORIGIN_MARKER in prompt:
            return {"stdout": "", "exit_code": 0}

        msg_hash = hashlib.md5(prompt.encode()).hexdigest()
        if msg_hash == _last_relay_hash:
            return {"stdout": "", "exit_code": 0}

        cwd = hook_data.get("cwd", "") or str(Path.cwd())
        bot_data = find_bot_for_cwd(cwd)
        if not bot_data:
            return {"stdout": "", "exit_code": 0}

        if _is_pending_tg_message(prompt, bot_data):
            return {"stdout": "", "exit_code": 0}

        bot_token = bot_data["bot_token"]
        chat_id = int(bot_data["chat_id"])

        if send_user_message(bot_token, chat_id, prompt):
            _last_relay_hash = msg_hash
            logger.info("[TG] user message relayed to chat_id=%s", chat_id)
            return {"stdout": "", "exit_code": 0, "sound": "user message relay"}

        return {"stdout": "", "exit_code": 0}
    except Exception as e:
        logger.warning("[TG] user message relay error: %s", e)
        return {"stdout": "", "exit_code": 0}
