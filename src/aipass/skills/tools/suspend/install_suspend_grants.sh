#!/bin/bash
# One-shot installer for the DPLAN-0270 P5 /suspend control verb root grants.
#
# Copies 3 files from this directory into system locations and reloads the
# affected daemons. Review before running — this touches /etc.
#
#   sudo tools/suspend/install_suspend_grants.sh
#
# Installs:
#   aipass-suspend-sudoers  -> /etc/sudoers.d/aipass-suspend        (0440)
#   60-aipass-suspend.rules -> /etc/polkit-1/rules.d/60-aipass-suspend.rules (0644)
#   aipass-resume-signal    -> /etc/systemd/system-sleep/aipass-resume-signal (0755)

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Must run as root: sudo $0" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing sudoers drop-in..."
install -o root -g root -m 0440 "$SRC_DIR/aipass-suspend-sudoers" /etc/sudoers.d/aipass-suspend
visudo -c -f /etc/sudoers.d/aipass-suspend

echo "Installing polkit rule..."
install -o root -g root -m 0644 "$SRC_DIR/60-aipass-suspend.rules" /etc/polkit-1/rules.d/60-aipass-suspend.rules

echo "Installing system-sleep resume-signal hook..."
install -o root -g root -m 0755 "$SRC_DIR/aipass-resume-signal" /etc/systemd/system-sleep/aipass-resume-signal

echo "Done. No suspend was triggered — this only installed the grants."
echo "Live-test sequence:"
echo "  1. sudo -n /usr/sbin/rtcwake -m no -s 60 && sudo -n /usr/sbin/rtcwake -m disable   # sudoers check, no real suspend"
echo "  2. systemctl suspend   # manual real suspend, confirm it no longer prompts for a password"
echo "  3. After waking, check: cat /home/patrick/.aipass/telegram_bots/resume_signal.json"
echo "  4. Send /suspend 2m to the AIPASS control chat and confirm the machine wakes on schedule"
echo "  5. Send /suspend (heartbeat mode), then send any command within the grace window after a wake and confirm it stays awake"
