[← Back to AIPass](../../../README.md)

# AI_MAIL

**Purpose:** Inter-agent messaging for AIPass. File-based email system that lets agents send, receive, and process messages using `@branch` addresses. No SMTP, no external services — just JSON files and symbolic routing.
**Module:** `aipass.ai_mail`
**Created:** 2025-11-08
**Last Updated:** 2026-08-12

---

**Status:** Operational | **Seedgo:** 100% | **Tests:** 1048 pass | **Battle Tested:** S62

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
- **`sent` sorts by mtime, not filename.** The folder holds two naming schemes —
  `create.py` writes `<YYYYMMDD_HHMMSS>_<subject>.json`, `reply.py` writes `<id>.json`
  — and in a filename sort every hex id outranks every digit, so a mailbox with 20
  replies in it hid every recent send behind them.
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
  never flips a message back to unread, never writes a notification event, and
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

## Notification Feed

Desktop toasts are retired (Patrick's ruling, 2026-08-11) — no D-Bus, no
notify-send, no fallback that still toasts. `notify.py` appends notification
events to a shared JSONL feed that BAUD's notification bell reads.

```
path : <repo root>/.aipass/notifications.jsonl
line : {"ts": ISO8601, "kind": "mail"|"wake"|"dispatch"|"system",
        "title": str, "body": str, "source": branch name (no @)}
```

- **Append-only, one object per line.** Readers never write; the feed carries no
  read flags — BAUD tracks read state locally.
- **Four writers, four kinds** — `delivery.py` (`mail`), `wake.py` (`wake`),
  `daemon.py` (`dispatch`, spawn), `dispatch_monitor.py` (`dispatch`, completion).
  An off-contract `kind` is recorded as `system` and the substitution is logged,
  never silently accepted.
- **Concurrency** — those four are separate processes. Each append is a single
  `O_APPEND` write; the trim is a read-modify-write. Both take the same advisory
  lock (`.notifications.lock`, a sibling file — the trim replaces the feed inode),
  so an append can never land inside a trim and be dropped.
- **Trim policy** — past 400 lines the feed drops to its newest 200. A bell shows
  recent events; older ones have no reader.
- **Fail honest** — a failed feed write is logged and returns `False`. Nothing
  falls back to a toast.

Tests point `FEED_PATH` at a tmp file via an autouse conftest fixture: four
call sites write feed lines as a side effect, and an unguarded suite run
appends fake dispatch events to the real feed BAUD renders.

## Refused Sends

The sent record is written **before** delivery is attempted, because delivery needs the
loaded email data. So a send the cross-project fence turns away has already left a file
on disk. `send.py` restamps it:

```
status          : "refused"
refused_reason  : the delivery error, verbatim
refused_at      : when the refusal was recorded
```

- **Restamped, never deleted.** The attempt is evidence — a sender who saw an error must
  still be able to cite what they tried to send and to whom.
- **Visible as refused.** `sent` prints `REFUSED` on the row and `Not delivered: <reason>`
  under the subject. Identical rendering is what let a cross-project sender read
  "it's in my sent folder" as proof it arrived.
- **Broadcasts** carry one record for N recipients: refused only when *zero* were
  delivered. A partial broadcast is a real send.

## Exit Codes

`0` success · `1` unroutable command · `2` routed but failed.

Handlers return `True` for "I recognised **and ran** this command", which is not "it
worked". `error()` sets a process failure flag that `main()` maps through
`resolve_exit()`, so a failed delivery or an invalid reply_path exits nonzero instead of
reporting success to the caller's script.

Returning `False` for a failure is not a smaller mistake — it is a different bug:
`route_command()` walks modules until one returns `True`, so a handler that ran a send,
failed, and returned `False` sent the router on to the **next** module, which ran the
same send again and then printed `Unknown command: email` over a command it had just
executed. Two sent records, two error lines, one contradiction, exit 1 instead of 2.

Each module answers only for the commands it owns (`email_send.COMMANDS`,
`dispatch` for the dispatch module). A module that answers to any command name it is
handed will re-run its own work under someone else's.

### Output ordering

Progress goes to stdout and failures to stderr, and `drone` captures each stream whole
and replays **stdout first**. A progress line printed before an operation therefore
surfaces *below* the failure it preceded. Announce outcomes, not intent, on any path
that can fail — `dispatch` no longer prints `Sending dispatch email to ...` ahead of a
send that the fence may refuse.

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
2. `wake.py` resolves the branch from the registry, checks `citizen_class` (managers are mail-only — wake skips, unless the scheduled lane below applies), finds the `claude` binary, spawns a subprocess
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
- **Manager structural block** — branches with `citizen_class: "manager"` in their passport (e.g. `@devpulse`) are unwakeable on the dispatch and manual paths. Mail delivers, wake skips. The three exceptions (scheduled, admin, @daemon self-wake) are named below
- **Self-wake guard** — if sender equals target, wake-back is skipped (prevents self-loops)
- **Chain termination** — wake-back sessions carry an empty sender, so the chain always stops at the original dispatcher
- `dispatch_monitor.py` strips `AIPASS_CALLER_*` env vars to prevent parent context leaking into agent identity
- `AIPASS_BRANCH_NAME` env var set in spawn_env for CWD-independent identity

### Scheduled Lane (`scheduled=True`)

`wake_branch()` takes a keyword-only `scheduled` flag — the opt-in for a wake fired
by a clock rather than by a person (DPLAN-0287, the 5am maintenance rotation).

```python
from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

status, ok = wake_branch("@devpulse", custom_message=prompt, sender="@daemon", scheduled=True)
```

| Target | `scheduled=False` (default) | `scheduled=True` |
|---|---|---|
| manager, sender `@daemon` | interactive tmux session | **headless via `dispatch_monitor`** |
| manager, any other sender | mail only, wake skipped | headless via `dispatch_monitor` |
| non-manager | monitor pipeline | monitor pipeline (identical) |
| on `WAKE_BLOCKLIST` | unchanged per path | **refused, never spawned** |

- **Why headless.** The interactive spawn never touches `dispatch_monitor`, so it gets
  no `CLAUDE_CODE_AUTO_COMPACT_WINDOW` pin, no bounce email and no lock cleanup — an
  unattended 5am session would inherit its model's native window with nobody watching.
  Routing the scheduled lane through the monitor is what makes the 350k pin apply.
- **The blocklist is checked before the passport read.** A missing or corrupt
  `passport.json` must never be the reason a blocked target gets spawned. Refusal is a
  named `blocklist` fail step, not a bare `False`.
- **Default `False` changes nothing.** Manual manager self-wakes stay interactive tmux;
  inbox-sweep and `@daemon`'s `run.py` don't pass the param, so they are untouched.
- **Reading the outcome** — `status.find_step("scheduled")` is present only for the
  headless lane; the interactive spawn names its tmux session in the `spawn` step.

### Admin Lane (`admin=True`)

Patrick's ruling (DPLAN-0288): @devpulse — and only @devpulse — holds an admin
grant that lets a dispatch wake **manager-class** citizens. `wake_branch` takes a
keyword-only `admin` flag that is an *already-decided verdict*, never a request:

```python
status, ok = wake_branch(target, sender=..., admin=is_admin)
```

- **The check runs in `dispatch.py`, not here.** Leg 1 of the contract needs
  `AIPASS_CALLER_*`, and `wake_branch`'s in-process callers don't carry it — a
  `wake_branch` that verified its own caller would be verifying nobody.
- **Five legs, all or nothing** (FPLAN-0401 THE CONTRACT): verified caller is
  devpulse · cert path resolved from the *registry* entry, never caller-supplied ·
  cert content (`owner`, `type`, `privileges.admin`) · HMAC-SHA256 signature over
  the canonical cert-minus-signature payload · registry `admin: true`.
  `verified_caller.verify_admin_caller()` delegates to @devpulse's reference
  implementation rather than mirroring it — one contract, one home, no drift.
- **Lane dark by default.** The signing key lives at `~/.aipass/admin_grant.key`,
  outside every repo, and does not exist until the ceremony. No key → leg 4 fails
  → today's behavior exactly. An import failure of the reference is *also* dark,
  and a verifier that raises is caught: a privilege path never takes mail down.
- **`WAKE_BLOCKLIST` still refuses.** Admin raises the stakes, not the fence —
  @devpulse stays undispatchable even by a verified admin, checked before the
  passport read alongside the scheduled lane.
- **Non-holders pay nothing.** The verifier only runs when the rail already says
  the caller is the grant holder; everyone else's dispatch is byte-identical, with
  no key read and no file I/O.
- `status.find_step("admin")` marks the lane; when both flags are set the
  scheduled lane wins and reports itself, so a 5am rotation is never logged as an
  admin dispatch.

### Cross-Project Bridge (verified-admin only)

Citizens under `projects/*` (e.g. @baud) sit behind two walls, and phase 5 of
FPLAN-0401 puts one door in each — openable only with the grant:

- **Resolution.** `resolve_branch(email, admin=False)` gains a third step: an
  `admin`-only sweep of `projects/*/*_REGISTRY.json` under the repo root. It runs
  **last**, so a local branch always wins and the sweep is a fallback, never a
  preempt. Left at its default the function behaves exactly as it did before —
  there is no resolution widening for anyone unverified.
- **Delivery.** `_check_cross_project_boundary()` gains a verified-admin
  exemption, and the branch map gains the same sweep. The exemption is checked
  **last**, once a refusal is otherwise certain, so ordinary same-project mail
  never reads the grant.
- **One boolean, no cache.** Both halves consult
  `verified_caller.is_verified_admin_caller()` — rail says holder, then all five
  legs. Deliberately uncached: a per-process cache would keep a revoked grant
  alive until restart, which is failing open. A raising verifier is a refusal.
- **Dark today.** No key → no bridge, end to end: @baud does not resolve and the
  boundary refuses with the same wording as before. Vera-Studio (a separate repo)
  is out of scope — this reads the projects the repo already hosts, and is not a
  multi-root discovery layer.

### Reply Return Path

The bridge opened one-way — admin mail got in, the targets' replies could not get
out (live proof, 2026-08-12: exempted 17:44, refused 17:46). Phase 5b closes it
with a second boundary exemption, narrower than the first:

- **A reply is answering, not initiating.** The referenced message sitting in the
  sender's *own* mailbox is the proof the channel was sanctioned. Initiation
  across projects stays admin-only and inbound-only.
- **`_is_sanctioned_reply(email_data, to_branch)`** allows delivery only when the
  outbound mail carries an `in_reply_to`, that id is present in the sender's
  mailbox, and the destination matches that message's `from` **or** its
  `reply_to`. Both are fields only the *original sender* could have written —
  the replier never picks them, so a new recipient cannot be laundered through a
  reply. Matching `reply_to` as well is required, not generous: `reply.py` routes
  to `reply_to or from`, so a `from`-only exemption would refuse the very replies
  it exists to allow.
- **Inbox-only lookup, mirroring `reply.py`.** `get_email_by_id()` reads the
  inbox, and delivery failure returns *before* the auto-close — so during a real
  reply the original is always still there. Checking anywhere else would accept
  proof `reply.py` itself would not.
- **Fails closed everywhere else:** forged or unknown `in_reply_to`, no mailbox,
  unreadable mailbox, or no `in_reply_to` at all → today's refusal, unchanged.

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

### Verified-Caller Rail

`--from` and `--sender` are **claims, not credentials**. Both land on
`wake_branch(sender=...)`, and that value is not only a bounce address — a
sender in `PRIVILEGED_SENDERS` unlocks a wake lane. Until this rail, any citizen
could run `dispatch @manager --from @daemon` and wake a manager (found by a
@devpulse scout, DPLAN-0288; traced, not executed).

`handlers/users/verified_caller.py` draws the line:

| | claimed identity (`--from` / `--sender`) | verified identity |
|---|---|---|
| source | a CLI string | `AIPASS_CALLER_BRANCH`, else a passport walk up `AIPASS_CALLER_CWD` |
| authors the mail | yes | — |
| gates a privilege | **never** | yes |

- **`resolve_verified_caller()`** — `@branch`, or `""` when unprovable. There is
  deliberately **no `Path.cwd()` fallback**: drone runs a routed module with
  `cwd=<target branch>` and a dispatched agent with `cwd=<its own tree>`, so this
  process's directory says nothing about who called.
- **`sender_claim_refusal(claimed)`** — a reason string when the claim is
  privilege-bearing and doesn't match the verified caller (including when there
  is no caller to match: unprovable is refused, not assumed). Refusal happens
  **before the send**, so a spoof attempt leaves no delivered email behind, and
  exits `2`.
