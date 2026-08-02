#!/bin/bash
# One-shot installer for the DPLAN-0270 P5 /suspend control verb root grants.
#
# Copies files from this directory into system locations and reloads the
# affected daemons. Review before running — this touches /etc.
#
#   sudo tools/suspend/install_suspend_grants.sh
#   sudo tools/suspend/install_suspend_grants.sh --with-wake-sources
#
# Installs:
#   aipass-suspend-sudoers   -> /etc/sudoers.d/aipass-suspend        (0440)
#   60-aipass-suspend.rules  -> /etc/polkit-1/rules.d/60-aipass-suspend.rules (0644)
#   aipass-resume-signal     -> /etc/systemd/system-sleep/aipass-resume-signal (0755)
#                                optional belt-and-braces resume signal — the bot's
#                                primary resume detection is a wall-clock jump in its
#                                own poll loop and does not depend on this hook firing
#
# OPT-IN ONLY, via --with-wake-sources (Patrick's ruling 2026-08-02, compass #216):
#   aipass-wake-sources.sh   -> /usr/local/sbin/aipass-wake-sources.sh (0755)
#   aipass-wake-sources.service -> /etc/systemd/system/aipass-wake-sources.service (0644)
#                                masks the gpe4E spurious-wake storm + disables USB
#                                wakeup sources on every boot (both reset on reboot)
#
# Why opt-in: on Patrick's laptop those "spurious" wakes ARE the product. /suspend
# is used to lock and darken the screen while agents keep running behind the
# password wall, and the short wake beats are what kept phone chat working for
# days. Masking them made suspend real and trapped the conversation. This unit
# must never reappear as a side effect of reinstalling the grants.
#
# `install` does not create missing parent directories by default — on a fresh
# machine /etc/systemd/system-sleep/ may not exist yet, which fails the copy
# with "cannot create regular file." -D makes every install below create its
# target directory first.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Must run as root: sudo $0" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WITH_WAKE_SOURCES=0
for arg in "$@"; do
    case "$arg" in
        --with-wake-sources) WITH_WAKE_SOURCES=1 ;;
        *) echo "Unknown option: $arg (only --with-wake-sources is accepted)" >&2; exit 1 ;;
    esac
done

echo "Installing sudoers drop-in..."
install -D -o root -g root -m 0440 "$SRC_DIR/aipass-suspend-sudoers" /etc/sudoers.d/aipass-suspend
visudo -c -f /etc/sudoers.d/aipass-suspend

echo "Installing polkit rule..."
install -D -o root -g root -m 0644 "$SRC_DIR/60-aipass-suspend.rules" /etc/polkit-1/rules.d/60-aipass-suspend.rules

echo "Installing system-sleep resume-signal hook (optional, belt-and-braces)..."
install -D -o root -g root -m 0755 "$SRC_DIR/aipass-resume-signal" /etc/systemd/system-sleep/aipass-resume-signal

if [ "$WITH_WAKE_SOURCES" -eq 1 ]; then
    echo "Installing spurious-wake-source masking script + boot unit (opt-in)..."
    install -D -o root -g root -m 0755 "$SRC_DIR/aipass-wake-sources.sh" /usr/local/sbin/aipass-wake-sources.sh
    install -D -o root -g root -m 0644 "$SRC_DIR/aipass-wake-sources.service" /etc/systemd/system/aipass-wake-sources.service
    systemctl daemon-reload
    systemctl enable aipass-wake-sources.service
    # restart, not `enable --now`: --now won't re-run an already-active unit, so a
    # re-install would deploy a fixed script without executing it (live-caught)
    systemctl restart aipass-wake-sources.service
else
    echo "Skipping wake-source masking (not requested — pass --with-wake-sources to install it)."
    echo "  The short spurious-wake beats are the accepted deployment mode on this machine."
    if systemctl is-enabled aipass-wake-sources.service >/dev/null 2>&1; then
        echo "  NOTE: aipass-wake-sources.service is currently ENABLED from an earlier install." >&2
        echo "  This script will not touch it. To remove it:" >&2
        echo "    sudo systemctl disable --now aipass-wake-sources.service" >&2
    fi
fi

echo "Done. No suspend was triggered — this only installed the grants."
echo "Live-test sequence:"
echo "  1. sudo -n /usr/sbin/rtcwake -m no -s 60 && sudo -n /usr/sbin/rtcwake -m disable   # sudoers check, no real suspend"
echo "  2. systemctl suspend   # manual real suspend, confirm it no longer prompts for a password"
echo "  3. Send /suspend 2m to the AIPASS control chat and confirm the machine wakes on schedule"
echo "  4. Send /suspend (heartbeat mode), then send any command within the grace window after a wake and confirm it stays awake"
echo "  5. Spurious-wake path: during a heartbeat suspend, if the machine wakes early with no"
echo "     command sent, confirm it re-arms and re-suspends after the grace window on its own"
