# =================== AIPass ====================
# Name: notify.py
# Description: Desktop Notification Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Desktop Notification Handler

Sends persistent, stacking desktop notifications via D-Bus.
GNOME's Portal mode strips persistence hints from notify-send,
so we use the dbus module directly with unique app names per
notification source to ensure they stack in the notification center.
"""

import shutil
import subprocess
import sys

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler


def send_notification(title: str, body: str, source: str = "ai_mail", icon: str = "dialog-information") -> bool:
    """Send a persistent desktop notification.

    Args:
        title: Notification title (e.g. "Email from @spawn")
        body: Notification body text
        source: Branch/context name used as app identity for stacking.
                Each unique source gets its own slot in the notification center.
        icon: Icon name (dialog-information, dialog-warning, etc.)

    Returns:
        True if sent, False on failure
    """
    json_handler.log_operation("send_notification", {"title": title, "source": source})

    # Primary: dbus direct (bypasses Portal, supports stacking)
    if _send_via_dbus(title, body, source, icon):
        return True

    # Fallback: notify-send (works on non-GNOME, macOS via homebrew, etc.)
    return _send_via_notify_send(title, body, icon)


def _send_via_dbus(title: str, body: str, source: str, icon: str) -> bool:
    """Send notification via D-Bus using system python."""
    try:
        # Use system python which has dbus module (venv python may not)
        # Find python3 cross-platform (not hardcoded /usr/bin/python3)
        system_python = shutil.which("python3") or shutil.which("python") or sys.executable
        result = subprocess.run(
            [system_python, "-c", _DBUS_SCRIPT, source, icon, title, body], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        logger.warning("[notify] D-Bus notification failed: %s", e)
        return False


def _send_via_notify_send(title: str, body: str, icon: str) -> bool:
    """Fallback: send via notify-send."""
    try:
        subprocess.run(["notify-send", "-i", icon, title, body], capture_output=True, timeout=5)
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        logger.warning("[notify] notify-send fallback failed: %s", e)
        return False


# Inline script executed by system python (which has dbus module).
# Kept as a string to avoid importing dbus in the venv.
_DBUS_SCRIPT = """\
import sys, dbus
source, icon, title, body = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
bus = dbus.SessionBus()
proxy = bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
iface = dbus.Interface(proxy, 'org.freedesktop.Notifications')
iface.Notify(source, 0, icon, title, body, [], {'urgency': dbus.Byte(1)}, -1)
"""
