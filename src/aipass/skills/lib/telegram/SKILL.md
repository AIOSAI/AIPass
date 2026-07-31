---
name: telegram
description: Multi-bot Telegram bridge — routes messages between Telegram and Claude tmux sessions
version: 1.4.0
tags: [communication, bridge, telegram, bot]
requires:
  pip: [telethon]
  bins: [tmux, claude]
  config: []
  aipass: [api, prax, hooks, cli]
has_handler: true
---

# Telegram Bridge

Multi-bot personal-assistant bridge: long-polling listener routes user Telegram messages into Claude tmux sessions. The base reply flow is Claude's Stop hook writing a pending file, which the bot picks up and sends back to Telegram; bots opting into streaming (below) also live-edit a "Processing..." placeholder while the reply is still being generated. A control-center bot exposes /start, /kill, /suspend to wake, kill, and sleep terminal sessions by branch, and a separate hook mirrors terminal-typed messages into the same TG chat so the conversation reads as one continuous thread regardless of which door you type in.

## Architecture

- **BaseBot** — polling loop, tmux injection, heartbeat, lock management, control verbs, streaming, offline backoff
- **BranchPlugin** — per-branch overrides (message prefix, response prefix, session startup)
- **ResponseRouter** — CWD-safe pending-file routing for multi-bot
- **TelegramStandards** — shared /start, /help, /new, /status command handlers
- **BotFactory** — bot create/delete lifecycle (8-step)
- **BotRegistry** — fcntl-locked JSON registry CRUD
- **BotOperations** — start/stop/status ops
- **BotFatherClient** — optional Telethon BotFather automation
- **Config** — bot configuration via @api secrets store
- **FileHandler** — download, classify, and prompt file uploads
- **LogStreamer** — daemon thread tailing logs to Telegram
- **Notifier** — standalone push notification sender
- **TmuxManager** — tmux session helpers (not the control verbs — see below)
- **UserMessageRelay** — UserPromptSubmit hook that mirrors terminal-typed messages into the branch's TG chat

## Usage

```bash
drone @skills run telegram start <bot_id>
drone @skills run telegram stop <bot_id>
drone @skills run telegram status [bot_id]
drone @skills run telegram create <bot_id> --token <token>
drone @skills run telegram delete <bot_id>
drone @skills run telegram notify "message"
```

## Control verbs (DPLAN-0270 P1)

One bot doubles as a control center: `_is_control_bot()` is true when `branch_name` is `None` (a bare base bot) or `"aipass"` (the deployed control-center config — same `bot_id="base"` process, no separate bot). Only that bot handles these commands; branch bots fall through to the normal command set.

