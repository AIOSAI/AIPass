[<- Back to the README](../README.md)

# Sending, delivery and the message lifecycle

**Branch** ai_mail · **Code** `apps/handlers/email/delivery.py`, `apps/handlers/email/send.py`, `apps/handlers/email/inbox_ops.py`, `apps/handlers/email/create.py`, `apps/handlers/email/reply.py`, `apps/handlers/email/format.py`, `apps/handlers/email/error_dispatch.py`

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


## Email Lifecycle

Messages follow a 3-state model:

```
new → opened → closed
```

- **new** — Delivered to inbox, never viewed
- **opened** — Viewed by recipient, awaiting action
- **closed** — Replied or dismissed, archived automatically

Each branch's mailbox lives at `<branch_path>/.ai_mail.local/inbox.json`. Sent copies go to `.ai_mail.local/sent/`. File locking (`fcntl`/`msvcrt`) protects concurrent inbox writes.


## Related

- [cli_contract.md](cli_contract.md) — the help-flag and exit-code rules that guard
  the send and dispatch paths described here.
- [dispatch_register_and_feed.md](dispatch_register_and_feed.md) — the completion-report
  mechanism a failed send dispatches into (`error_dispatch.build_error_report()`).
- [identity_and_boundaries.md](identity_and_boundaries.md) — the cross-project fence that
  produces the refusals this file describes.
