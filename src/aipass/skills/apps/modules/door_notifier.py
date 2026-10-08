# =================== AIPass ====================
# Name: door_notifier.py
# Description: Door: skills' Telegram push notification, published for daemon's schedule notifier (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Door for lib/telegram/apps/handlers/notifier.py: the scheduler bot's push notification."""

from aipass.skills.lib.telegram.apps.handlers.notifier import send_telegram_notification

__all__ = ["send_telegram_notification"]
