[← Back to AIPass](../../../README.md)

# AI_MAIL

**Purpose:** Inter-agent messaging for AIPass. File-based email system that lets agents send, receive, and process messages using `@branch` addresses. No SMTP, no external services — just JSON files and symbolic routing.
**Module:** `aipass.ai_mail`
**Created:** 2025-11-08
**Last Updated:** 2026-08-11

---

**Status:** Operational | **Seedgo:** 100% | **Tests:** 924 pass | **Battle Tested:** S62

## Quick Start

```bash
# Check your inbox
drone @ai_mail inbox

# View a message
drone @ai_mail view <id>

# Reply and close
drone @ai_mail reply <id> "your message"

# Send mail to another branch
drone @ai_mail email @target "Subject" "Body"

# Dispatch (send + wake target agent)
drone @ai_mail dispatch @target "Subject" "Body"
```

## Commands

```bash
# Dispatch (send + wake in one step)
drone @ai_mail dispatch @target "Subject" "Body"          # Send dispatch email + wake
drone @ai_mail dispatch @target "Subject" "Body" --fresh  # Send + fresh wake (new session)
drone @ai_mail dispatch wake @target                      # Wake only (no email)

# Send mail (no wake)
drone @ai_mail email @target "Subject" "Body"             # Send to one branch
drone @ai_mail email @all "Subject" "Body"                # Broadcast to all branches
drone @ai_mail email @target "Subj" "Body" --from @spawn  # Explicit sender override

# Read mail
drone @ai_mail inbox                                      # List all emails (new + opened)
drone @ai_mail view <id>                                  # View email (marks as opened)
drone @ai_mail view latest                                # View most recent email

# Resolve mail
drone @ai_mail reply <id> "message"                       # Reply + close + archive original
drone @ai_mail close <id>                                 # Close single email
drone @ai_mail close <id1> <id2> <id3>                    # Close multiple emails
drone @ai_mail close all                                  # Close all emails

# Other
drone @ai_mail sent                                       # View sent messages
drone @ai_mail contacts                                   # List all known branches
drone @ai_mail --help                                     # Full help
```

## Listing Rules

Bulk listings (`inbox`, `sent`) must never hide a message — an invisible new mail is
the worst failure shape mail has, because the sender believes it was delivered.

- **Newest-end truncation** — `delivery.py` inserts new mail at index 0, so listings
  slice `messages[:20]` (the newest) and then reverse for oldest-first reading order.
  Reversing before slicing kept the oldest 20 and hid every new arrival in a busy inbox.
- **`view latest`** reads `messages[0]`, not `[-1]`, for the same reason.
- **Markup escaping** — subject, preview, sender and recipient are sender-controlled and
  are escaped in `format.py`. Unescaped, `[dim]` silently swallows text and `[/rc]`
  raises `MarkupError` that aborts the whole listing.
- **Fail honest** — a row that still cannot render is reprinted raw behind a marker, and
  an unreadable `sent/` file lists as a placeholder. Never a silent skip.

## Repeat Signals (`upsert_key`)

A signal that repeats — the same WARNING firing every poll — must occupy **one**
inbox slot with a climbing counter, not one slot per repeat. Senders that repeat
give the send a stable `upsert_key`:

```bash
drone @ai_mail email @devpulse "WARNING: disk 97%" "body" --upsert-key warn:disk
```

- **Match** = same `from` **and** same `upsert_key` **and** `status != closed`.
  On a match the existing message is rewritten in place: fresh subject + body,
  `last_updated` stamped, `updates` incremented.
- **The id and the read status are preserved.** Opened stays opened, new stays
  new. A repeat is the same demand for attention, not a new one — so an update
  never flips a message back to unread, never fires a desktop notification, and
  never wakes or dispatches anything (`auto_execute` is forced off on update).
- **No match** — first send, or the previous one was closed/archived — creates an
  ordinary new message at `updates: 1`. **Closing re-arms the signature**: the
  next send starts a fresh message, which is how a resolved warning comes back.
- **Visibility** — `inbox` prints `x3` on the row, `view` prints
  `Updates: 3 (last: <timestamp>)` in the header. One message, N stated.
- `upsert_key=None` (the default) is plain delivery, unchanged for every caller.
- Not supported for `@all` broadcasts — refused loudly rather than stacking N.

Delivery-layer callers (e.g. `@trigger`, which imports `deliver_email_to_branch`
directly) pass `upsert_key=` as a keyword or set `email_data["upsert_key"]`;
both work. The outcome comes back as `email_data["upsert_action"]`
(`"created"` / `"updated"`), so a caller can log the difference without
re-reading the inbox.

## Exit Codes

`0` success · `1` unroutable command · `2` routed but failed.

Handlers return `True` for "I recognised this command", which is not "it worked".
`error()` sets a process failure flag that `main()` maps through `resolve_exit()`, so a
failed delivery or an invalid reply_path exits nonzero instead of reporting success to
the caller's script.

