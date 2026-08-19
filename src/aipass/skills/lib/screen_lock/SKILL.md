---
name: screen_lock
description: Password-lock the machine's screen while every process keeps running
version: 1.0.0
tags: [system, control, security]
when_to_use:
  - "lock the screen"
  - "lock the machine"
  - "walking away from the desk, keep the agents running"
requires:
  pip: []
  bins: [loginctl]
  config: []
has_handler: true
---

# Screen Lock

## What This Does

Password-locks the graphical session and leaves everything running — agents keep
working behind the password wall. Nothing sleeps, nothing is killed, no root is
needed (no sudoers grant, no polkit rule).

Two paths, tried in order:

1. `loginctl lock-session <id>` against the **explicitly resolved** graphical
   session. Callers usually run as a `systemd --user` service with no
   `XDG_SESSION_ID`, so a bare `lock-session` has no ambient session to resolve
   and may refuse — naming the session is what makes the verb work from there.
2. `gdbus` → `org.gnome.ScreenSaver.Lock` as the fallback.

If both fail it says so. A screen that never locked is never reported as locked.

## Doctrine — lock is the exception

> A destructive action never fires from a locked screen. **Lock itself must work
> from anywhere — that is its whole point.**

So this verb is never gated: it does not ask whether the screen is already
locked, does not require a desktop environment, and does not refuse when no
graphical session can be resolved (it still tries the bare call). Callers that
gate *other* verbs on screen state must leave this one ungated.

## Available Actions

| Action | Description                                        |
|--------|----------------------------------------------------|
| `lock` | Lock the screen now; agents keep running           |

## Usage

```bash
drone @skills run screen_lock lock
```

In-process (what the Telegram control bot and the host API verb lane use):

```python
from aipass.skills.lib.screen_lock import handler as screen_lock

result = screen_lock.lock_screen()
# {"locked": True, "method": "loginctl", "session": "3", "error": None}
```

## When to Use

Use this skill when:
- You are leaving the machine and want the screen locked with work continuing
- A remote surface (phone, host API, chat bot) needs to secure the desk

Do NOT use this skill when:
- You want the machine to sleep — that is `/suspend`, a different verb with a
  wake, grace-window and reachability story. Lock never suspends.
- You want to end sessions — nothing is stopped or killed here.

## Output Format

`run()` returns the standard skill envelope:

```python
{"success": True, "output": "Screen locked via loginctl (session=3)", "error": None}
```

`lock_screen()` returns structured detail for programmatic callers:

```python
{"locked": bool, "method": "loginctl" | "dbus" | None, "session": str | None, "error": str | None}
```

## Notes

- Stdlib + the Prax logger only — importing this skill pulls in no Telegram
  stack, no bot, no network client. A test asserts that in a clean interpreter.
- `resolve_graphical_session()` is public: callers can ask which session is ours
  without locking anything.
- `loginctl` is the declared requirement; `gdbus` is the fallback and is not
  required for the skill to be usable.
- Only sessions of type `wayland`/`x11`, state `active`, owned by our own uid are
  eligible — another user's desktop is never locked.
- Extracted from the Telegram control bot in DPLAN-0300; that bot is the first
  consumer, not the owner.
