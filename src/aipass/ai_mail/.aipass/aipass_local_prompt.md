# AI_MAIL Branch-Local Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- Source: src/aipass/ai_mail/.aipass/aipass_local_prompt.md -->
<!-- Cap: 9,000 chars (hooks BRANCH_CHAR_BUDGET). Breadcrumbs only — the depth lives in docs/, the face in README.md. -->

## Role

Inter-branch messaging. Every citizen speaks through ai_mail: `email` delivers, `dispatch`
delivers and wakes the recipient so work is handed over in one step.

## Key Commands

```bash
drone @ai_mail dispatch @target "Subject" "Body"   # Send + wake (hand work over)
drone @ai_mail email @target "Subject" "Body"      # Send only (no wake)
drone @ai_mail inbox                               # What is waiting
drone @ai_mail view <id>                           # Read it (marks opened)
drone @ai_mail reply <id> "message"                # Answer + close + archive
drone @ai_mail dispatch register                   # What is outstanding, what is overdue
drone @ai_mail --help                              # The generated surface — never retyped
```

## Architecture

```
apps/
  ai_mail.py                  # Entry point — discovers modules, routes commands
  modules/
    email.py                  # inbox, view, reply, close, sent, contacts
    email_send.py             # Send orchestration: direct, interactive, broadcast
    dispatch.py               # Dispatch send+wake, register, status, daemon control
  handlers/
    paths.py                  # find_repo_root() + the case-exact registry walk
    notify.py                 # Notification feed writer (JSONL; BAUD reads it)
    central_writer.py         # Central inbox stats aggregation
    cli/
      help_flags.py           # wants_help() — whole-sequence help detection, pure predicate
    dispatch/
      wake.py                 # The wake path: gates, model resolution, three spawn lanes
      wake_dashboard.py       # Refreshes the RECIPIENT's dashboard before the spawn
      dispatch_monitor.py     # Wraps the claude process (bounce, lock cleanup, sandbox)
      daemon.py               # Polls inboxes, spawns agents for dispatch emails
      register.py             # Append-only dispatch register — open/close/outstanding
      report.py               # Completion report: emails_sent, memories_edited, duration
      session_pointer.py      # Durable resume-session pointer
      status.py               # Dispatch log I/O
      test_token.py           # AIPASS-TEST ping protocol (auto-ack)
    email/
      delivery.py             # Core delivery pipeline — the one writer into a mailbox
      send.py                 # Sender resolution + send orchestration
      send_args.py            # Hand-rolled argument parsing (never argparse)
      inbox_ops.py            # Inbox loading + v1→v2 migration
      inbox_cleanup.py        # Mark opened/closed + archive
      inbox_lock.py           # File locking (fcntl POSIX / msvcrt Windows)
      inbox_resolve.py        # Resolve inbox path from args or caller detection
      reply.py                # Reply + auto-close original
      close_ops.py            # Batch close
      contacts.py             # Address book for @branch routing
      create.py               # Email file creation (sent/ folder)
      format.py / header.py / footer.py   # Display, dispatch header, footer
      purge.py                # Auto-purge sent/deleted folders
      error_dispatch.py       # Error reporting by mail
    registry/
      read.py                 # Registry reading + get_all_branches()
    users/
      branch_detection.py     # CWD/env-based branch identity detection
      verified_caller.py      # Verified-caller rail + the admin verdict
      user.py                 # Current user detection
    json/
      json_handler.py         # The fleet's one json service, bound here (DPLAN-0325)
tests/                        # One module per concern; new test files are gated fleet-wide
docs/                         # The depth — indexed from README.md
```

## Critical Rules

- **Identity**: `detect_branch_from_pwd()` reads `AIPASS_CALLER_BRANCH` first, then walks up
  from the CWD. NEVER fall back to `Path.cwd()` silently — a wrong identity is worse than no
  identity. An assigned name is attribution, not a credential: a verified caller needs the
  passport and the registry row to agree.
- **Fallback**: per-id commands (view/close/reply) use `_resolve_branch_path()`, which falls
  back to `_AI_MAIL_DIR` when caller detection fails. Handlers return `True` even on error —
  that bool means "command recognised", not "it worked".
- **Dispatch env**: `dispatch_monitor.py` sets `AIPASS_BRANCH_NAME=<branch>` in the spawn env
  and strips `AIPASS_CALLER_*` — the parent's context must not leak into the child.
- **Inbox lock**: every mailbox write goes through `inbox_lock()`; a second writer waits.
- **Fail-open exists in exactly one place**: the recipient dashboard refresh on the wake
  path. Everywhere else, refuse and name the reason.
- **Purge lifecycle**: vectorize into the Memory Bank first, then delete. Deletion is gated
  on vectorization succeeding.
- **Managers are mailed, never dispatched** (`citizen_class: manager`, e.g. @devpulse, which
  is also on `WAKE_BLOCKLIST`). A reply never wakes; a wake-back does.

## Gotchas

- `dispatch status` can print "No dispatches recorded yet." while work is running — it reads
  a different log. `dispatch register` is the trustworthy view (APLAN-0006).
- `--help` anywhere in a command sequence EXPLAINS and never executes; that is a contract,
  pinned by tests.
- The two ids: a message carries its own id and the sender's `sent_id`. Echo the message's
  own id — `view latest` once printed "ID: latest".
- A broadcast costs what it delivers: it fans out per recipient and each delivery is its own
  write. `--upsert-key` is the way to repeat a signal without stacking new mail.
- The registry glob is re-checked in Python because a case-insensitive filesystem answers
  `*_REGISTRY.json` with `*_registry.json` — counter files are not citizens.

## Integration Points

- **prax** — `system_logger` everywhere, and the dashboard refresh the wake path calls.
- **trigger** — imports `deliver_email_to_branch()` directly for event-driven delivery.
- **drone** — routes commands in via `handle_command()`; the broker socket is the only
  `aipass.drone` import here.
- **seedgo** — audited like every branch; documented exceptions live in `.seedgo/bypass.json`.
