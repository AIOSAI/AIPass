[← Back to AIPass](../../../README.md)

# AI_MAIL

**Purpose:** Inter-agent messaging for AIPass. File-based email system that lets agents send, receive, and process messages using `@branch` addresses. No SMTP, no external services — just JSON files and symbolic routing.
**Module:** `aipass.ai_mail`
**Created:** 2025-11-08
**Last Updated:** 2026-08-27

---

**Status:** Operational | **Seedgo:** 100% | **Tests:** 1340 pass across 46 files (1322 + 4 live-hygiene skips on a fresh checkout — 2 in `test_live_mailbox_hygiene.py`, 2 in `test_live_contacts_hygiene.py`) | **Battle Tested:** S62

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
drone @ai_mail dispatch @t "Subj" "Body" --model sonnet   # Wake on a named model
drone @ai_mail dispatch wake @target                      # Wake only (no email)
drone @ai_mail dispatch register                          # What is outstanding, what is overdue
drone @ai_mail dispatch status                            # Last 5 spawns (see Known Issues)
drone @ai_mail dispatch daemon                            # Start the polling dispatch daemon

# Send mail (no wake)
drone @ai_mail email @target "Subject" "Body"             # Send to one branch
drone @ai_mail email @all "Subject" "Body"                # Broadcast to all branches
drone @ai_mail email @target "Subj" "Body" --from @spawn  # Explicit sender override
drone @ai_mail email @t "Subj" "Body" --reply-to @x       # Route replies elsewhere
drone @ai_mail email @t "Subj" "Body" --upsert-key KEY    # Repeat signal, one slot (below)

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

## Broadcast Costs What It Delivers, Not More

`email @all` fans out sequentially to every fleet citizen. The per-recipient work
is real and it is allowed to take the time it takes. What is **not** allowed is
paying a global cost per recipient.

- **One central aggregation per broadcast, not one per recipient.**
  `update_central()` takes no arguments — it rescans every branch inbox from the
  repo root and derives the whole answer itself. Running it per delivery
  recomputes one global result N times, and only the last run is ever read.
  `send_to_broadcast` therefore passes **no** `on_delivered` callback and calls
  `update_central_fn()` once after the loop. The central file is byte-identical
  either way; the 18 discarded recomputations are not.
- **The inbox scan prunes, it does not filter.** `find_all_inbox_files()` walks
  with `os.walk` and drops excluded directories from `dirnames` in place, which
  is what stops the descent. It used to `rglob` the entire tree and then discard
  results whose path *contained* an excluded word — but discarding a result does
  not save the walk. Measured on the live repo: **2.9s → 0.34s** for the same 26
  inboxes, because 57GB of `.backup` and 68GB of `projects/` are no longer
  traversed to be thrown away.
- **Exclusions are path components, not substrings** (`EXCLUDED_DIR_NAMES`). The
  substring form hid any branch whose directory merely contained the word —
  `my.backup.tools/` read as an archive and vanished from central stats with no
  error anywhere. It was also the only reason `/backups/` behaved differently on
  Windows: that check was a literal forward-slash match, so the same tree counted
  on POSIX and not on Windows. Component names have no separator to disagree on.

**What this cost, stated plainly.** On 2026-08-27 a fleet announcement to 18
inboxes spent ~55 of its ~60 seconds doing 19 full-repo scans, and the router
killed it at its 60s default *after every message had already been delivered*.
The caller saw a timeout for a send that worked — worse than either a clean
success or a clean failure, because the work was done and only the report died.

**The timeout is still the router's to fix.** Speed here removes today's
symptom, not the failure shape: `resolve_timeout(branch, command, explicit)`
never sees the command's arguments, so no per-verb integer can distinguish
`email @seedgo` from `email @all`, and there is no mechanism for a target to
declare what a call actually needs. Raised with @drone separately; a bigger
constant is not the fix.

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

## Message Ids: Two Names, One Message

A delivered message has **two ids**, and they are not the same string:

| Field | Whose | Where it lives |
|-------|-------|----------------|
| `id` | the recipient's | minted at delivery, unique in *their* mailbox |
| `sent_id` | the sender's | copied from the sender's `sent/` record |

`id` is authoritative — it is what `inbox` lists, what `view` prints back, and
what `reply`/`close` expect. `sent_id` is a back-reference so the two sides can
be matched.