- **`resolve_wake_sender(claimed)`** — verified caller first, the claim only as a
  fallback, which the refusal has already guaranteed is not privilege-bearing.
  So `--from @spawn` from @seedgo's seat still authors the mail as `@spawn` while
  the wake — and therefore wake-back — is attributed to `@seedgo`.
- **`PRIVILEGED_SENDERS`** lives at the boundary that enforces it, because
  `wake_branch` cannot: its in-process callers (@daemon's `run.py`) have no
  caller env and are trusted by import instead. A test scans `wake.py` for
  `sender == "@x"` gates and fails if one is missing from the set.

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
│       ├── notify.py           # Notification feed writer (JSONL, BAUD reads)
│       └── central_writer.py   # Central inbox stats aggregation
└── tests/                      # 1034 tests across 35 test files
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
    ├── test_notify.py          # Notification feed schema, trim, concurrency (23 tests)
    ├── test_refused_sends.py   # Refused-send records + handled-vs-worked routing (25 tests)
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
- **BAUD** — `.aipass/notifications.jsonl` feed for delivery, wake, dispatch events

## Known Issues

- **DPLAN-0138**: Inbox backdoor audit identified 2 write path classes — ad-hoc direct writes (detectable by non-UUID ID format) and `_deliver_via_reply_path()` bypass (no lock, no notification). Fix pending.
- **Caller detection**: `BRANCH DETECTION FAILED` when callers don't set `AIPASS_CALLER_BRANCH` (low severity, caller-side fix — use `--from` flag)
- **Cross-branch writes**: ai_mail not in trusted cross-writers list for `system-pr`

---

[← Back to AIPass](../../../README.md)