## Email Lifecycle

Messages follow a 3-state model:

```
new → opened → closed
```

- **new** — Delivered to inbox, never viewed
- **opened** — Viewed by recipient, awaiting action
- **closed** — Replied or dismissed, archived automatically

Each branch's mailbox lives at `<branch_path>/.ai_mail.local/inbox.json`. Sent copies go to `.ai_mail.local/sent/`. File locking (`fcntl`/`msvcrt`) protects concurrent inbox writes.

## Dispatch System

The `dispatch` command sends an email and wakes the target branch in one step. Dispatch emails carry `auto_execute: true` and a task header, signaling the target agent to process them as work items.

### Wake Pipeline

1. `dispatch.py` orchestrates: send email via `send_to_single()`, then wake via `wake_branch()`
2. `wake.py` resolves the branch from the registry, checks `citizen_class` (managers are mail-only — wake skips), finds the `claude` binary, spawns a subprocess
3. `dispatch_monitor.py` wraps the claude process with safety features:
   - **Startup health check** — monitors JSONL session files for 90s, kills if no activity
   - **Auto-retry** — 3 strikes: attempt 1+2 resume, attempt 3 fresh (new session)
   - **Bounce email** — on final failure, sends error report back to sender
   - **Lock cleanup** — removes `.dispatch.lock` when agent exits
   - **Wake-back** — on agent exit, wakes the original sender so they can process the result. Wake-back sessions carry an empty sender, so chains terminate at the original dispatcher

### Safety Limits

- PID-based locking prevents concurrent agents per branch (`.dispatch.lock`)
- Max turns per wake, max dispatches per branch per day
- `WAKE_BLOCKLIST` protects `@devpulse` from cross-branch manual wakes
- **Manager structural block** — branches with `citizen_class: "manager"` in their passport (e.g. `@devpulse`) are unwakeable on all wake paths. Mail delivers, wake skips
- **Self-wake guard** — if sender equals target, wake-back is skipped (prevents self-loops)
- **Chain termination** — wake-back sessions carry an empty sender, so the chain always stops at the original dispatcher
- `dispatch_monitor.py` strips `AIPASS_CALLER_*` env vars to prevent parent context leaking into agent identity
- `AIPASS_BRANCH_NAME` env var set in spawn_env for CWD-independent identity

### Daemon

The polling daemon (`daemon.py`) watches inboxes for `auto_execute` dispatch emails and spawns agents automatically. It also runs the AIPASS-TEST token protocol: `scan_and_ack_test_emails()` intercepts ping-test messages and auto-replies with "ack" before dispatch processing.

## Sender Identity

Branch identity detection follows a priority chain in `detect_branch_from_pwd()`:

1. `AIPASS_CALLER_BRANCH` env var (set by drone router from passport or `AIPASS_BRANCH_NAME`)
2. Contacts address book lookup (fastest path for registered branches)
3. Registry lookup by name
4. `AIPASS_CALLER_CWD` / `Path.cwd()` walk-up to find `.trinity/passport.json`
5. Registry lookup by path

If all fail, detection returns `None` and the operation fails loudly. Wrong identity is worse than no identity.

The `--from @branch` flag on send/email commands provides an explicit sender override for callers outside branch directories.

### Address Derivation Hazard

A branch with no explicit `email` field in the registry gets one derived by
`registry/read.py:_derive_email_from_branch_name()`, which splits the name and
keeps **one token**:

| Branch name | Rule | Address |
|---|---|---|
| `AIPASS.admin` | after the dot | `@admin` |
| `Glass House` | first word | `@glass` |
| `AIPASS-HELP` | after the hyphen (AIPASS prefix only) | `@help` |
| `flight-deck` | before the hyphen | `@flight` |

So a multi-word branch name silently loses everything after the first token, and
resolution downstream is exact-match (`delivery.py`, `contacts.py`) with no fuzzy
or prefix fallback anywhere — a truncated address never self-corrects, it just
fails to route. **Set an explicit `email` in the registry for any branch whose
name contains a space, dot or hyphen.**

## Cross-Project Email