**Why both.** The recipient's id must be unique within their inbox no matter
what any sender chose, so delivery mints it. But without `sent_id` the two
copies shared no identifier at all: holding a sender's id, you could not prove
their message ever arrived. On 2026-08-16 that untraceability was read as a
delivery outage — @seedgo's reply (`de0cef3e` in their `sent/`) was sitting in
@devpulse's inbox as `361cefd6`, correctly delivered and unfindable.

**Both ids resolve.** `view`, `reply` and `close` accept either, through one
shared resolver (`inbox_ops.find_message`) rather than a fallback per command.
Inbox ids are checked before any `sent_id`, so a sender cannot shadow a
recipient's message with a colliding id, and resolution never depends on
message order. `view` prints `sender's id: <sent_id>` when present.

`sent_id` is omitted, never invented, when a producer stamps no id — some
callers (`@trigger`) deliver directly without a `sent/` record, and a
placeholder would point at a sent record that does not exist.

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

### Locating the feed

```python
from aipass.ai_mail import feed_path   # callable, resolves at call time
from aipass.ai_mail import FEED_PATH   # the import-time value, for existing callers
```

Import these from the package, never from `apps.handlers.notify` — reaching
into another branch's handlers layer is an encapsulation violation, and
restating the path as your own constant is worse: it goes stale the day the
feed moves, and the symptom is a bell showing nothing with no error logged
anywhere. Both names resolve lazily, so `import aipass.ai_mail` costs no prax
import. `FEED_PATH` reads through to the live module attribute, so a consumer's
test suite can redirect the feed the same way this branch's conftest does.

### Reading the feed: cursors go stale, key on `ts`

The trim is a read-modify-write that **replaces the file**, and lines carry no
id. Two consequences for every reader:

- **A line's position is not its identity.** After a trim, line 5 is a different
  event than the line 5 you last read. Any cursor held as a line index or byte
  offset silently points at the wrong place — no error, just wrong or skipped
  events. Byte offsets fare worse: the inode is new, so a `seek()` past the new
  end yields nothing at all and the feed looks permanently empty.
- **Resume on `ts`, and say when you lost ground.** Keep the last `ts` you
  served, re-open the file by path each poll, and take lines newer than it.
  If that `ts` is older than the feed's own first line the trim ate the gap;
  serve what remains and flag it rather than implying continuity. @api's
  `/v1/feed` does exactly this — ts-cursor clamped both ends with a gap flag.

Timestamps: every line `notify.py` writes is offset-aware
(`datetime.now().astimezone().isoformat()`), and all 216 lines in the live feed
were offset-aware when last measured (2026-08-16). But the contract says only
ISO8601, which does not require an offset, and hand-seeded lines have been naive
before — S130 filled this file from two writers with different shapes. Parse
defensively; comparing a naive `ts` against an aware one raises, and a reader
that crashes on the cursor comparison stops serving the feed entirely.

Tests point `FEED_PATH` at a tmp file via an autouse conftest fixture: four
call sites write feed lines as a side effect, and an unguarded suite run
appends fake dispatch events to the real feed BAUD renders.

## Dispatch Register + Completion Reports

Patrick's rule 1 (DPLAN-0317): *"the watchdog knows what is outstanding because it
was TOLD, never because it looked."* Nothing polls. Three files carry it.

```
.aipass/dispatch_register.jsonl        # what was promised, append-only
.aipass/dispatch_reports/<id>.json     # what happened, durable, waits to be read
.aipass/notifications.jsonl            # the existing feed, now pointing at both
```

### Locating them

```python
from aipass.ai_mail import register_path            # <repo root>/.aipass/dispatch_register.jsonl
from aipass.ai_mail import outstanding_dispatches   # the parsed open entries — prefer this
```

Same rule as the feed: import from the package, never from `apps.handlers`, and
never restate the path as your own constant.

### The register is APPEND-ONLY, and a naive reader is wrong rather than broken

An entry is written by `wake_branch()` **before anything spawns**, so a spawn that
dies still leaves evidence the dispatch was promised. It is closed by appending a
**second record** carrying the same `dispatch_id` — the first is never rewritten,
because the promise staying visible is the whole point.

**Read forward and let later records win.** A reader that takes the first record
per id sees every dispatch ever made as outstanding forever: wrong, plausible, and
silent. `outstanding_dispatches()` does this correctly and is why the
reconstruction is exported rather than left for each consumer to re-implement.

