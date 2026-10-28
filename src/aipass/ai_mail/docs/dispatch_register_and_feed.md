[<- Back to the README](../README.md)

# The dispatch register, completion reports and the notification feed

**Branch** ai_mail · **Code** `apps/handlers/notify.py`, `apps/handlers/email/delivery.py`, `apps/handlers/dispatch/wake.py`, `apps/handlers/dispatch/dispatch_monitor.py`, `apps/handlers/dispatch/register.py`, `apps/handlers/dispatch/session_pointer.py`

---

## Notification Feed

Desktop toasts are retired — no D-Bus, no
notify-send, no fallback that still toasts. `notify.py` appends notification
events to a shared JSONL feed that BAUD's notification bell reads.

```
path : <repo root>/.aipass/notifications.jsonl
line : {"ts": ISO8601, "kind": "mail"|"wake"|"dispatch"|"system",
        "title": str, "body": str, "source": branch name (no @)}
```

- **Append-only, one object per line.** Readers never write; the feed carries no
  read flags — BAUD tracks read state locally.
- **Three writers, three kinds** — `delivery.py` (`mail`), `wake.py` (`wake`),
  `dispatch_monitor.py` (`dispatch`, completion).
  An off-contract `kind` is recorded as `system` and the substitution is logged,
  never silently accepted.
- **Concurrency** — those three are separate processes. Each append is a single
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
(`datetime.now().astimezone().isoformat()`). The contract says only ISO8601, which
does not require an offset, and a hand-seeded line may be naive. Parse
defensively; comparing a naive `ts` against an aware one raises, and a reader
that crashes on the cursor comparison stops serving the feed entirely.

Tests point `FEED_PATH` at a tmp file via an autouse conftest fixture: three
call sites write feed lines as a side effect, and an unguarded suite run
appends fake dispatch events to the real feed BAUD renders.

## Dispatch Register + Completion Reports

The watchdog knows what is outstanding because it was told, never because it looked.
Nothing polls. Three files carry it.