External projects (outside the AIPass repo) can send to AIPass branches. On delivery, `delivery.py` stores a `reply_path` on the message (the sender's `inbox.json` path, resolved from `AIPASS_CALLER_CWD`). Replies use `_deliver_via_reply_path()` to write directly to the external inbox without needing registry lookup.

The contacts system (`contacts.py`) maintains an address book at `.ai_mail.local/contacts.json`, auto-registering branches on every send/receive. This enables fast sender detection for known branches without CWD walking or registry lookups.

## Architecture

Follows the standard AIPass 3-layer pattern:

```
ai_mail/
├── apps/
│   ├── ai_mail.py              # Entry point (auto-discovers modules)
│   ├── modules/
│   │   ├── email.py            # Inbox, view, reply, close, contacts, routing
│   │   ├── email_send.py       # Send orchestration (direct, interactive, broadcast)
│   │   └── dispatch.py         # Dispatch send+wake, status, daemon control
│   └── handlers/
│       ├── email/
│       │   ├── delivery.py     # Core delivery pipeline (write to recipient inbox)
│       │   ├── send.py         # Sender resolution + send helpers
│       │   ├── send_args.py    # Argument parsing for send command
│       │   ├── inbox_ops.py    # Inbox loading + v1→v2 migration
│       │   ├── inbox_cleanup.py # Mark opened/closed + archive
│       │   ├── inbox_lock.py   # File locking (fcntl/msvcrt cross-platform)
│       │   ├── inbox_resolve.py # Resolve inbox path from args or caller
│       │   ├── reply.py        # Reply + auto-close original
│       │   ├── close_ops.py    # Batch close operations
│       │   ├── contacts.py     # Address book for branch routing
│       │   ├── create.py       # Email file creation (sent/ folder)
│       │   ├── format.py       # Display formatting
│       │   ├── header.py       # Dispatch header injection
│       │   ├── footer.py       # Email footer
│       │   ├── purge.py        # Auto-purge sent/deleted folders
│       │   ├── error_dispatch.py # Error reporting via email
│       │   └── dashboard_sync.py # Dashboard integration
│       ├── dispatch/
│       │   ├── daemon.py       # Polls inboxes, spawns agents for dispatch emails
│       │   ├── wake.py         # Wakes branches via claude subprocess
│       │   ├── dispatch_monitor.py # Wraps claude process (bounce + lock cleanup)
│       │   ├── status.py       # Dispatch log I/O
│       │   └── test_token.py   # AIPASS-TEST ping protocol (auto-ack)
│       ├── registry/
│       │   └── read.py         # Registry reading + get_all_branches()
│       ├── users/
│       │   ├── branch_detection.py # CWD/env-based branch identity detection
│       │   └── user.py         # Current user detection (get_current_user)
│       ├── json_utils/
│       │   └── json_handler.py # Auto-creating JSON system
│       ├── paths.py            # Shared find_repo_root() utility
│       ├── notify.py           # Desktop notifications (dbus direct)
│       └── central_writer.py   # Central inbox stats aggregation
└── tests/                      # 924 tests across 31 test files
    ├── conftest.py             # Shared fixtures (mock_logger, mock_json_handler)
    ├── test_daemon.py          # Daemon config, state, kill switch, dispatch check
    ├── test_dispatch_monitor.py # Monitor safety features, env stripping
    ├── test_dispatch_status.py # Log I/O, age calculation
    ├── test_dispatch_watchdog.py # Watchdog auto-spawn
    ├── test_wake.py            # Branch resolution, PID checks, lock files
    ├── test_wake_blocklist.py  # Wake protection for @devpulse
    ├── test_delivery.py        # Inbox migration, private branches, pipeline
    ├── test_send_identity.py   # Sender identity chain (36 tests)
    ├── test_user_paths.py      # Mailbox path resolution (13 tests)
    ├── test_contacts.py        # Address book operations
    ├── test_inbox_ops.py       # Inbox loading + migration
    ├── test_registry_read.py   # Registry parsing + branch lookup
    ├── test_upsert.py          # upsert_key repeat-signal collapsing (40 tests)
    ├── test_central_writer.py  # Central stats aggregation
    ├── test_cli_routing.py     # CLI routing + help/version
    ├── test_json_handler.py    # JSON I/O helpers
    ├── test_notify.py          # Desktop notification dbus calls
    └── test_paths.py           # find_repo_root() utility
```

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and display formatting
- `aipass.drone` — Command routing and `@branch` resolution
- `aipass.trigger` — `trigger.fire()` for `email_dispatched` events
- Python stdlib (`pathlib`, `json`, `argparse`, `importlib`, `subprocess`, `fcntl`)

### Provides To
- **All branches** — inter-branch messaging (send/receive/reply/close)
- **Dispatch system** — autonomous task execution via `auto_execute` emails
- **Branch contacts** — address book for `@branch` routing
- **trigger branch** — `deliver_email_to_branch()` imported directly for event-driven delivery
- **Desktop** — dbus notifications for delivery, wake, completion events

## Known Issues

- **DPLAN-0138**: Inbox backdoor audit identified 2 write path classes — ad-hoc direct writes (detectable by non-UUID ID format) and `_deliver_via_reply_path()` bypass (no lock, no notification). Fix pending.
- **Caller detection**: `BRANCH DETECTION FAILED` when callers don't set `AIPASS_CALLER_BRANCH` (low severity, caller-side fix — use `--from` flag)
- **Cross-branch writes**: ai_mail not in trusted cross-writers list for `system-pr`

---

[← Back to AIPass](../../../README.md)