### Empty and unreadable are opposite answers

`outstanding_dispatches()` returns `[]` when the register **does not exist** —
nobody has dispatched from this project yet, which is legitimate and honest. It
**raises `OSError`** when the register exists and cannot be read.

The distinction is @devpulse's, and it is load-bearing for anything that renders
health: *"none outstanding"* and *"I cannot tell what is outstanding"* must not
look the same, and an empty list is how they would. A watchdog that shows all
clear because it could not open the file is worse than one that shows an error.

If you want the tolerant read instead, `jsonl_records(path, strict=False)` is the
default and logs rather than raises. The feed uses it deliberately — a
notification bell that raises at a delivery hook is a worse failure than one that
misses an event.

### Where the root comes from

Both paths resolve through `find_repo_root()`, which walks up for
`AIPASS_REGISTRY.json` and then for `pyproject.toml`. **The second marker is not
redundant.** The registry is untracked runtime state, so on a fresh checkout — CI,
a new clone — it exists nowhere, and the walk used to fall through to
`Path.cwd()`. The register would then be created wherever the process happened to
be standing, which reports perfect health while covering nothing. `pyproject.toml`
is tracked and sits only at the repo root, so the right answer was always
available; it simply was not being asked for.

```
{"dispatch_id": "<uuid4>", "ts": "<iso>", "sender": "@devpulse", "target": "@ai_mail",
 "subject": "...", "expected_by": "<iso>", "status": "outstanding"}
{"dispatch_id": "<uuid4>", "ts": "<iso>", "status": "completed", "report_path": "..."}
```

### Crash coverage without a process — and its two-hour latency

`expected_by` comes from `dispatch_monitor`'s own `HARD_TIMEOUT` (7200s), never an
invented number. A **live** monitor kills the run at that mark and reports, so it
cannot legitimately overrun: an entry past `expected_by` with no completion record
means the monitor **died**. Zero false positives, and nothing runs to discover it —
the staleness is simply a fact about a file that any reader sees.

Honest cost, named rather than found later: the deleted r3 daemon spotted a stale
lock in ten minutes. This spots a dead monitor in two hours. That is a deliberate
trade of detection latency for zero idle cost. `drone @ai_mail dispatch register`
lists what is open and flags what is overdue.

### The report is durable; delivery is opportunistic

Written **before the dispatch lock is released** — under r4 the report *is* the
event, so losing it means the dispatch never happened while the released lock says
it finished cleanly. With the release last, the same crash leaves a held lock:
visible, and recoverable by the stale-lock path that already exists.

Two honesty requirements the report will not drop:

- **`bg_orphaned` and `max_turns_hit` ship beside `emails_sent`, always.** When
  `bg_orphaned` is true the agent exited 0 while its background tasks — possibly
  including its reply — were killed at the headless ceiling. The report then
  honestly says *zero emails sent* for an agent that believed it had replied.
  Without those flags beside it a reader concludes the agent ignored its mail.
  **Never a bare exit 0.**
- **`memories_edited` detects a WRITE, not a good one.** Rewriting `local.json`
  with identical bytes still trips it.

`emails_sent` is a **record, not an inference**: every mail is stamped with the
`dispatch_id` live at send time, so attribution is by authorship. An mtime scan of
`sent/` would attribute by *time* and credit the agent with anything else that
wrote the mailbox during its run.

### Feed records for dispatch completions

`kind: "dispatch"` lines gained three **additive** keys — `dispatch_id`, `sender`,
`report_path`. The five contract keys are untouched and are written last, so an
extra can never redefine `ts` or `kind`. Values may be null on an unregistered
dispatch; treat them as optional. The full report is deliberately **not** inlined:
it is 1–2 KB and would bloat what @api serves to BAUD, so the line carries a
pointer instead.

`trigger.fire("dispatch_completed", ...)` also fires, and is **in-process only** —
@trigger cannot cross process boundaries (DPLAN-0314). **The feed file is what
carries this event to another process.** Anything expecting the trigger to reach a
separate watchdog will silently never fire.

Tests re-root the register and the reports directory to `tmp_path` via an autouse
conftest fixture. `wake_branch` registers before spawning and the wake tests mock
the spawn, so an unguarded run writes phantom "outstanding" entries into the live
register — 62 of them, the first time this shipped.

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

