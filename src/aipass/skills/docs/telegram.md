[← Back to the skills README](../README.md)

# The Telegram Skill — Retired

Telegram is retired: switched off, left in place, its tests skipped and never fixed. It does nothing:

- `drone @skills run telegram <anything>` refuses in one line: *Skill 'telegram'
  is switched OFF and will not run (Telegram is retired - ...)*. The reason is
  the off-switch's own record, and its five `telegram-bot@` units stay masked.
- `lib/telegram/apps/handlers/notifier.py` asks the switch itself before it
  sends. @daemon's scheduler lifecycle pings import it in-process and never
  pass the runner's gate, so the notifier's own check is what stops them. Off,
  or an unreadable switch state, sends nothing.
- Every test under `lib/telegram/tests/` is **skipped, never fixed**:
  `pytest_collection_modifyitems` in that directory's `conftest.py` marks each
  case skipped with the retirement as the reason. A skip marker rather than
  `collect_ignore`, so every case still shows up as skipped. This hook is the
  only skip condition in the branch: under `pytest . -rs` every skipped case
  carries that reason, and nothing outside `lib/telegram/tests/` skips. It
  also covers seedgo's runtime-probe finding: `test_log_streamer.py` writes
  `~/.aipass/telegram_bots/last_inbound.json`.
- Lifting it is `drone @skills on telegram` plus deleting that hook.

## The Telegram Skill On A Host Without tmux Or systemd

A missing `tmux` or `systemctl` binary raises out of exec, before there is a
return code to check. Every call site in `base_bot.py`, `bot_factory.py` and
`tmux_manager.py` catches the exec failure where it sits and returns a verdict:

- `session_exists` answers False, so `kill_session` has nothing to kill,
  `get_session_pane` is None and `send_message` is False. `_send_rename` logs.
- `inject_message` and `_kill_tmux_session` return False.
- `/start` and `/kill` reply `tmux not found on this machine.` — the same words
  the has-session probe above them uses.
- `launch_mirror_session` returns False when tmux is gone at `new-session` or at
  either `send-keys`. A session nobody typed into is not a mirror session.
- `/suspend` on a host with no `systemctl` disarms the alarm it armed and says
  `systemctl is not installed on this host.` The polkit advice cannot work
  there. A suspend that systemd *refused* still gets the polkit text.

There is no `shutil.which` probe. Every unit that exercises these functions
mocks `subprocess.run`; a probe beside the call would make those units measure
the runner's package list. Catching at the call is driven by the same mock the
units already hold.

Its three `/proc` reads in `base_bot.py` each sit inside `except OSError` and
degrade honestly. One is worth knowing as behaviour: the bot-lock check guards
its `/proc/<pid>/cmdline` read with `sys.platform != "win32"`, so on macOS the
PID-reuse verification is skipped and the lock trusts liveness alone.

**Known issue — deployed bots may still keep config in the secret store.** Only
`config.SECRET_FIELDS` (`bot_token`, `api_id`, `api_hash`) belong there, but a
bot whose secret document carries other keys and has no config file still loads
and runs, and warns on every load with the count of non-secret keys, never
their names. `drone @skills run telegram migrate-config` reports what would
move; `--apply` splits them. `telethon_config` is left untouched because
`api_id` / `api_hash` are real secrets.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
