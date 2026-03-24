# AI_MAIL

**Purpose:** Inter-agent messaging for AIPass. File-based email system that lets agents send, receive, and process messages using `@branch` addresses. No SMTP, no external services — just JSON files and symbolic routing.
**Module:** `aipass.ai_mail`
**Created:** 2025-11-08
**Last Updated:** 2026-03-24

---

**Status:** Operational. Core email workflow (send/inbox/reply/close), dispatch system, daemon, desktop notifications all working. Seedgo 96%.

## Commands / Usage

```bash
drone @ai_mail dispatch @target "Subject" "Body"          # Send dispatch email + wake
drone @ai_mail dispatch @target "Subject" "Body" --fresh  # Send + fresh wake
drone @ai_mail email @target "Subject" "Body"             # Send email (no wake)
drone @ai_mail dispatch wake @target                      # Wake only (no email)
drone @ai_mail inbox                                      # Check inbox
drone @ai_mail --help                                     # Full help
```

## Email Lifecycle

Messages follow a 3-state model:

```
new → opened → closed
```

- **new** — Delivered to inbox, never viewed
- **opened** — Viewed by recipient, awaiting action
- **closed** — Replied or dismissed, archived automatically

## Dispatch System

The `--dispatch` flag marks emails for autonomous execution. A polling daemon watches inboxes and spawns agents to process dispatch emails automatically.

- Agents are ephemeral (wake, do work, exit)
- Safety limits: max turns per wake, max dispatches per branch per day
- PID-based locking prevents concurrent agents per branch
- Failed agents trigger bounce emails back to sender

## Architecture

Follows the standard AIPass 3-layer pattern:

```
ai_mail/
├── apps/
│   ├── ai_mail.py          # Entry point (auto-discovers modules)
│   ├── modules/
│   │   ├── email.py        # Send, inbox, view, reply, close, contacts
│   │   ├── dispatch.py     # Dispatch status, daemon, wake
│   │   └── branch_ping.py  # Branch health monitoring
│   └── handlers/
│       ├── email/           # Delivery, formatting, inbox ops, purge, reply
│       ├── dispatch/        # Daemon, wake, dispatch_monitor, status
│       ├── registry/        # Branch registry read/update/load
│       ├── users/           # Branch detection, user lookup
│       ├── json_utils/      # JSON I/O helpers (load_json, save_json)
│       ├── monitoring/      # Memory health, error tracking
│       ├── notify.py        # Desktop notifications (dbus)
│       └── central_writer.py # Registry status aggregation
```

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and display formatting
- `aipass.drone` — Command routing and `@branch` resolution
- Python stdlib (`pathlib`, `json`, `argparse`, `importlib`)

### Provides To
- All modules — inter-branch messaging (send/receive/reply/close)
- Dispatch system — autonomous task execution via `--dispatch` flag
- Branch contacts — address book for `@branch` routing

---

*Last Updated: 2026-03-24*
