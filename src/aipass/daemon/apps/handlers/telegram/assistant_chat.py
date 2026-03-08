
# ===================AIPASS====================
# META DATA HEADER
# Name: assistant_chat.py - Daemon Bot Telegram Launcher
# Date: 2026-02-15
# Version: 2.0.0
# Category: daemon/handlers/telegram
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-02-15): Thin launcher - delegates to shared direct_chat.py
#   - v1.1.0 (2026-02-15): Photo/document support (archived)
#   - v1.0.0 (2026-02-15): Initial long-polling + tmux bridge (archived)
#
# CODE STANDARDS:
#   - Thin launcher only - all logic lives in direct_chat.py
#   - External AI imports made optional
# =============================================

"""
Daemon Bot Telegram Launcher (@aipass_assistant_bot)

Thin wrapper around the shared direct_chat module. All chat logic,
command handling, tmux management, and polling lives in direct_chat.py.
This file only provides the daemon-specific configuration.
"""

import sys
from pathlib import Path

try:
    from api.apps.modules.telegram_chat import run_direct_chat
    TELEGRAM_CHAT_AVAILABLE = True
except ImportError:
    TELEGRAM_CHAT_AVAILABLE = False
    run_direct_chat = None

_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/

if not TELEGRAM_CHAT_AVAILABLE:
    print("[assistant_chat] telegram_chat module not available, exiting")
    sys.exit(1)

sys.exit(run_direct_chat(
    branch_name="daemon",
    session_name="telegram-daemon",
    config_path=Path.home() / ".aipass" / "assistant_bot_config.json",
    work_dir=_DAEMON_ROOT,
    log_dir=_DAEMON_ROOT / "logs",
    data_dir=_DAEMON_ROOT / "daemon_json",
    bot_name="AIPass Assistant Bot",
))
