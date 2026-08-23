# Test sheet — the 08-21 no-fallback night

Three branches changed tonight: **@ai_mail** (identity fence, manager wake-back),
**@drone** (router detour, identity provenance), **@devpulse** (watchdog, mine).

**Every FAIL below is a PASS for us.** The whole night was converting silent
substitutions into loud refusals. A command that refuses with a clear message is
the feature.

**Before you start**, so your own seat's env doesn't mask the cases:

```bash
unset AIPASS_CALLER_BRANCH AIPASS_CALLER_CWD AIPASS_CALLER_IDENTITY_SOURCE
```

---

## A. The identity fence — @ai_mail

The defect: a dispatch from the repo root sent as a different citizen. **$1.41,
11 turns, a phantom badge you couldn't clear.**

| # | From | Command | Expect |
|---|---|---|---|
| A1 | repo root | `unset AIPASS_BRANCH_NAME; drone @ai_mail inbox` | **FAIL exit 2** |
| A2 | repo root | `unset AIPASS_BRANCH_NAME; drone @ai_mail dispatch @canary "probe" "probe"` | **FAIL exit 2**, nothing sent |
| A3 | `/tmp` | `AIPASS_BRANCH_NAME=ai_mail drone @ai_mail inbox` | **PASS exit 0** |
| A4 | `/tmp` | `unset AIPASS_BRANCH_NAME; drone @ai_mail inbox` | **FAIL exit 2** |
| A5 | `src/aipass/devpulse` | `unset AIPASS_BRANCH_NAME; drone @ai_mail inbox` | **PASS exit 0**, your inbox |
| A6 | repo root | `drone @ai_mail --help` | **PASS exit 0** |
| A7 | both | `drone @ai_mail view <id>` from a branch, then from root | PASS, then **FAIL exit 2** |

**A1 is the $1.41 case.** Before tonight it printed another citizen's inbox and
said nothing. Expected text:

> BRANCH DETECTION FAILED: Could not resolve the sending branch.
> AIPASS_CALLER_CWD=... is not inside a branch — no .trinity/passport.json at or
> above it ... re-run from within the sending branch.

**A2:** confirm the refusal happens BEFORE the send — no new file in
`src/aipass/aipass/.ai_mail.local/sent/`, nothing new in @canary's inbox.

**A3 is S102 restored** — a dispatched agent that `cd`s away is still itself.
This was *refused* between 19:21 and 22:04; that regression is what the
provenance flag lifted. `assigned` and `passport` are credentials; `project` is
a directory name and stays refused forever.

**A7:** `view`/`close`/`reply` were the quiet ones — they used to fall back to
@ai_mail's own mailbox.

> **Already run by me, 22:07 — all five matched:** A1 exit 2 · A3 exit 0 ·
> A4 exit 2 · A5 exit 0 · A6 exit 0.

## B. The manager wake-back — @ai_mail

The defect: dispatch **told** you the sender would be woken, then for managers
silently woke nobody and sent nothing. Three statements in the code corroborated
each other and all three were wrong.

- **B1** — `drone @ai_mail dispatch @canary "test" "reply and stop"`.
  The closing line must now read *"@devpulse is a manager and is never woken, so
  you will be MAILED when @canary completes"*. It must **not** say "woken".
- **B2** — when @canary finishes, check my inbox **with the watchdog wire
  disarmed**. Expect mail *"Dispatch complete: @canary finished (exit 0)"*.
  **This is the P0** — before tonight, nothing arrived.
- **B3** — `tail src/aipass/canary/logs/dispatch_wake.log` → newest line reads
  `wake_result=mailed_manager`, not `skipped_manager`.
- **B4** — confirm @devpulse was **not** woken. No new claude process. The
  blocklist is deliberate; a wake here is a **regression, not a bonus**.
- **B5** — control: dispatch from a **non-manager** seat → old "woken" line and
  an actual wake. Only managers changed.

