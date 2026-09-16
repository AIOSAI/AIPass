[← Back to the skills README](../README.md)

# The Telegram Skill — Retired

Telegram is retired: switched off, left in place, its tests skipped and never fixed. This page is the record of that state and of the portability work that came before it.

**Retired — the telegram skill (the owner's ruling of 2026-09-14).** Telegram is
skipped and ignored by all. The work stays in place, disabled — nothing was
deleted, moved or renamed — and it does nothing:

- `drone @skills run telegram <anything>` refuses in one line: *Skill 'telegram'
  is switched OFF and will not run (Telegram is retired - the owner ruling
  2026-09-14: ...)*. The reason is the off-switch's own record; it has been OFF
  since 2026-08-18, and its five `telegram-bot@` units stay masked.
- `lib/telegram/apps/handlers/notifier.py` asks the switch itself before it
  sends. @daemon's scheduler lifecycle pings import it in-process and never
  pass the runner's gate, so until 2026-09-14 they were still being delivered
  with the skill switched off (its log shows two sends on each of 09-13 and
  09-14). Off, or an unreadable switch state, now sends nothing.
- Every test under `lib/telegram/tests/` is **skipped, never fixed**:
  `pytest_collection_modifyitems` in that directory's existing `conftest.py`
  marks each case skipped with the ruling as the reason. A skip marker rather
  than `collect_ignore`, so all 1114 cases still show up as skipped. That
  covers seedgo's runtime-probe finding (`test_log_streamer.py` wrote
  `~/.aipass/telegram_bots/last_inbound.json`), which is not cured.
- Lifting it is `drone @skills on telegram` plus deleting that hook.

## The Telegram Skill On A Host Without tmux Or systemd

When `host_portability` started reading `lib/` it found 12 calls in the telegram
skill running `tmux` or `systemctl` with no probe and no `FileNotFoundError`
handler (`base_bot.py` 7, `bot_factory.py` 3, `tmux_manager.py` 2). A missing
binary raises out of exec, before there is a return code to check. One of them
was a real escape, not a technicality: `tmux_manager.session_exists` is called
**above** the `try` in `send_message`, `kill_session` and `get_session_pane`, so
their own `except Exception` never saw it and all three raised on a host without
tmux.

Every call site now catches the exec failure where it sits and returns a
verdict:

- `session_exists` answers False, so `kill_session` has nothing to kill,
  `get_session_pane` is None and `send_message` is False. `_send_rename` logs.
- `inject_message` and `_kill_tmux_session` return False.
- `/start` and `/kill` reply `tmux not found on this machine.` — the same words
  the has-session probe above them already used.
- `launch_mirror_session` returns False when tmux is gone at `new-session` or at
  either `send-keys`. A session nobody typed into is not a mirror session, and
  the old code would have returned True over it.
- `/suspend` on a host with no `systemctl` disarms the alarm it armed and says
  `systemctl is not installed on this host.` The polkit advice cannot work
  there. A suspend that systemd *refused* still gets the polkit text,
  byte-identical.

No `shutil.which` probe was added. Every unit that exercises these functions
mocks `subprocess.run`; a probe beside the call would make those units measure
the runner's package list, which is the defect @api cured in `3ef3d571`.
Catching at the call is driven by the same mock the units already hold.

Pinned by 13 cases across five existing telegram test files. All 13 fail against
the pre-cure handlers, and 11 mutants — one per clause, plus the mirror session
claiming success and the suspend message reverting to polkit — all go red.

The skill is still switched **OFF** (since 2026-08-18, retired 2026-09-14), so
nothing live changed.
Its three `/proc` reads in `base_bot.py` are not scored: each sits inside
`except OSError` and degrades honestly. One is still worth knowing as behaviour —
the bot-lock check guards its `/proc/<pid>/cmdline` read with
`sys.platform != "win32"`, so on macOS the PID-reuse verification is silently
skipped and the lock trusts liveness alone. That waits for a switch-on plan.

**Known issue — five deployed bots still keep config in the secret store.**
Since 2026-09-07 only the token is written there (`config.SECRET_FIELDS`), but
the bots created before that carry all ten keys in their secret document. They
load and run, and warn by name on every load. `drone @skills run telegram
migrate-config` reports what would move — measured 2026-09-07: api 6 keys, base
6, devpulse 7, prax_monitor 5, scheduler 6, and `telethon_config` correctly
untouched because api_id/api_hash are real secrets. `--apply` splits them for
real. Not run, and moot since the 2026-09-14 retirement.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
