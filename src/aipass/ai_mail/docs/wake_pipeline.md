# The wake pipeline

**Branch** ai_mail · **Code** `apps/modules/dispatch.py`, `apps/handlers/dispatch/wake.py`, `apps/handlers/dispatch/dispatch_monitor.py`, `apps/handlers/dispatch/daemon.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## Dispatch System

The `dispatch` command sends an email and wakes the target branch in one step. Dispatch emails carry `auto_execute: true` and a task header, signaling the target agent to process them as work items.

## Wake Pipeline

1. `dispatch.py` orchestrates: send email via `send_to_single()`, then wake via `wake_branch()`
2. `wake.py` resolves the branch from the registry, checks `citizen_class` (managers are mail-only — wake skips, unless the scheduled lane below applies), finds the `claude` binary, spawns a subprocess
3. `dispatch_monitor.py` wraps the claude process with safety features:
   - **Startup health check** — monitors JSONL session files for 90s, kills if no activity
   - **Auto-retry** — 3 strikes: attempt 1+2 resume, attempt 3 fresh (new session)
   - **Bounce email** — on final failure, sends error report back to sender
   - **Lock cleanup** — removes `.dispatch.lock` when agent exits
   - **Wake-back** — on agent exit, the original sender is notified. A
     builder-class sender is **woken**; a **manager sender is MAILED, never
     woken** (`_mail_wake_back()`), because the manager gate is deliberate and
     stays — telling a manager "you will be woken" was a promise the lane could
     not keep, and the manager then heard nothing at all — three live cases on
     2026-08-21 alone, and `skipped_manager` rows across the fleet's
     `dispatch_wake.log` files from 2026-08-04 on.
     `dispatch` announces which of the two will happen, by reading
     `is_manager(sender)` up front rather than guessing.
     Wake-back sessions carry an empty sender, so chains terminate at the
     original dispatcher, and `AIPASS_WAKE_DEPTH` caps the chain at
     `MAX_WAKE_DEPTH = 3` regardless. `_wake_sender()` returns one of nine
     result tags into `dispatch_wake.log` — `success`, `mailed_manager`,
     `failed_manager_mail`, `blocked_occupied`, `blocked_locked`,
     `blocked_depth`, `skipped_sender`, `skipped_self`, `failed` — so "notified"
     is never inferred from a bare boolean. It was: the manager gate returns
     `True` having woken nothing, and trusting that bool logged "woken" for a
     wake that never happened.
     Library callers such as @daemon's scheduled nudges may pass
     `wake_back=False` to `wake_branch()` (carried to the monitor as the
     `--no-wake-back` argv flag, logged and recorded as `declined` in
     `dispatch_wake.log`); the `dispatch` and `dispatch wake` CLI verbs always
     arm the wake-back

## Safety Limits

- PID-based locking prevents concurrent agents per branch (`.dispatch.lock`)
- Max turns per wake, max dispatches per branch per day
- `WAKE_BLOCKLIST` protects `@devpulse` from cross-branch manual wakes
- **Manager structural block** — branches with `citizen_class: "manager"` in their passport (e.g. `@devpulse`) are unwakeable on the dispatch and manual paths. Mail delivers, wake skips. The three exceptions (scheduled, admin, @daemon self-wake) are named below
- **Self-wake guard** — if sender equals target, wake-back is skipped (prevents self-loops)
- **Chain termination** — wake-back sessions carry an empty sender, so the chain always stops at the original dispatcher; `MAX_WAKE_DEPTH = 3` on `AIPASS_WAKE_DEPTH` bounds it even if that were bypassed
- `dispatch_monitor.py` strips `AIPASS_CALLER_*` env vars to prevent parent context leaking into agent identity
- `AIPASS_BRANCH_NAME` env var set in spawn_env for CWD-independent identity

## Scheduled Lane (`scheduled=True`)

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

## Unattended Wakes: Permissions, Model, and Marking

Three rulings from Patrick on 2026-08-30, all after @vera's first external daemon
wake. The fire itself worked; the **lane** failed three ways around it.

**1 — Always bypass permissions.** *"always bypass permissions always, claude alone
will nvr work."* @vera launched as a bare `claude`, sat in default permission mode,
and had Bash **denied** mid-playbook with nobody present to approve it — she
improvised around it with WebFetch, which is not a thing an unattended agent should
ever have to do. The headless lane had carried `--permission-mode bypassPermissions`
for months; the interactive manager lane had not. It does now, unconditionally:
every route into that spawn comes from `@daemon`, so *attachable* was never the same
thing as *attended*.

**2 — Fable is managers-only.** ***SUPERSEDED 2026-09-08 — see "Fable is granted by
name" below.*** The 08-30 wording was *"managers are fable thats it, only manager run
fable"*, and it is recorded here rather than deleted because the rule that replaced it
was written by watching this one fail: @vera is manager-class, so on 2026-09-08 at
11:31 she woke on Fable through the daemon's scheduled lane, and nobody had asked her
to. A rule keyed on a *class* cannot say "this one manager and no other".

**3 — Daemon sessions are marked.** Patrick killed @vera's live session mid-run: it
was not in the dispatch register (the manager-interactive lane bypasses it) and
`daemon-vera-192848` read as his own leftover tmux. Two markings:

- **The session name**, `AIPASS-DAEMON-WAKE-<branch>-<HHMMSS>` — guaranteed, because
  tmux either creates the session under that name or `new-session` already failed.
  Loud on purpose: it is read by a person deciding whether to kill a window.
- **A tmux user option**, `@aipass_daemon_wake`, carrying branch/sender/start time —
  the queryable half (`tmux show-options -v -t <session> @aipass_daemon_wake`), so a
  tool need not string-match a prefix. Set **before** the agent starts, because a
  window is killable from the moment it exists. Best-effort: a failure is a `warn`
  step on the `mark` label and the wake proceeds — refusing to start real work over
  a cosmetic label is the worse trade, but the thin marking is said out loud.

**Not the dispatch register, and the reason is the register's own contract.**
`open_dispatch()` takes `expected_seconds` from the lane's real timeout, and the
interactive lane has no monitor and no timeout. Every entry it wrote would stay
outstanding forever and go overdue against a number invented here — turning crash
detection into a wall of false alarms. Marking a window and tracking a promised
dispatch are two questions; only one of them has a monitor to close it. The
**headless** lane registers and is closed by `dispatch_monitor`, which is why
routing scheduled manager wakes through it (`scheduled=True`) answers marking and
supervision together.

## Fable is granted by name (Patrick, 2026-09-08)

*"only devpulse runs on fable (I carry the admin baggage)."* Every other agent —
every class, every project, Vera-Studio included — runs `DEFAULT_MODEL` when
dispatched or scheduled, and lighter models on request. **Patrick alone decides who
may run Fable**, @devpulse included. This supersedes the 2026-08-30 ruling above
(compass #323 → #350).

`resolve_wake_model(target_email, requested)` is the one site that decides, and it
returns a `ModelDecision(model, refusal)`:

| Target | Requested model | Runs on |
|---|---|---|
| in the grant | `fable` / `claude-fable-5` / `FABLE` | that model — the grant is permission to **ask** |
| in the grant | nothing | `DEFAULT_MODEL` — a grant is not a standing assignment |
| not in the grant | any spelling of Fable | `DEFAULT_MODEL`, **and the refusal is returned** |
| anyone | anything else, or nothing | unchanged: the `wake.model` field, else `DEFAULT_MODEL` |

- **Granted by name, not by class.** `citizen_class` is no longer an input. It still
  decides the manager *gate* — who is woken at all versus mailed — and that is a
  different question the same constant used to answer twice.
- **The grant lives where the repo cannot ship it.** `CONFIG_FILE` →
  `.ai_mail.local/safety_config.json` (gitignored), key `fable_allowed`, a list of
  addresses. Absent, unparseable, or not-a-list falls back to `FABLE_GRANT_DEFAULT`
  = `{"@devpulse"}` — **never to empty**, because a grant that collapsed on a typo
  would demote @devpulse silently and the only symptom would be devpulse spawning on
  opus. An **explicit** `[]` is honoured: that is how you revoke Fable fleet-wide,
  and it is distinguishable from the key being absent. *(That file pointed at the
  branch root — tracked territory — until this ruling; nothing existed at either
  path, so `_load_config` had always returned its own defaults.)*
- **Refused, never silent, never stalling.** The refusal names the target, the model
  requested and the ruling date, and it is rendered as a `warn` step on the `model`
  label so it reaches the dispatch output the caller actually reads — the superseded
  version only logged it. The wake proceeds on `DEFAULT_MODEL`: the caller asked for
  a model, not for a veto.
- **Substring, not equality.** The CLI takes both `fable` and `claude-fable-5`, so a
  check comparing to the bare alias would let the full id walk past the grant.
- **Addresses normalised** exactly as `is_wake_blocked` normalises them (one leading
  `@`, lowercased), on both sides — a policy keyed on an address is worthless if
  typing it differently promotes *or* demotes a seat.
- **One resolver, measured.** Three sites in `apps/` name a model:
  `wake.py:884` (interactive tmux) and `wake.py:1133` (headless `base_args`) both
  take the value `wake_branch` already resolved, and `daemon.py:423` hardcodes
  `DEFAULT_MODEL` in a module its own comment documents as dormant. No second path
  can reach Fable.

## The recipient's dashboard is refreshed before the spawn

`wake.py` calls `refresh_recipient_dashboard()` (`apps/handlers/dispatch/wake_dashboard.py`)
for the RECIPIENT branch at the one point past every gate and above all three spawn lanes —
the tmux manager session, the systemd scope and the detached `Popen`. A woken agent reads
`DASHBOARD.local.json` as its single status glance, and nothing refreshed it on the way in:
the card it read was whatever its own last session left behind, reporting no new mail while
the dispatch that woke it sat in the inbox.

- **One branch, never the fleet.** prax's `refresh_all_dashboards` walks every branch; the
  recipient is one of them, and the other cards are nobody's business on this path.
- **Fail-open, and it is the one exemption from failing honestly in this file.** An import
  that cannot resolve, a raise, an error status prax RETURNED rather than raised, or a
  refresh still running at `DASHBOARD_REFRESH_TIMEOUT` each record one prax WARNING naming
  the branch and a `warn` step — then the spawn goes ahead. A stale dashboard costs the
  woken agent one refresh of its own; a wake that dies costs the dispatch.
- **The bound needs a thread.** `signal.alarm` is POSIX-only and main-thread-only, and this
  runs under the daemon as often as under a terminal, so the refresh runs in a daemon thread
  with `join(timeout)`. An overrun is left behind, named, and cannot hold the process open.
- **The import is local, and through prax's module door** (`aipass.prax.apps.modules.dashboard`),
  never its handler. A module-level import would make a broken prax dashboard an ImportError
  at ai_mail import time — every wake dead for a dashboard, the exact trade the fail-open
  exists to refuse.

## Related

- [wake_lanes.md](wake_lanes.md) — the admin, cross-project, `@all` and daemon lanes
- [dispatch_register_and_feed.md](dispatch_register_and_feed.md) — the register row a wake opens and the feed it writes
- [identity_and_boundaries.md](identity_and_boundaries.md) — who may claim to be the sender a wake trusts
- [sending_and_delivery.md](sending_and_delivery.md) — the delivery pipeline a dispatch rides in on
- [cli_contract.md](cli_contract.md) — exit codes and the help-flag rule
- [known_issues.md](known_issues.md) — open defects, all registered in APLAN-0006
