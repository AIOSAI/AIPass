[<- Back to the README](../README.md)

# Subprocess timeouts — a hang guard, not a performance budget

**Branch** drone · **Code** `apps/handlers/executor.py`, `apps/modules/router.py`

Routed commands run with a timeout resolved in this order — **explicit flag > per-command policy >
default**:

| Layer | Value | Where |
|-------|-------|-------|
| Default | **600s** | `DEFAULT_TIMEOUT` |
| Per-command policy | **none — the table ships empty** | `TIMEOUT_OVERRIDES` |
| Explicit | whatever you pass | `--drone-timeout <n>` |
| Extension quantum | **120s** | `IDLE_GRACE` |
| Hard ceiling | **1800s** | `MAX_TIMEOUT` |

All five live in `apps/handlers/executor.py`.

---

## Why 600

The default was raised 30 → 60 on 2026-08-13 (the owner's ruling): two known runners finish around
31s and were tripping the old default. It was raised again 60 → 600 on 2026-08-27, after two live
kills in one morning — the fleet-wide trinity push died at 60s mid-alphabet (it needs about five
minutes; the re-fire used `--drone-timeout 900`), and an `@all` mail broadcast was killed at 60s
*after* every message had been delivered. The owner's ruling: *"it is configured wrong — it should not
be timing out before it completes; processing time is fine, increase the allowed timeout so things
can actually complete."*

**The timeout is sized for the worst *legitimate* case.** Per-verb budgets were considered and
rejected: an integer per command cannot tell `email @seedgo` from `email @all`, which is one verb
with two very different worst cases.

**`TIMEOUT_OVERRIDES` is empty on purpose.** It held three entries — `memory process-plans` 120s,
`memory rollover` 100s, `flow close` 90s — and every one of them was written to *raise* above the
old 60s default. Against a 600s base the same numbers invert into *caps*: the commands we know are
slow would get the least time in the fleet. The mechanism stays, because a per-command policy is a
decision, not a floor — it still wins even if it is *lower* than the default (`resolve_timeout` has
no `max()`, and a test pins that). Only the now-harmful data is gone.

---

## Output extends life

Nothing is killed before the base timeout, however silent it is. If the child has produced output
within the last `IDLE_GRACE` when the deadline arrives, the deadline moves out by another
`IDLE_GRACE` instead of killing — repeatedly, while it keeps talking, up to `MAX_TIMEOUT`, which
nothing can pass. A child that has said *nothing at all* never extends: silence is not output.

**The ceiling caps extension, never the base.** If a number above `MAX_TIMEOUT` is asked for — an
operator's `--drone-timeout 3600`, or a future `TIMEOUT_OVERRIDES` entry — that number is honoured
in full; the ceiling only bounds how far *extension* can push a deadline past it. A ceiling that
quietly became a maximum would kill work earlier than the number actually requested, which is the
failure this whole design exists to end.

*The honest edge:* a long **silent** computation gets only the base. Extension is earned by
talking, so a quiet fifteen-minute job still needs `--drone-timeout`. This adds no new false-kill
mode — silence never *shortens* anything, it just does not lengthen it.

**An explicit `--drone-timeout N` means exactly N.** `route_command()` passes
`extend_on_output=False` whenever the operator named a number, because a deliberate tight cap that
silently stretches is worse than no cap. The routing log line states the extension state next to
the timeout.

---

## When something is killed

**A killed child is chased down and reported.** The kill path is a ladder — `terminate()`, wait,
then `kill()`, then wait again to reap — and the one rung that can leave something behind says so:
a child still unreaped after `SIGKILL` logs a **WARNING** naming its pid, because a zombie held for
the lifetime of this process is otherwise invisible. Every other rung logs at debug; none is silent.

**A killed command still reports what it did.** The timeout error replays the child's partial
stdout and stderr under `--- partial stdout (N bytes) ---` banners, truncated to the last 4000
characters *and told so when truncated*, and the chained `subprocess.TimeoutExpired` carries the
same bytes on `.output` / `.stderr`. This is the other half of the `@all` broadcast defect: every
message was delivered, and the old error said only *"Command timed out after 60s"* because the
child's captured output was discarded with the exception.

---

## Two lanes take no timeout, and say so

Module routing runs in-process, and interactive commands inherit the terminal — neither is
captured, so neither can be timed. The flag still *parses* there, so before this an operator's
number vanished in silence: `drone @seedgo audit aipass --drone-timeout 5` ran unbounded and said
nothing. Both lanes now emit a WARNING to the log and to stderr naming the number and the reason. A
silently discarded cap is the same species of defect as a silent kill.

---

## Where the flag goes

Anywhere **after** the `@target`, including after the routed command and its arguments. It is
stripped from the argument list before routing, so the target branch never sees it. Before the
target, drone refuses it as an unknown command — the flag belongs to the routing call, not to the
binary.

The signature defaults of `execute_command()` and `execute_branch_command()` reference
`DEFAULT_TIMEOUT` rather than restating the number, so the layers cannot silently disagree.
`tests/test_executor.py::TestDefaultTimeoutValue` pins the number itself and asserts all three
layers agree.

---

## Related

- [routing_and_resolution.md](routing_and_resolution.md) — which lane a command takes
