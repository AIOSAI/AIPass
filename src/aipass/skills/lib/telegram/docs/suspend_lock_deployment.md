# Suspend / Lock Deployment — where it stands

Reference for the `/lock` and `/suspend` control verbs and the machine policy behind them.
Written 2026-08-02, every claim verified against the tree and the live machine on that date.

Companion to [`../SKILL.md`](../SKILL.md), which documents the mechanisms. This doc documents
the **deployment**: what is on, what is off, and why.

---

## 1. Deployment model (Patrick's ruling #217, supersedes #216)

**The machine stays awake 24/7. Lock is never sleep.**

The remote-control story does not depend on the machine sleeping — it depends on the machine
being reachable. Reachability comes from the Telegram control chat, authenticated by
`allowed_user_ids` in the bot config. The screen lock gates only the **display**; citizens,
bots, builds, tmux sessions and the poll loop all keep running behind it.

Real suspend means real disconnect. No amount of grace-window engineering changes that — a
suspended machine is not polling Telegram, so the conversation stalls until something wakes
it. That is why `/suspend` is retired from daily use rather than tuned further.

| | `/lock` | `/suspend` |
|---|---|---|
| Status | **Daily driver** | **Grounded** — shipped, tested, not for routine use |
| Screen | Locked + dark | Locked + dark |
| Agents / bots / builds | Keep running | Stopped (machine asleep) |
| Telegram reachable | Yes, continuously | Only during wake beats |
| Root grants needed | None | sudoers (rtcwake) + polkit (suspend) |
| Failure mode | Screen does not lock, you are told | Conversation trapped behind a sleeping machine |

---

## 2. The verbs as they stand

Control verbs are gated by `_is_control_bot()` — true when `branch_name` is `None` (bare base
bot) or `"aipass"` (the deployed control-center config, same `bot_id="base"` process). Branch
bots fall through to the normal command set. All are registered via `get_custom_commands()`.

### `/lock` — the daily driver (base_bot v1.5.1)

Locks the screen, leaves everything running. No root, no sudoers grant, no polkit rule.

Mechanism, in order — first success wins:

1. `_resolve_graphical_session()` — `loginctl list-sessions --no-legend`, then per session
   `loginctl show-session <id> -p Type -p State -p User`. Selects the session where
   `Type` is `wayland` or `x11` **and** `State=active` **and** `User == os.getuid()`.
   The uid match is deliberate: never lock another user's desktop.
2. `loginctl lock-session <id>` — the resolved session, named explicitly.
3. `gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver
   --method org.gnome.ScreenSaver.Lock` — fallback if loginctl refuses or is missing.
4. Honest failure. A screen that never locked is never acked as locked.

Success ack: `🔒 Locked — agents stay awake.`

**Why the session must be resolved explicitly:** the bot runs as `telegram-bot@base.service`,
a `systemd --user` unit, which sits outside the graphical session scope. It has no
`XDG_SESSION_ID`, so a bare `loginctl lock-session` has no ambient session to resolve and can
refuse.

**Live-proven twice on 2026-08-02**, both resolving `session=3`:

- 13:13 — the real `_handle_control_lock` code path driven from an environment with
  `XDG_SESSION_ID`, `XDG_SESSION_TYPE` and `XDG_SESSION_CLASS` unset, reproducing the service
  context. `LockedHint` went `no` → `yes`.
- 13:28:51 — Patrick's own tap in the Telegram control chat, through the live
  `telegram-bot@base.service` after its 13:26 restart onto v1.5.1. Logged by the service as
  `Screen locked via loginctl (session=3)`.

The `gdbus` fallback has **never fired on this machine** — the loginctl path works from the
service context. It is covered by mocked tests only.

### `/suspend [duration]` — shipped, grounded

Gated a second time by `suspend_enabled` in the bot config (default `true`) — the ops parking
brake, grounds the verb without a code edit. No argument = heartbeat mode; `8h` / `45m` =
single-wake mode.

The v1.5.0 rework (2026-08-02) fixed four real defects. All landed as code + tests; none has
run an approved overnight soak:

- **Cross-process presence stamp** — every bot process stamps
  `~/.aipass/telegram_bots/last_inbound.json` on any allowed-user inbound. Any inbound on any
  bot now cancels the cycle. Previously the control bot was blind to a conversation happening
  on `@devpulse`, because it is a separate OS process.
- **Alarm-time wake classification** — the wake is classified by comparing against the armed
  alarm, not by guessing from gap size. More than `SUSPEND_EARLY_WAKE_MARGIN_SECONDS` (60s)
  early = a human woke it → cancel the cycle and disarm. At or after the alarm = our RTC →
  open the grace window.
