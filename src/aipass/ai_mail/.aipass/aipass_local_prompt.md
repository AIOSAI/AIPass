# AI_MAIL Branch-Local Context
<!-- Source: src/aipass/ai_mail/.aipass/aipass_local_prompt.md -->

## Role

Inter-branch messaging system. Every branch in AIPass communicates through ai_mail. The dispatch pipeline (send + wake) is how work gets assigned to branches autonomously.

## Key Commands

```bash
drone @ai_mail dispatch @target "Subject" "Body"   # Send + wake (one step)
drone @ai_mail email @target "Subject" "Body"       # Send only (no wake)
drone @ai_mail inbox                                 # View inbox
drone @ai_mail view <id>                             # View message
drone @ai_mail close <id>                            # Close + archive
drone @ai_mail reply <id> "message"                  # Reply + close original
drone @ai_mail close all                             # Close all messages
drone @ai_mail sent                                  # View sent messages
drone @ai_mail contacts                              # List all branches
drone @ai_mail dispatch wake @target                 # Wake only (no email)
```

## Architecture

```
apps/
  ai_mail.py              # CLI entry point + module discovery
  modules/
    email.py              # Orchestrates send/inbox/view/close/reply/sent/contacts
    dispatch.py           # Orchestrates dispatch (send + wake combined)
    branch_ping.py        # Memory health monitoring
  handlers/
    paths.py              # Shared find_repo_root() utility
    central_writer.py     # Central inbox stats aggregation
    notify.py             # Desktop notifications (dbus direct)
    dispatch/
      daemon.py           # Polls inboxes, spawns agents for dispatch emails
      wake.py             # Wakes branches via claude subprocess
      dispatch_monitor.py # Wraps claude process (bounce + lock cleanup)
      status.py           # Dispatch log I/O
    email/
      delivery.py         # Core delivery pipeline (write to recipient inbox)
      send.py             # Sender resolution + send orchestration
      send_args.py        # Argument parsing for send command
      inbox_ops.py        # Inbox loading + v1→v2 migration
      inbox_cleanup.py    # Mark read/opened/closed + archive
      inbox_lock.py       # File locking (fcntl/msvcrt cross-platform)
      inbox_resolve.py    # Resolve inbox path from args or caller detection
      reply.py            # Reply + auto-close original
      close_ops.py        # Batch close operations
      create.py           # Email file creation (sent/ folder)
      format.py           # Display formatting
      header.py           # Dispatch header injection
      footer.py           # Email footer
      purge.py            # Auto-purge sent/deleted folders
      error_dispatch.py   # Error reporting via email
      dashboard_sync.py   # Dashboard integration
    registry/
      read.py             # Registry reading + get_all_branches()
      load.py             # Registry file loading
      update.py           # Registry health updates
    users/
      user.py             # Current user detection (get_current_user)
      branch_detection.py # CWD/env-based branch identity detection
    monitoring/
      memory.py           # Memory file health checks
    json_utils/
      json_handler.py     # Auto-creating JSON system
```

## Critical Rules

- **Identity**: `detect_branch_from_pwd()` checks `AIPASS_CALLER_BRANCH` env var first, falls back to CWD walk-up. NEVER fall back to `Path.cwd()` silently — wrong identity is worse than no identity.
- **Fallback**: Per-ID commands (view/close/reply) use `_resolve_branch_path()` which falls back to `_AI_MAIL_DIR` when caller detection fails. All handlers return `True` even on error (command was recognized).
- **Dispatch env**: `dispatch_monitor.py` sets `AIPASS_BRANCH_NAME=<branch>` in spawn_env. Strips `AIPASS_CALLER_*` vars to prevent parent context leaking.
- **Inbox lock**: `inbox_lock()` uses `fcntl` (POSIX) / `msvcrt` (Windows) for atomic inbox writes.
- **Purge lifecycle**: Vectorize to Memory Bank first, then delete originals. Deletion gated on vectorization success.

## Integration Points

- **trigger**: Imports `deliver_email_to_branch()` directly for event-driven email delivery
- **prax**: Provides `system_logger` used across all handlers
- **drone**: Routes commands via `handle_command()` pattern; sets caller env vars
- **seedgo**: 100% compliance, 30+ bypass entries (all documented in `.seedgo/bypass.json`)