> **Already proven by accident:** two real wake-back mails landed in my inbox at
> 21:57 from a test that wasn't mocking subprocess. Wrong reason, right output —
> the body says *"You are a manager, so no agent was woken — that is by design
> and not a failure. This mail IS the wake-back."*

## C. Router silence — @drone

The defect: **1277 of 1279** log lines were one message announcing a non-event,
across 4 rotated generations (~750KB). The router every command passes through
had ~3 hours of history.

```bash
L=$AIPASS_HOME/system_logs/drone_drone.log
b=$(wc -l < $L); drone @git status; drone @git log 2; drone @git --help; a=$(wc -l < $L)
echo $((a-b))        # -> 0
```

- Output must be **unchanged** — `drone @git status` still prints your files.
  We removed a dead sentence, not a channel.
- `tail -2 $AIPASS_HOME/system_logs/drone_router.log` → still shows
  `Routing @ai_mail [CALLER:DEVPULSE] -> view [...]`.
- **Interactive branches must still render live:** `drone @seedgo checklist <file>`,
  `drone @cli ...`, `drone @spawn ...`. These are module **and** branch, so they
  keep the subprocess lane. If Rich output went flat, the fix overreached.

> **Already run by me, 21:44:** 0 lines added, output intact, router log flowing.

## D. The security case — @drone (no hand-command)

`resolve_branch()` refuses a registry path that **escapes the project root**, and
signalled it by raising `BranchNotFoundError`. The fallback caught that refusal,
matched `is_module`, and **served the blocked branch through module routing.**

Covered by @drone's tests; there's no safe way to exercise it by hand. Nobody was
hunting for this — it surfaced only because the doctrine sent them to look at a
fallback firing on the happy path. It is the most valuable thing the night bought.

## E. Watchdog — @devpulse (mine)

- `ls -l /tmp/aipass-watchdog-active` → mtime always within ~15s
- statusline reads `watchdog:on` green
- 610 tests green, re-run after **all three** branches' changes
- idle cost **0.017–0.022%** of a core, was 7.72%
- live tonight: reported WAKE + COMPLETE for all four dispatches

**Run during the session, not before — these spawn live dispatches and the fleet
is one-agent-at-a-time:**

```bash
WATCHDOG_INTEGRATION=1 .venv/bin/python -m pytest \
  src/aipass/devpulse/tests/test_watchdog_agent.py -q
```

## F. Nothing else moved

- `drone @ai_mail inbox / view / reply / close / sent / contacts` from inside a
  branch — all normal
- `cd src/aipass/ai_mail && python -m pytest tests/ -q` → **1238 passed**
- `drone @seedgo audit aipass @ai_mail` → 100%, no type errors
- @drone: **1194 green**, seedgo 100%

## G. Still open — named, not hidden

- **P1 event enrichment** — the completion event marks *process exit*, not task
  completion, and carries no outcome field. A failure reads byte-identical to a
  success. My wire has a permanent blind spot until this lands; my P5 recovery
  sweep is the cover.
- **`dispatch stop` verb** — no way to stop a dispatch. I killed a PID by hand
  and renamed a lock at midnight.
- **External-tier ledger** for @wren/@vera — needs your ruling, not code.
- **@api** wake-refused vs spawn-died exit codes.
- **29 files uncommitted repo-wide**, 9 ahead of main. Nothing tonight is
  committed — three branches' work sitting on `dev`.

## H. What we could not verify ourselves

`AIPASS_CALLER_IDENTITY_SOURCE` is only observable inside a routed subprocess, so
I took @drone's word plus their test — **but A3 passing is the end-to-end proof**:
it can only succeed if ai_mail is reading a provenance stamp @drone wrote.

Two of @ai_mail's own tests were passing while asserting the opposite of what they
meant, because that variable was ambient in their shell. Their conftest now strips
it. Worth remembering when a test agrees with you too easily.