```
.aipass/dispatch_register.jsonl        # what was promised, append-only
.aipass/dispatch_reports/<id>.json     # what happened, durable, waits to be read
.aipass/notifications.jsonl            # the feed, pointing at both
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

The distinction is load-bearing for anything that renders health: *"none outstanding"* and *"I cannot tell what is outstanding"* must not
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
a new clone — it exists nowhere; `pyproject.toml` is tracked and sits only at the
repo root. A register created wherever the process stands would report perfect
health while covering nothing.

```
{"dispatch_id": "<uuid4>", "ts": "<iso>", "sender": "@devpulse", "target": "@ai_mail",
 "subject": "...", "expected_by": "<iso>", "status": "outstanding", "provider": "claude"}
{"dispatch_id": "<uuid4>", "ts": "<iso>", ..., "status": "outstanding", "monitor_pid": 12345}
{"dispatch_id": "<uuid4>", "ts": "<iso>", "status": "completed", "report_path": "..."}
```

`provider` names the CLI the wake spawned: `claude`, `codex` or `opencode`.

The middle line is the **pid annotation**: a second
`outstanding` record appended once the spawn returns a pid, which `open_dispatch`
could not know because it deliberately runs *before* the spawn. Same append-only
discipline as closing — the promise is never rewritten, and the fold takes the
later record.

### Crash coverage without a process — and its two-hour latency

`expected_by` comes from `dispatch_monitor`'s own `HARD_TIMEOUT` (7200s), never an
invented number. A **live** monitor kills the run at that mark and reports, so it
cannot legitimately overrun: an entry past `expected_by` with no completion record
means the monitor **died**. Zero false positives, and nothing runs to discover it —
the staleness is simply a fact about a file that any reader sees.

The cost: by `expected_by` alone a dead monitor shows in two hours, a deliberate
trade of detection latency for zero idle cost. `drone @ai_mail dispatch register`
lists what is open and flags what is overdue.

**The two-hour latency is the fallback, not the only signal.** Rows carrying a
`monitor_pid` also expose `monitor_alive` on read — the process is checked (Linux
reads `/proc`, Windows `OpenProcess`) at the moment someone looks, never stored, because a stored liveness is
stale the instant it is written. A dead monitor is therefore visible on the next
watchdog pass (five minutes) instead of at `expected_by`.

`monitor_alive` is **three-valued and the third value matters**: `True` alive,
`False` gone, `None` cannot be told. `None` covers rows with no `monitor_pid` and the
systemd-scope spawn path, which never learns a pid. Readers treat `None` as "fall
back to `overdue`"; reading it as `False` would announce a death that nobody saw.

### A reply closes the row

An agent's own reply is the strongest completion evidence the system has, so a
reply closes its dispatch (`status: "completed (replied)"`, distinct from the
monitor's own `completed` so a reader can tell "the agent said so" from "the process
exited"). Only the row's **target** can close it — a third party replying on the
thread says nothing about whether the dispatched agent finished.

**Matched by thread, not by the agent's dispatch stamp.** A resumed agent runs
under a new dispatch id, so its completion carries a different stamp, and a stamped
early mail (a report-first plan) is not a completion. The stamp would close too
early and still miss the completion; the thread is the one link that survives a
resume, and a report-first plan is not a reply on it.

A dispatch with an **empty subject** — a bare wake — has no thread and can never
be matched. Its row keeps `expected_by` as its only signal, which is honest
rather than a gap: there is nothing for the agent to reply *to*.

### The report is durable; delivery is opportunistic

Written **before the dispatch lock is released** — the report *is* the
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

### Feed records for delivered mail

`kind: "mail"` lines carry three **additive** string keys — `mail_id` (the
message's `id` in the recipient's `.ai_mail.local/inbox.json`), `recipient` (the
branch, no @) and `project` (the recipient's project as its registry names it:
`BAUD_REGISTRY.json` → `baud`, `unknown` when no registry names it). The body
stays subject plus a 100-char preview; the keys are the way to the whole message.
An upsert update writes no line, so it carries none. `wake` lines carry none either.

### Feed records for dispatch completions

`kind: "dispatch"` lines carry three **additive** keys — `dispatch_id`, `sender`,
`report_path`. The five contract keys are untouched and are written last, so an
extra can never redefine `ts` or `kind`. Values may be null on an unregistered
dispatch; treat them as optional. The full report is deliberately **not** inlined:
it is 1–2 KB and would bloat what @api serves to BAUD, so the line carries a
pointer instead.

`trigger.fire("dispatch_completed", ...)` also fires, and is **in-process only** —
@trigger cannot cross process boundaries. **The feed file is what
carries this event to another process.** Anything expecting the trigger to reach a
separate watchdog will silently never fire.

Tests re-root the register and the reports directory to `tmp_path` via an autouse
conftest fixture. `wake_branch` registers before spawning and the wake tests mock
the spawn, so an unguarded run would write phantom "outstanding" entries into the
live register.

## The run record

Every dispatch says which host ran it and which model answered. The record lives on the
session pointer, `.ai_mail.local/session.json`, beside `session_id` and `provider`:

```
host_cli         : claude | codex | opencode   (the same fact as provider)
model_provider   : the vendor as the host names it, or "pending"
model_requested  : what the door asked for, or "cli_default"
model_observed   : the id the runtime's own assistant row reports, or "pending"
selection_source : flag | inline_config | project_config | user_config | cli_default | unknown
observed_at      : ISO time of the first observation, or null
```

- **Requested comes from the argv** the door built: `--model` (claude) or `-m` (codex,
  opencode) is `flag`; otherwise the `model` key of an `--opencode-config` object is
  `inline_config`; otherwise `cli_default`. Project and user `opencode.json` are not
  resolved here, so a model they set reads as `cli_default`.
- **Observed comes from the runtime's own row** for the pointer's session, read by
  `session_pointer.observe_model()` after the run: the newest assistant row of
  OpenCode's `session_message` table (read-only), the last assistant line of the Claude
  transcript, the last `turn_context` of the Codex rollout. Unseen stays `pending`; a
  requested model is never promoted to observed.
- **One line, three surfaces.** `format_run_line()` prints it in the dispatch result
  (step `run`, at send: observed is always pending there), at the end of the bounce,
  and at the end of the completion wake-back (message or manager mail):
  `run: opencode · openai/gpt-6.1-sol (observed; flag) session ses_…`.
  Never a credential or a config's contents.
- `write_pointer(..., run=...)` sets the keys; a call without `run` writes the defaults,
  with `host_cli` taken from `provider`.

## Related

- [wake_pipeline.md](wake_pipeline.md) — the spawn path `wake_branch()`
  and `dispatch_monitor.py` run before a register row or a feed line ever exists.
- [wake_lanes.md](wake_lanes.md) — `wake_branch()` itself: the admin, cross-project,
  and `@all` lanes it dispatches through before a register row is even closed.
- [sending_and_delivery.md](sending_and_delivery.md) — `delivery.py`, the feed's
  `mail` writer, and the reply lifecycle a completion report's `emails_sent` counts.
- [cli_contract.md](cli_contract.md) — `drone @ai_mail dispatch register` and the
  rest of the CLI surface referenced here.