A failed send also auto-dispatches an `[ERROR] Send failed to ...` report to `@drone`
(`error_dispatch.build_error_report()`). That report is **from `@ai_mail`, and replies to it
come back to `@ai_mail`**. It carried `reply_to: "@devpulse"` until 2026-08-13, so @drone's
reply to a message reading `From: ai_mail` landed on the dispatcher instead (reported by
@drone/@devpulse, live-reproduced and fixed in APLAN-0006). `reply.py` routes to
`reply_to or from`, so those two fields together decide where an answer goes: whoever the
From line names has to be who receives the reply. The branch whose send failed stays named
in the body, as evidence, not as a route.

## Help Flags — Explain, Never Execute

A help flag anywhere in the argument list means *describe this command*, and all three
modules check for it as the first thing after the command-ownership guard in
`handle_command` — before any argument is read and before anything routes. It is not
literally statement one, and cannot be: a module has to establish the command is *its*
before it may answer for it (`email.py`, `dispatch.py`, `email_send.py`).

They used to gate help at `args[0]` only, so a flag one position later was discarded and
the command ran instead. On a messaging branch that is not a cosmetic bug:
`dispatch @target "Subject" "Body" --help` fell through to `_orchestrate_dispatch_send`
and would have **sent the mail and woken the branch** it was asked to describe. `email`,
`close all` and `reply` had the same shape against the mailbox. (Seedgo standard
`help_flag_safety`, DPLAN-0291 rule E — the router cannot fix this for us, because the
standalone `__main__` path calls `handle_command` with raw argv and never touches it.)

`apps/handlers/cli/help_flags.py` holds the whole check — `wants_help(args)`, a pure
predicate with no I/O and no imports beyond typing, so it can run ahead of every layer:

| Token | Counts as help | Why |
|---|---|---|
| `--help`, `-h` | anywhere in the sequence, **exact match** | unambiguous wherever they appear |
| `help` | position 0 only | a bare word is legitimate message content |

- **Exact match is what keeps real mail intact.** A body reading `run --help for usage`
  arrives as one quoted argument and is not that token, so it still sends. A body that is
  *exactly* `--help` explains instead — nonsense input, and explain-over-execute is the
  ruling.
- **Position 0 for the bare word**, because on this branch a subject or body can plausibly
  be the single word "help". None of the three modules owns a genuine `help` verb, so that
  slot is free; `allow_bare_word=False` exists for a module that ever does.
- **Tests assert both halves** — help printed *and* the send/wake target never called.
  Asserting only the first would pass on code that explains itself after sending the mail.
- The handler carries a documented `json_structure` bypass: the standard wants a
  `log_operation()` call, which would make the help gate depend on the JSON layer it must
  run in front of, and would log a non-event on every invocation. @memory, @trigger and
  @drone bypassed the identical file the same day.

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

The same rule still reads wrong on one path: `dispatch wake`'s failure line says "see the
step status **above**", and the steps replay below it. Tracked in APLAN-0006.

### Interactive send needs a terminal

`email` / `send` with no arguments means interactive mode. That is a human-only path, and
it now refuses up front when `sys.stdin` is not a TTY — usage to stderr, exit 2, no branch
list printed first.

Under `drone` the routed subprocess inherits an **open but silent** stdin pipe, so
`input()` does not raise `EOFError`; it blocks until drone's 30s routing timeout kills the
command. `EOFError` handling alone cannot cover this, because once you are waiting on the
first read, "no input yet" and "no input ever" are the same thing. The check has to happen
before the first prompt, and it lives in both halves — `send.collect_interactive_input()`
refuses, and `email_send._send_interactive()` refuses ahead of it so the listing never
prints and the exit code is right.

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

### `@all` Scope: Fleet, Plus Residents for a Verified Admin

`@all` resolves the 18 core citizens. A **verified-admin** `@all` also reaches the
four resident projects — baud, earmark, finch, aipass_site (ruled 2026-08-27,
DPLAN-0318 circle close). Ordinary citizens' `@all` is byte-identical to what it
was: the widening rides the same five-leg verification that already permits
admin-initiated direct mail into projects, and grants no new authority — every
recipient still passes the per-delivery boundary check.

