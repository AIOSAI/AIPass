#!/bin/bash
# Masks known spurious-wake sources on this laptop (DPLAN-0270 P5 hardening).
#
# Live suspend testing found a gpe4E ACPI GPE interrupt storm (8.5M interrupts,
# suspected Broadcom `wl` driver misbehaving during the suspend path) that was
# producing spurious resumes roughly every ~44s. Both settings below are
# runtime-only (sysfs / procfs) knobs — they reset on every reboot — so this
# script is meant to be re-run at boot by aipass-wake-sources.service rather
# than hand-applied once.
#
# Idempotent by design:
#   - the GPE mask write is guarded: masking an already-masked GPE returns
#     EINVAL on this kernel (live-caught 2026-07-30: first `--now` start failed
#     because the mask had been hand-applied earlier the same day), so the
#     write only happens when the sysfs entry doesn't already show "masked".
#   - /proc/acpi/wakeup TOGGLES a device's wakeup flag on every write, so each
#     device is only written if it's currently enabled — writing to an
#     already-disabled device would silently re-enable it.

set -euo pipefail

GPE_FILE="/sys/firmware/acpi/interrupts/gpe4E"
WAKEUP_FILE="/proc/acpi/wakeup"
WAKE_DEVICES=(XHC1 RP01 RP02 RP03 RP05 RP06)

if [ -w "$GPE_FILE" ]; then
    # -w: the unmasked state's line contains "unmasked", which a plain
    # substring match also hits (live-caught on the first post-install boot:
    # the guard skipped masking a fresh, unmasked GPE)
    if grep -qw "masked" "$GPE_FILE"; then
        echo "$GPE_FILE already masked — skipping"
    else
        echo mask > "$GPE_FILE"
        echo "Masked $GPE_FILE"
    fi
else
    echo "Skipping $GPE_FILE (not present/writable on this kernel)" >&2
fi

if [ -w "$WAKEUP_FILE" ]; then
    for dev in "${WAKE_DEVICES[@]}"; do
        if grep -Eq "^${dev}[[:space:]].*enabled" "$WAKEUP_FILE"; then
            echo "$dev" > "$WAKEUP_FILE"
            echo "Disabled wakeup for $dev"
        else
            echo "$dev already disabled (or not present) — skipping"
        fi
    done
else
    echo "Skipping $WAKEUP_FILE (not present/writable on this kernel)" >&2
fi