- **Grace anchored to the first successful poll** after resume, not to resume detection —
  DNS/network needs 45–60s to return, and the whole reply chain has to fit inside the window.
- **In-flight hold** — re-arming is blocked while any bot has an undelivered pending, so a
  reply in flight is never cut off.
- **Adaptive cadence** — 3-minute beats while the conversation is live, 25-minute beats when
  quiet, liveness read from the shared presence stamp. Parked behind a grounded verb; kept
  rather than stripped (devpulse ruling, 2026-08-02).

Constants (`base_bot.py`): `SUSPEND_GRACE_WINDOW_SECONDS=180`,
`SUSPEND_EARLY_WAKE_MARGIN_SECONDS=60`, `RESUME_WALLCLOCK_JUMP_SECONDS=45`,
`SUSPEND_HEARTBEAT_DEFAULT_MINUTES=25`, `SUSPEND_ACTIVE_HEARTBEAT_DEFAULT_MINUTES=3`,
`SUSPEND_ACTIVE_WINDOW_DEFAULT_MINUTES=30`, `RTCWAKE_BIN=/usr/sbin/rtcwake`.

### The other control verbs

| Verb | Effect |
|---|---|
| `/start [branch]` | Wake a terminal agent — detached tmux session `aipass-<branch>`, runs `claude -c \|\| claude`. Default branch `aipass`. No-ops if the session exists. |
| `/kill [branch]` | Kill the `aipass-<branch>` tmux session outright. No graceful stop (Patrick's ruling). |
| `/status` | Normal status text plus a live listing of all `aipass-*` sessions (branch, PID, alive/dead). |
| `/stop` | Every bot, not just control bots — Escape-interrupts *this* bot's own mirrored session. |
| `/logs`, `/monitor` | Session log stream control and system-wide log subscription. |

---

## 3. Machine config backing the model

Verified on this laptop 2026-08-02. This is the configuration that makes "always awake" true;
without it GNOME or logind will sleep the machine regardless of what the verbs do.

| Setting | Value | Why |
|---|---|---|
| `org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type` | `nothing` | Never auto-suspend on AC |
| `…sleep-inactive-battery-type` | `nothing` | Never auto-suspend on battery either |
| `org.gnome.desktop.session idle-delay` | `0` | Screen never blanks on idle — Patrick's preference; `/lock` is the lock path, not a timer |
| `org.gnome.desktop.screensaver lock-enabled` | `true` | When it does lock, a password is required |
| `org.gnome.desktop.screensaver lock-delay` | `0` | Lock takes effect immediately, no grace period |
| `/etc/systemd/logind.conf` `HandleLidSwitch` | `ignore` | Closing the lid does not suspend |
| `HandleLidSwitchExternalPower` | `ignore` | Same on AC |
| `aipass-wake-sources.service` | `disabled` / `inactive` | Patrick ran the disable 2026-08-02 |

Note: the `sleep-inactive-*-timeout` values (3600 AC / 900 battery) are still at their
defaults but are inert while the corresponding `-type` is `nothing`.

### Root grants — installed but dormant

Installed 2026-07-30 by `tools/suspend/install_suspend_grants.sh`, unused while `/suspend` is
retired. Left in place so re-enabling suspend needs no reinstall:

- `/etc/sudoers.d/aipass-suspend` (0440 root) — passwordless `rtcwake` for the bot user
- `/etc/polkit-1/rules.d/60-aipass-suspend.rules` — polkit rule for `systemctl suspend`
  (the rules directory is root-only, so this one could not be stat'd from the bot user;
  it is what the installer writes)
- `/etc/systemd/system-sleep/aipass-resume-signal` (0755 root) — optional secondary
  resume-stamp hook. Not load-bearing: primary resume detection is the bot's own wall-clock
  jump plus alarm-time check.

### Wake-source masking — opt-in only

`aipass-wake-sources.sh` + `.service` mask the gpe4E spurious-wake storm and disable USB wakeup
sources on every boot (both reset on reboot). The installer **only** installs them behind an
explicit `--with-wake-sources` flag; unknown flags are rejected outright. A default reinstall
does not touch the unit, and if it detects the unit still enabled from an earlier install it
prints a warning to stderr with the removal command rather than acting on it. Removal stays a
human decision. See section 4 for why this is opt-in.

---

## 4. The saga (for future archaeology)

**Jul 30 – Aug 1 — the "perfect days".** Chat-behind-suspend felt near-live. `/suspend` was
shipped and in daily use; Patrick could message the machine and get answers back promptly
while it appeared to be asleep.

**What was actually happening.** It was a hardware bug, not a feature. Spurious ACPI wakes on
gpe4E were defeating suspend, duty-cycling the machine in 7–44 second naps. The machine was
never really asleep for long, so the bot kept polling. The good behaviour was an accident.

**2026-08-02 morning — the trap.** The `aipass-wake-sources` masking was installed to stop the
spurious wakes. It worked: suspend became real. Patrick was then trapped behind a genuinely
sleeping machine — 5 suspend cycles in 25 minutes. Two defects compounded it: his chat
messages did not count as presence (the control bot is a separate process from `@devpulse`,
where he was actually typing), and the grace window started at resume detection rather than at
the first successful poll, so it had usually expired before the network came back.

**Ruling #216 (12:46).** The spurious wakes ARE the product on this hardware. Wake-source
masking reverted to opt-in, default not installed, and it must never come back as a side
effect of reinstalling grants.

**v1.5.0 (`ba549363`).** Fixed presence (cross-process stamp), wake classification
(alarm-time comparison — a 14-second nap fell below the gap threshold entirely), grace
anchoring (first successful poll), and added the in-flight hold plus the `suspend_enabled`
parking brake.

**The live soak.** v1.5.0 worked exactly as designed — and Patrick still hit the wall. Fixed
suspend is still suspend, and real sleep is real disconnect.

**Ruling #217 (13:07, supersedes #216).** The machine stays awake 24/7. `/suspend` is retired
from daily use. `/lock` — the thing `/suspend` was actually being used for — becomes the daily
driver. Built and hardened the same afternoon (`05f8baa7`).

The lesson worth keeping: *a behaviour that seems to work can be a hardware bug in disguise.*
Fixing the bug killed the behaviour, and the behaviour was the point.

---

## 5. Ops runbook

### Check state

```bash
cat /sys/class/rtc/rtc0/wakealarm          # RTC alarm — empty means disarmed
loginctl list-sessions --no-legend         # find the graphical session id
loginctl show-session 3 -p LockedHint -p Type -p State
journalctl -b | grep "PM: suspend"         # did the machine actually sleep this boot?
systemctl --user status telegram-bot@base  # is the control bot up
tail -f ~/Projects/AIPass/system_logs/skills_bot_base.log   # the live base bot's log
```

`journalctl -b | grep "PM: suspend"` prints `PM: suspend entry (deep)` / `PM: suspend exit`
pairs — the kernel's own record of whether the machine really slept, independent of anything
the bot believes.

Lock events log as `Screen locked via loginctl (session=<id>)` or
`Screen locked via the GNOME ScreenSaver D-Bus fallback`.

### Kill a runaway suspend loop

In order of escalation:

```bash
sudo -n /usr/sbin/rtcwake -m disable          # 1. disarm the pending RTC alarm
systemctl --user restart telegram-bot@base    # 2. restart the control bot, clearing heartbeat state
# 3. set "suspend_enabled": false in the base bot config — survives restarts, no code edit
```

Step 3 is the durable fix; steps 1–2 stop the current cycle. Heartbeat state
(`_suspend_heartbeat_active`, `_suspend_alarm_at`) lives in process memory, so a restart
clears it — but not the armed RTC alarm, which is why step 1 comes first.

### Re-enable suspend deliberately

Only with Patrick's approval — the verb is grounded, and it has never passed the hands-off
overnight soak (DPLAN-0270 test-matrix step T4). Never self-trigger a live suspend.

1. Confirm `suspend_enabled` is `true` (or absent — it defaults to true) in the base bot config.
2. Grants are already installed; verify with
   `sudo -n /usr/sbin/rtcwake -m no -s 60 && sudo -n /usr/sbin/rtcwake -m disable`
   (arms and disarms, no real suspend).
3. Decide on wake-source masking. Leave it off to get the short-beat behaviour back; install it
   with `sudo tools/suspend/install_suspend_grants.sh --with-wake-sources` to make suspend real.
   These are opposite outcomes — see section 4.
4. Soak overnight with Patrick present before trusting it.

---

## 6. Where it stands

| | |
|---|---|
| `base_bot.py` | v1.5.1 |
| `lib/telegram/SKILL.md` | v1.5.2 |
| `tests/test_suspend.py` | v2.0.1 |
| Commits | `ba549363` (suspend rework v1.5.0) + `05f8baa7` (/lock hardening v1.5.1), both on PR#725 |
| Tests | 77 suspend + lock; 1211 passed / 1 skipped across the full telegram + skills suites |
| seedgo | `audit aipass @skills` — 100% overall, no type errors |
| Live unit | `telegram-bot@base.service` (`systemd --user`), restarted onto v1.5.1 at 13:26 on 2026-08-02 |
| Also running | `telegram-bot@{api,devpulse,prax_monitor,scheduler}.service`, `prax-monitor.service` |
| `/lock` | Live and proven |
| `/suspend` | Grounded — do not live-test without Patrick |