The case that decided it: the fleet-push announcement had to be hand-sent to the
four residents in four separate admin sends, because `@all` could not carry it.
An announcement every citizen should hear is exactly what the asymmetry was
built for.

- **The resident list is a NAMED CONSTANT, never a glob** (`RESIDENT_REGISTRIES`
  in `registry/read.py`, read by `get_resident_branches()`). `projects/` also
  holds `marketstand(on _hold)` and `speakeasy(on_hold)`, and marketstand's
  registry still marks its branch `active` while its directory name says parked —
  a glob would broadcast into a held project on the strength of a stale field.
- **Broadcast scope and resolution scope are different questions.**
  `get_project_tree_branches()` still globs, and should: a held project's citizen
  legitimately has an *address*. Being reachable is not the same as being on the
  announcement list.
- **It mirrors @memory's `registry_scope.RESIDENT_REGISTRIES`**, the single fleet
  definition, and is deliberately a copy rather than an import — reaching into
  another branch's handlers is an encapsulation violation, and `@all` must not
  acquire a runtime dependency on @memory to know who it is talking to. A test
  parses their constant and fails on drift, so the copy cannot rot quietly.
- **Fails closed in both directions.** An unverified caller widens nothing, and a
  verifier that *raises* is a refusal, not an opening.
- **One inbox, one copy** — a resident already in the core registry is not added
  twice.

### Out-of-Scope Addresses Are Explained, Not Denied

An address can fail to resolve for two different reasons, and reporting both as
"unknown" is a lie in one of them. `@baud` is a registered citizen of `projects/baud`
that @devpulse reaches through the admin lane; telling a fleet branch it does not exist
sent @api hunting an addressing bug that did not exist and left two stray pings in
@baud's inbox (2026-08-14).

```
Out of scope: @baud is a citizen of hosted project 'baud', not the AIPass fleet
(17 branches in scope). Fleet-to-project mail is replies-only by ruling
(DPLAN-0288) — only @devpulse's verified-admin lane may initiate. Reply to an
existing message from @baud, or use the feedback channel.
```

The branch count is **computed, not written** — `len(branches)` for the caller's own
scope, handed to `_describe_unresolved_address()`. It reads 18 today and drifts with the
fleet; the number above is an example of the shape, never a constant.

- **The refusal is unchanged — only the reason is now true.** Fleet→project initiation
  stays walled for every non-admin caller, exit `2`, sent record stamped `refused`.
- **`_describe_unresolved_address()` runs on the failure path only**, so a successful
  send never pays for the registry read.
- **Explaining the wall must not open it.** The diagnostic returns a *string*; the branch
  map is never updated from it. A test asserts delivery still fails and no inbox is
  written — that is the load-bearing test in this fix, not the wording ones.
- **Exact match**, so `@bau` is still an honest "unknown", not a near-miss guess.
- A hosted registry that is missing or unreadable falls back to the plain unknown
  message; a refusal never becomes a crash.

Naming the project is not a disclosure: `projects/` is in the same public repo, and the
caller can list it. What was secret was the *policy*, which is exactly what a wall should
say out loud.

**Two walls, and they used to disagree.** Resolution is the outer wall;
`_check_cross_project_boundary()` is the inner one. The inner wall already named both
projects and said "cross-project mail refused". Anyone stopped by the outer wall never
learned a policy existed at all.

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

Branch identity detection runs in `detect_branch_from_pwd()`. It is **not** a flat
waterfall — a fence runs first, and the env-var lane and the walk-up lane are
alternatives, not neighbours.

**0. The identity fence.** `AIPASS_CALLER_CWD` set but standing outside any branch →
refused outright, *unless* `AIPASS_CALLER_IDENTITY_SOURCE` is `assigned` or `passport`.
@drone stamps which kind of evidence named the caller, and a credential travels where a
location does not. `project` — a registry-derived *project* name — answers "which project
am I in", never "who am I", and stays refused: that is the $1.41 wake, where drone
standing at the repo root stamped `aipass` the directory, which spells the same as
`@aipass` the citizen. An **absent** `AIPASS_CALLER_CWD` is not contradicting evidence and
leaves everything below untouched — in-process callers depend on that.

**1. `AIPASS_CALLER_BRANCH` is set** → registry lookup by name, **then** contacts, then an
identity synthesized from the env vars alone (recorded `unverified` — no passport, no
registry row).