- `/start [branch]` — wake a terminal agent (default branch: `aipass`). Spawns a detached tmux session `aipass-<branch>` in the branch's registered path and launches `claude -c || claude`. No-ops with "already running" if the session exists (one session per branch).
- `/kill [branch]` — kill the `aipass-<branch>` tmux session outright. No graceful-stop nuance in v1 (Patrick's ruling).
- `/status` — on the control bot, appends a live listing of all `aipass-*` sessions (branch, PID, alive/dead) below the normal status text.

Session names use the `CONTROL_SESSION_PREFIX = "aipass-"` prefix and are managed with direct `subprocess` calls to `tmux` inside `base_bot.py` — **not** `tmux_manager.py`'s `kill_session`/`list_sessions`/`has_tmux`, which remain ported-but-unwired (see table below).

The command menu is re-registered via BotFather's `setMyCommands` on every startup (`_set_command_menu()`, called from `run()`), so the control bot's `/start` entry is overridden with control-verb text instead of the generic welcome copy.

## /suspend (DPLAN-0270 P5)

Control-bot-only. `/suspend [duration]`:
- No argument — **heartbeat mode**. Arms `rtcwake` for `suspend_heartbeat_minutes` (bot config override, default 25) and suspends. On each wake it checks for a command in a 100s grace window (`SUSPEND_GRACE_WINDOW_SECONDS`); if none arrived, it re-arms and re-suspends on its own (absorbs spurious wakes without staying up).
- `8h` / `45m` — **single-wake mode**, wakes once after the given duration.

Resume detection is primarily a **wall-clock jump** in the poll loop: if the gap between consecutive loop iterations exceeds `RESUME_WALLCLOCK_JUMP_SECONDS` (45s — chosen to clear both the 30s poll timeout and the 60s network-backoff cap, so neither produces a false positive), a resume is assumed. An optional systemd `system-sleep` hook (`aipass-resume-signal`) writing a resume-stamp file is kept as a secondary signal, since this signal is not proven to fire reliably on the deployed hardware.

Root-privileged pieces live as reviewable repo files in `tools/suspend/`, installed by `tools/suspend/install_suspend_grants.sh` (never applied directly to `/etc` by an agent):
- `aipass-suspend-sudoers` — passwordless `rtcwake` for the bot user
- `60-aipass-suspend.rules` — polkit rule for `systemctl suspend`
- `aipass-resume-signal` — optional system-sleep resume-stamp hook
- `aipass-wake-sources.sh` + `aipass-wake-sources.service` — boot-time oneshot that re-masks a spurious ACPI GPE wake source and disables USB wakeup on affected devices (both reset every reboot)

**Honest status:** the hardening above (wall-clock-jump detection, stale-stamp fix, wake-source persistence unit) landed as code + tests only. The currently running bot predates it — installing the grants and restarting the bot is a deliberate, separate session (DPLAN-0270's test-matrix step T3), not something applied automatically on landing.

## Streaming replies (DPLAN-0229)

Opt-in per bot via the `stream` config key (`stream: true`, default `false`). When enabled, instead of waiting silently for the Stop hook, `_streaming_loop` tails the active Claude transcript every `STREAM_INTERVAL` (2s) and live-edits the "Processing..." placeholder message with the growing response via `editMessageText`. `_stream_edit` handles Telegram's edit-specific quirks: a 429 backs off for the given `retry_after` seconds, and a "message is not modified" 400 is treated as success (no-op edit). The pending file written for the Stop hook still carries a `"streaming": True` flag either way — streaming is a live preview layered on top of the same finalize-on-Stop-hook flow, not a replacement for it.

## user_message_relay — terminal-to-TG mirror

`user_message_relay.py` is a `UserPromptSubmit` hook: when you type in a terminal (or any non-TG door) instead of Telegram, it posts that message into the branch's TG chat so the chat reads as the full conversation. It skips: subagent prompts, system/dispatch noise, TG-origin messages (marked with `"via Telegram:"`), and consecutive duplicate prompts (md5-hashed).

**Dual registration is required — an `enabled: true` flag alone does nothing.** The hook needs BOTH:
1. An enabled handler entry in `.aipass/hooks.json` (project config)
2. A matching provider bridge entry in `~/.claude/settings.json`

`drone @hooks verify` cross-checks the two and reports handlers that are enabled in one but missing from the other — run it after any hook registration change.

Bot lookup uses two directories with **different naming conventions**, searched separately:
- `MIRROR_DIR` (`~/.aipass/telegram_bots/`) — `bot_factory.py` shadow configs, named `{bot_id}.json`
- `PENDING_DIR` (`~/.aipass/telegram_pending/`) — transcript-relay stream state, named `bot-{bot_id}.json`

## Offline handling — backoff, 409, 429

The main poll loop (`run()`) tracks two independent backoffs:
- **Non-network errors** — plain `retry_delay`, 5s doubling to a 60s cap.
- **Network errors** (`_NetworkPollError`, raised for connection failures, HTTP 5xx, and HTTP 409 — a second poller holding the long-poll) — exponential backoff from `NETWORK_BACKOFF_INIT` (1s) to `NETWORK_BACKOFF_CAP` (60s), with a summary log line every `NETWORK_LOG_INTERVAL` while still offline and a "reachable again" log on recovery.

HTTP 429 (rate limit) on `poll_updates` is handled inline — sleep for the `retry_after` Telegram returns, then return an empty update batch rather than raising.

## Secrets

Bot tokens and config accessed via the in-process `aipass.api.apps.modules.secrets.get_secret` API.
State files (offset, lock, registry) stay with the skill in `.local/`.

## Ported-but-unwired (DPLAN-0220)

This bridge is a partial port of the ~9k-line "Dev-Pass" telegram system. Several
functions are **ported but not yet wired** — they have no caller today and will be
connected as DPLAN-0220 completes. They are *not* dead code (do not delete them; see
S249), so seedgo's `unused_function` check is bypassed for them in
`.seedgo/bypass.json`. As each one is wired up, remove its bypass entry.

| File | Function(s) | Awaiting |
|---|---|---|
| `base_bot.py` | `on_response` | response hook (Wave-2 design call) |
| `base_bot.py` | `_read_transcript_tail` | DPLAN-0226 OUT relay — built and tested, wiring pending end-to-end integration |
| `branch_plugin.py` | `on_response` | per-branch response hook (Wave-2 design call) |
| `response_router.py` | `find_pending_bot`, `clean_expired_pending` | response_router import-vs-delete decision |
| `bot_registry.py` | `get_bot_by_work_dir` | CWD→bot match for the response router |
| `bot_operations.py` | `get_all_bots` | multi-bot listing |
| `config.py` | `get_allowed_user_ids`, `validate_config` | config accessor/validator wiring |
| `file_handler.py` | `download_telegram_file`, `cleanup_file` | file up/download feature |
| `tmux_manager.py` | `_send_rename`, `has_tmux`, `kill_session`, `list_sessions`, `get_session_pane` | interactive tmux session management — control verbs use their own direct `subprocess` calls instead |

`chunk_text` (long-message splitting, now used by `scheduler_bot.py`) and `_extract_assistant_text` (DPLAN-0226 OUT relay, now used by `base_bot.py`) are wired as of this pass and have been removed from this table and from `.seedgo/bypass.json`.
