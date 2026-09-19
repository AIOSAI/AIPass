[← Back to AIPass](../../../README.md)

# AI_MAIL

**Purpose:** Inter-agent messaging for AIPass. A file-based mail system that lets citizens send, receive and resolve messages at `@branch` addresses, and a dispatch pipeline that hands work over by waking the recipient. No SMTP, no external service — JSON files and symbolic routing.
**Module:** `aipass.ai_mail`
**Version:** 2.0.0
**Created:** 2025-11-08

---

## Quick Start

```bash
drone @ai_mail inbox                                # What is waiting for you
drone @ai_mail view <id>                            # Read it (marks it opened)
drone @ai_mail reply <id> "message"                 # Answer, close and archive
drone @ai_mail email @target "Subject" "Body"       # Send, wake nobody
drone @ai_mail dispatch @target "Subject" "Body"    # Send and wake the recipient
```

---

## What It Does

- **Delivers mail between citizens.** One writer, one lock, one id per message: every send
  lands in the recipient's mailbox through the same pipeline, whoever called it.
- **Hands work over.** A dispatch is a send plus a wake — the recipient's agent starts,
  reads the mail, does the work and replies, and the reply closes the row that opened when
  the dispatch was sent.
- **Says who is speaking.** Sender identity is resolved from the caller's own environment
  and the registry, never guessed from a working directory, because a wrong identity is
  worse than no identity.
- **Refuses honestly.** A cross-project address, an unverifiable sender or a blocked target
  gets a named refusal with a reason, not a silent drop and not a fallback delivery.
- **Leaves a record.** Deliveries, wakes and completions are written to the notification
  feed and the append-only dispatch register, so what happened is readable after the
  session that did it is gone.

Not a task runner: this branch delivers messages about work, and never decides another
branch's work for it.

---

## Live Inventory

The list of modules, verbs and flags is **generated from the code that runs them**, so it
is not written down on this page and cannot go stale here:

- `drone @ai_mail` — the self-map: the discovered modules and what this branch is.
- `drone @ai_mail --help` — the full command surface. Each module answers for its own
  verbs: `drone @ai_mail email --help` and `drone @ai_mail dispatch --help`.

---

## How To Reach Me

- Mail: `drone @ai_mail email @ai_mail "Subject" "Body"` — delivery you cannot explain, a
  refusal you believe is wrong, an address that resolves to the wrong citizen.
- A message that arrived at the wrong mailbox, or never arrived, is a defect here. Say which
  sender, which recipient and roughly when; the feed and the register keep enough to
  reconstruct it.
- Need work done by another branch? `dispatch` wakes them, `email` does not. A sleeping
  agent never reads plain mail.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of this branch's own
help output rots the next time a verb or a flag is added. The generated surface is the one
above under **Live Inventory**, and it is always current. The contract that surface obeys —
what each exit code means, and why a help flag explains instead of executing — is in
[docs/cli_contract.md](docs/cli_contract.md).

---

## Architecture

The standard AIPass three-layer shape. `apps/ai_mail.py` is a thin entry point that
discovers modules and routes to the first one claiming a command. `apps/modules/` holds the
orchestration, one module per surface: `email` (inbox, view, reply, close, contacts),
`email_send` (direct, interactive and broadcast sending) and `dispatch` (send-plus-wake,
register, status, daemon). `apps/handlers/` holds the implementation, grouped one directory
per concern: `email/` for the delivery pipeline and the mailbox verbs, `dispatch/` for the
wake path, the monitor, the register, completion reports and the session pointer,
`registry/` and `users/` for address and identity resolution, `cli/` for the help-flag
predicate, and `json/` for the fleet's shared json service. `paths.py`, `notify.py` and
`central_writer.py` sit beside them as the shared root helpers.

The directory tree lives in this branch's own prompt
(`.aipass/aipass_local_prompt.md`) — one place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per handler group, each small enough for one read:

| Doc | What it covers |
|---|---|
| [docs/README.md](docs/README.md) | What belongs in `docs/` and what belongs in a local scratch directory |
| [docs/wake_pipeline.md](docs/wake_pipeline.md) | The wake path end to end: the spawn lanes, safety limits, the scheduled lane, unattended wakes, the Fable grant, and the recipient dashboard refresh |
| [docs/wake_lanes.md](docs/wake_lanes.md) | The admin lane, the cross-project bridge, `@all` scope, out-of-scope addresses, the reply return path and the daemon |
| [docs/dispatch_register_and_feed.md](docs/dispatch_register_and_feed.md) | The append-only register, completion reports, crash coverage and its latency, and the notification feed |
| [docs/sending_and_delivery.md](docs/sending_and_delivery.md) | Listing rules, what a broadcast costs, repeat signals (`upsert_key`), the two message ids, refused sends and the mail lifecycle |
| [docs/identity_and_boundaries.md](docs/identity_and_boundaries.md) | Sender identity, the verified-caller rail, cross-project mail and wakes, the import guard and the case-exact registry walk |
| [docs/cli_contract.md](docs/cli_contract.md) | Help flags that explain instead of executing, the exit codes, output ordering, and why interactive send needs a terminal |
| [docs/s84_multiline_reply_truncation.md](docs/s84_multiline_reply_truncation.md) | The multiline reply truncation defect and its fix |

---

## Integration Points

### Depends On
- `aipass.prax` — logging via `system_logger`, and the dashboard refresh a wake runs for the
  recipient before it spawns
- `aipass.cli` — console output and display formatting
- `aipass.drone` — broker-socket IPC for a sandboxed dispatch child. This is the only
  `aipass.drone` import in the package: `@branch` resolution is internal, and "drone routes
  commands to us" describes how `drone @ai_mail …` invokes this branch from outside, not a
  dependency
- `aipass.trigger` — `trigger.fire()`, in-process only, for mail and dispatch events
- Python stdlib (`pathlib`, `json`, `importlib`, `subprocess`, `fcntl`) — argument parsing is
  hand-rolled in `apps/handlers/email/send_args.py`, not `argparse`

### Provides To
- **Every branch** — inter-branch messaging: send, receive, reply, close
- **The dispatch system** — autonomous hand-over of work, and the register that says what is
  outstanding
- **`aipass.trigger`** — `deliver_email_to_branch()`, imported directly for event-driven
  delivery
- **BAUD** — the notification feed at `.aipass/notifications.jsonl`, for delivery, wake and
  dispatch events

---

**Last Updated:** 2026-09-15

---
[← Back to AIPass](../../../README.md)