> **The registry is asked before contacts, and the order is the whole fix.**
> `AIPASS_REGISTRY.json` is the authoritative catalog; `contacts.json` is a learned,
> writable cache. Asking the cache first let one poisoned row outrank the catalog for a
> citizen the catalog knew perfectly well — found live 2026-08-23, when
> `drone @ai_mail inbox` served @flow's mailbox from inside @ai_mail's own directory,
> logged as name AI_MAIL / email @ai_mail / path `.../flow`, confidence **verified**.
> The `is_dir()` staleness guard could never have caught it: the wrong root was a live
> branch with a real mailbox in it. Contacts keep their real job — resolving external
> callers the registry has never heard of.

**2. No `AIPASS_CALLER_BRANCH` at all** → walk up `AIPASS_CALLER_CWD` (or, with no caller
env, this process's `Path.cwd()`) for `.trinity/passport.json`, then registry lookup by
path. The `Path.cwd()` leg is recorded `unverified` deliberately: it is correct for a
dispatched agent standing in its own tree and silently wrong anywhere else.

Every exit is stamped by `_record_resolution()` with the winning strategy and a
confidence, so a wrong sender can be traced to the path that produced it. If all fail,
detection returns `None` and the operation fails loudly. Wrong identity is worse than no
identity.

The `--from @branch` flag on send/email commands provides an explicit sender override for callers outside branch directories.

### Registry Rows Leave the Reader Absolute

**A registry row's `path` is relative to THE REGISTRY THAT HOLDS IT.** Returned raw it
carries no memory of which registry answered, and every consumer then joins it to the
AIPass repo root — right for AIPass citizens by coincidence, wrong for every project
citizen.

`_rooted()` absolutises a row against its own registry at the point of read, in both lanes
of `_lookup_branch_by_name()` and both of `get_branch_info_from_registry()`. Rows already
absolute pass through untouched. It lives at the reader rather than at the nine call sites
that join a registry path, because a consumer cannot re-derive a root it was never given —
and nine copies of that join is how they drift.

**It fabricated rather than failing, which is why this is a rule and not a footnote.**
Found live 2026-08-24: a `projects/*` citizen read *"Inbox is empty"* against a file
holding four unread messages, and `reply <id>` answered *"Message not found"* for an id
read out of that same file. `projects/baud` + row `src/baud/baud` had resolved to
`<aipass>/src/baud/baud`. That path sits **inside** the AIPass tree, so the mail lane
created it — a phantom `.ai_mail.local/` holding a reply its author believed he had sent,
in a directory belonging to no citizen. A refusal would have been loud; a confident wrong
address was not.

The caller-registry fallback in `_lookup_branch_by_name()` is **not** admin-gated, and is
a different question from the admin-only cross-project sweep above: it resolves a citizen
of the caller's *own* project. It cannot reach @baud from a fleet seat — walking up from a
fleet citizen's `AIPASS_CALLER_CWD` finds `AIPASS_REGISTRY.json` first, which does not
list him.

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

### A Credential Is Not an Ambiguity

`_record_resolution()` warns when `AIPASS_CALLER_BRANCH` and `AIPASS_CALLER_CWD`
name different branches — the one disagreement visible from inside this process.
It logs that at **debug** when the env var carries a credential provenance
(`assigned` / `passport`) *and* actually resolved against a catalog.

A credential travels and a location does not: an agent that cds into another
branch is still itself. So `assigned` naming one branch while the cwd sits in
another is the designed precedence working, not a conflict. 104 lifetime
warnings said AMBIGUOUS about correctly-resolved sweeps — every one
`CALLER_BRANCH='ai_mail'` with the cwd walking the whole fleet — and a warning
that fires on the known-good case buries the one it exists for.

Three cases deliberately keep the warning, because none is proven good:

| Case | Why it stays loud |
|---|---|
| provenance `project` | a registry-derived **directory** name — @aipass the directory and @aipass the citizen spell the same. This is the $1.41 wake |
| provenance missing / `unknown` | unprovable is not proven; this lane fails toward noise, not silence |
| resolved via `caller_branch:synthesized` | the name resolved against nothing — provenance says who *stamped* it, never that anything vouched for it |

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
│       │   └── dashboard_sync(disabled).py # Dashboard integration — retired, kept per house rule
│       ├── dispatch/
│       │   ├── daemon.py       # Polls inboxes, spawns agents for dispatch emails
│       │   ├── wake.py         # Wakes branches via claude subprocess
│       │   ├── dispatch_monitor.py # Wraps claude process (bounce, lock cleanup, sandbox, broker fd)
│       │   ├── register.py     # Append-only dispatch register — open/close/outstanding
│       │   ├── report.py       # Completion report — build/write, emails_sent, memories_edited
│       │   ├── session_pointer.py # Durable resume-session pointer (replaces `claude -c`'s mtime guess)
│       │   ├── status.py       # Dispatch log I/O
│       │   └── test_token.py   # AIPASS-TEST ping protocol (auto-ack)
│       ├── cli/
│       │   └── help_flags.py   # wants_help() — whole-sequence help detection, pure predicate
│       ├── registry/
│       │   └── read.py         # Registry reading + get_all_branches()
│       ├── users/
│       │   ├── branch_detection.py # CWD/env-based branch identity detection
│       │   ├── verified_caller.py  # Verified-caller rail + 5-leg admin verdict
│       │   └── user.py         # Current user detection (get_current_user)
│       ├── json_utils/
│       │   └── json_handler.py # Auto-creating JSON system (the implementation)
│       ├── json/
│       │   └── json_handler.py # Re-export shim — seedgo's architecture standard
│       │                       # requires apps/handlers/json/json_handler.py by name
│       ├── paths.py            # Shared find_repo_root() utility
│       ├── notify.py           # Notification feed writer (JSONL, BAUD reads)
│       └── central_writer.py   # Central inbox stats aggregation
└── tests/                      # 1326 tests across 46 test files (selection below)
    ├── conftest.py             # Shared fixtures (mock_logger, mock_json_handler)
    ├── test_daemon.py          # Daemon config, state, kill switch, dispatch check
    ├── test_dispatch_monitor.py # Monitor safety features, env stripping
    ├── test_dispatch_status.py # Log I/O, age calculation
    ├── test_wake.py            # Branch resolution, PID checks, lock files
    ├── test_wake_blocklist.py  # Wake protection for @devpulse
    ├── test_delivery.py        # Inbox migration, private branches, pipeline
    ├── test_send_identity.py   # Sender identity chain (62 tests)
    ├── test_identity_fence.py  # Every verb refuses outside a branch
    ├── test_user_paths.py      # Mailbox path resolution (22 tests)
    ├── test_contacts.py        # Address book operations
    ├── test_inbox_ops.py       # Inbox loading + migration
    ├── test_registry_read.py   # Registry parsing + branch lookup
    ├── test_upsert.py          # upsert_key repeat-signal collapsing (40 tests)
    ├── test_central_writer.py  # Central stats aggregation
    ├── test_cli_routing.py     # CLI routing + help/version
    ├── test_json_handler.py    # JSON I/O helpers
    ├── test_notify.py          # Notification feed schema, trim, concurrency (23 tests)
    ├── test_refused_sends.py   # Refused-send records + handled-vs-worked routing (25 tests)
    ├── test_help_flag_safety.py # Whole-sequence help detection, 3 modules (21 tests)
    ├── test_cross_scope_addressing.py # Honest refusal of hosted-project addresses (8 tests)
    ├── test_public_surface.py  # Package doors: feed_path, register_path, outstanding (22 tests)
    ├── test_message_correlation.py # sent_id back-reference + shared id resolver (12 tests)
    ├── test_live_mailbox_hygiene.py # Guard: no test fixtures in real mailboxes (4 tests)
    ├── test_live_contacts_hygiene.py # Guard: no tmp paths in live contacts.json (3 tests)
    ├── test_dispatch_register.py # Append-only register, later-record-wins reconstruction
    ├── test_dispatch_report.py  # Completion report contents + durability
    ├── test_session_pointer.py  # Resume pointer (47 tests)
    ├── test_admin_lane.py      # 5-leg admin verdict on the wake path
    ├── test_cross_project_bridge.py # Admin-only resolution + reply return path
    └── test_paths.py           # find_repo_root() utility
```

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and display formatting
- `aipass.drone` — broker-socket IPC for a sandboxed dispatch child
  (`create_identified_connection`). This is the **only** `aipass.drone` import in the
  package: `@branch` resolution is internal (`registry/read.py`, `users/branch_detection.py`),
  and "drone routes commands to us" describes how `drone @ai_mail …` invokes this branch
  from outside, not a dependency
- `aipass.trigger` — `trigger.fire()` for `email_dispatched` / `dispatch_completed` events
- Python stdlib (`pathlib`, `json`, `importlib`, `subprocess`, `fcntl`) — argument parsing
  is hand-rolled in `send_args.py`, not `argparse`

### Provides To
- **All branches** — inter-branch messaging (send/receive/reply/close)
- **Dispatch system** — autonomous task execution via `auto_execute` emails
- **Branch contacts** — address book for `@branch` routing
- **trigger branch** — `deliver_email_to_branch()` imported directly for event-driven delivery
- **BAUD** — `.aipass/notifications.jsonl` feed for delivery, wake, dispatch events

## Bypass Registry

`.seedgo/bypass.json` holds **20** rules — 17 survivors of the prune below, one added the
same day *with* `cli/help_flags.py` and measured live (99% with it off, 100% on, the
opposite of a prune candidate), plus two added since: `handlers` on
`dispatch/report.py` (FPLAN-0452 P1) and `unused_function` on the package `__init__.py`
(S154, re-checked against the built wire). The 99%-with-everything-off figure was measured
on 2026-08-13 against the 18-rule registry and has **not** been re-run since — the 100%
audit score below is current, that one is dated.

It held 51 until the 2026-08-13 audit measured
every one of them in **both** lanes — the audit lane (`audit aipass @ai_mail --full`, walks
`apps/`) and the checklist lane (`checklist <file>`, what the PostToolUse hook runs) — with
the registry emptied. 34 suppressed nothing in either lane and were removed; the score is
100% before and after, which is the proof. Each dead class had a cause, not just an absence:

| Class | n | Why it went dead |
|---|---|---|
| `handlers`, same-branch | 12 | The standard now flags only **cross-branch** handler imports and handler→modules. The imports the reasons describe are still in the code and now pass. |
| `documentation` | 8 | The AST detector's multiline-signature miss was fixed upstream; the signatures are unchanged. |
| `deep_nesting`, depth 4 | 8 | The limit is now 5. Every surviving rule names a depth-5+ function. |
| `naming`, local variables | 5 | Plain locals are no longer read as module constants. Lazy-import *function references* still are — those 4 rules stayed. |
| `modules` | 1 | A helper module without `handle_command()` no longer violates. |
| file no longer exists | 1 | `email/identity.py`, gone from the tree with no archive and no references. |

Measured, not assumed: this branch has **zero `tests/*` rules**, which is the class that
made the naive audit-lane-only signal wrong 5 times in 6 for @seedgo. Here the two lanes
agreed on every rule. Do not reuse that conclusion for a branch that has `tests/*` rules —
re-measure per lane.

## Known Issues

- **DPLAN-0138**: Inbox backdoor audit identified 2 write path classes — ad-hoc direct writes (detectable by non-UUID ID format) and `_deliver_via_reply_path()` bypass (no lock, no notification). Fix pending.
- **Caller detection**: `BRANCH DETECTION FAILED` when callers don't set `AIPASS_CALLER_BRANCH` (low severity, caller-side fix — use `--from` flag)
- **Cross-branch writes**: ai_mail not in trusted cross-writers list for `system-pr`
- **No per-subcommand help**: `view --help`, `reply --help`, `close --help`, `sent --help`,
  `contacts --help` and `inbox --help` all print the same email-module help. The
  `subcommand_help` standard scores 100% on it. Open in APLAN-0006.
- **`--from` is undocumented in `email --help`** — it is in this README and in the code, but
  not in the module's own FLAGS block. Open in APLAN-0006.
- **`--model` help names retired models** ("Claude Opus 4.6", "Sonnet 4.6"). Open in APLAN-0006.
- **`dispatch status` reports "No dispatches recorded yet." while dispatches are running.**
  Reproduced 2026-08-25 with two live entries visible in `dispatch register` at the same
  moment. The register is the trustworthy view; `status` reads a different log and its
  empty answer is a false negative, not an empty state. Open in APLAN-0006.
- **`dispatch wake` prints "see step status above"** when the step status prints below it
  (`dispatch.py`). Named under *Output ordering*; open in APLAN-0006.

---

[← Back to AIPass](../../../README.md)
