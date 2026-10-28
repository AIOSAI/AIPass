[<- Back to the README](../README.md)

# The wake pipeline

**Branch** ai_mail · **Code** `apps/modules/dispatch.py`, `apps/handlers/dispatch/wake.py`, `apps/handlers/dispatch/dispatch_monitor.py`

---

## Dispatch System

The `dispatch` command sends an email and wakes the target branch in one step. Dispatch emails carry `auto_execute: true` and a task header, signaling the target agent to process them as work items.

## Wake Pipeline

1. `dispatch.py` orchestrates: send email via `send_to_single()`, then wake via `wake_branch()`
2. `wake.py` resolves the branch from the registry, checks `citizen_class` (managers are mail-only — wake skips, unless the scheduled lane below applies), finds the `claude` (or, with `--provider codex`, the `codex`) binary, spawns a subprocess
3. `dispatch_monitor.py` wraps the claude process with safety features:
   - **Startup health check** — monitors JSONL session files for 90s, kills if no activity
   - **Auto-retry** — 3 strikes: attempt 1+2 resume, attempt 3 fresh (new session)
   - **Bounce email** — on final failure, sends error report back to sender. A bounce
     drone did not deliver logs one `BOUNCE NOT DELIVERED` warning and ends the
     completion status with `, bounce NOT delivered to @sender` (report, register, feed)
   - **Lock cleanup** — removes `.dispatch.lock` when agent exits
   - **Wake-back** — on agent exit, the original sender is notified. A
     builder-class sender is **woken**; a **manager sender is MAILED, never
     woken** (`_mail_wake_back()`): the manager gate stays, and the mail is the
     wake-back, so a manager always hears that its dispatch finished.
     `dispatch` announces which of the two will happen, by reading
     `is_manager(sender)` up front rather than guessing.
     Wake-back sessions carry an empty sender, so chains terminate at the
     original dispatcher, and `AIPASS_WAKE_DEPTH` caps the chain at
     `MAX_WAKE_DEPTH = 3` regardless. `wake_sender()` returns one of nine
     result tags into `dispatch_wake.log` — `success`, `mailed_manager`,
     `failed_manager_mail`, `blocked_occupied`, `blocked_locked`,
     `blocked_depth`, `skipped_sender`, `skipped_self`, `failed` — so "notified"
     is never inferred from a bare boolean (the manager gate returns `True`
     having woken nothing).
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
by a clock rather than by a person (the 5am maintenance rotation).

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
- **Who passes it.** `@daemon`'s scheduled jobs (`run.py`) pass `scheduled=True` on
  every wake they fire. Every other caller takes the default `False`, and a manual
  manager self-wake stays interactive tmux.
- **Reading the outcome** — `status.find_step("scheduled")` is present only for the
  headless lane; the interactive spawn names its tmux session in the `spawn` step.

## Unattended Wakes: Permissions and Marking

The interactive manager lane is reached only from `@daemon`, so *attachable* is not
*attended*.

**Permissions are always bypassed.** Both spawn lanes pass
`--permission-mode bypassPermissions`, unconditionally: an unattended agent in default
permission mode has tools denied with nobody present to approve them.

**Daemon sessions are marked**, so a person deciding whether to kill a window can tell
daemon work from a leftover session (the manager-interactive lane is not in the dispatch
register). Two markings:

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

## Fable is granted by name

Only the seats in the Fable grant may run Fable (by default @devpulse alone). Every
other agent — every class, every project — runs `DEFAULT_MODEL` when dispatched or
scheduled, and lighter models on request. **The owner alone decides who is in the
grant.**

`resolve_wake_model(target_email, requested)` is the one site that decides, and it
returns a `ModelDecision(model, refusal)`:

| Target | Requested model | Runs on |
|---|---|---|
| in the grant | `fable` / `claude-fable-5` / `FABLE` | that model — the grant is permission to **ask** |
| in the grant | nothing | `DEFAULT_MODEL` — a grant is not a standing assignment |
| not in the grant | any spelling of Fable | `DEFAULT_MODEL`, **and the refusal is returned** |
| anyone | anything else, or nothing | unchanged: the `wake.model` field, else `DEFAULT_MODEL` |

- **Granted by name, not by class.** `citizen_class` is not an input: a rule keyed on a
  class cannot say "this one manager and no other". The class decides only the manager
  *gate* — who is woken at all versus mailed.
- **The grant lives where the repo cannot ship it.** `CONFIG_FILE` →
  `.ai_mail.local/safety_config.json` (gitignored), key `fable_allowed`, a list of
  addresses. Absent, unparseable, or not-a-list falls back to `FABLE_GRANT_DEFAULT`
  = `{"@devpulse"}` — **never to empty**, because a grant that collapsed on a typo
  would demote @devpulse silently and the only symptom would be devpulse spawning on
  opus. An **explicit** `[]` is honoured: that is how you revoke Fable fleet-wide,
  and it is distinguishable from the key being absent.
- **Refused, never silent, never stalling.** The refusal names the target, the model
  requested and the ruling date, and it is rendered as a `warn` step on the `model`
  label so it reaches the dispatch output the caller actually reads. The wake proceeds on `DEFAULT_MODEL`: the caller asked for
  a model, not for a veto.
- **Substring, not equality.** The CLI takes both `fable` and `claude-fable-5`, so a
  check comparing to the bare alias would let the full id walk past the grant.
- **Addresses normalised** exactly as `is_wake_blocked` normalises them (one leading
  `@`, lowercased), on both sides — a policy keyed on an address is worthless if
  typing it differently promotes *or* demotes a seat.
- **One resolver.** Two sites in `apps/` name a model:
  `wake._spawn_manager_interactive` (interactive tmux) and the headless `base_args` in
  `wake.wake_branch`, and both take the value `wake_branch` already resolved. No second
  path can reach Fable.

## The Codex provider (`--provider codex`)

`dispatch` and `dispatch wake` take `--provider claude|codex|opencode` (default `claude`); any other
value is refused before the mail is sent. `wake_branch(..., provider="codex")` spawns the
Codex CLI through the same monitor, lock, register and wake-back as a Claude wake, with
the same prompt text.

```
codex exec [-m <model>] --json -o <branch>/logs/dispatch_last_message.txt \
  --dangerously-bypass-approvals-and-sandbox "<prompt>"                      # fresh
codex exec resume <thread_id> [-m <model>] --json -o ... "<prompt>"          # resume
```

- **Model.** `--model` is passed verbatim as `-m`; without it no `-m` is sent and Codex
  uses `~/.codex/config.toml`. `resolve_wake_model` and the Fable grant are not consulted:
  both are Claude's. The status block prints `provider → codex` and `model → <slug>` or
  `model → codex config default`.
- **No `--cd`.** The monitor already runs with `cwd=<branch>`, and `resume` has no `--cd`.
- **Managers wake on Codex in the same lanes as on Claude.** Mailed, not woken, by default;
  headless through the monitor in the scheduled and admin lanes; on a @daemon self-wake, a tmux
  session runs `codex [-m <model>] --dangerously-bypass-approvals-and-sandbox "$(cat
  .daemon/last_wake_prompt.txt)"`.
- **The pointer.** `.ai_mail.local/session.json` carries `provider`; a pointer without the
  key is a Claude pointer. A pointer for one provider never resumes the other (`pointer is
  for claude, waking on codex - starting fresh`). A Codex pointer resumes only while its
  rollout file `~/.codex/sessions/YYYY/MM/DD/rollout-*-<thread_id>.jsonl` exists; otherwise
  the wake is fresh (Codex has no `-c`). `--fresh` always starts a new thread.
- **Codex mints the thread id**, so a fresh codex wake writes no pointer before the spawn.
  After a successful run the monitor records `thread.started.thread_id` with
  `set_by: "monitor-codex"`, `provider: "codex"`.
- **The monitor** is told `--provider=codex` before `--`. Startup is any byte on stdout
  within `STARTUP_TIMEOUT` (the `--json` stream is live), not the `~/.claude` JSONL probe.
  A run succeeds when it exits 0, the stream has `turn.completed`, and it has no `error`
  event. Exit 0 without that is `CODEX_STREAM_FAILED` (-5): bounced with the error line
  verbatim and never re-run, because the turn ran and may already have acted. The result is
  the LAST `agent_message` (the text `-o` writes); the report takes it and `usage` from the
  stream. Retries re-run the argv; strike 3 of a `resume` drops `resume <id>` to a fresh
  `exec`.
- **Processes.** `pgrep -l -x 'claude|codex'` and the zombie scan see both CLIs; the occupancy row
  names the one it found (`Interactive codex session in ...`). A `codex` whose first argument is
  `app-server`, `mcp-server` or `exec` is not a session: the app-server daemon a TUI leaves behind
  in its folder (parented by `systemd --user`) never blocks a wake. An unreadable argv counts as a
  session.
- **Not covered for Codex:** no `--max-turns` equivalent (`HARD_TIMEOUT` bounds the run) and
  no rate-limit reading; `_check_rate_limited` reads stderr as for Claude.

## The OpenCode provider (`--provider opencode`)

`wake_branch(..., provider="opencode")` spawns OpenCode 2 through the same monitor, lock,
register, pointer and wake-back as Claude and Codex, with the same prompt text. The binary is
found on `PATH`, else in `~/.opencode/bin` (the installer's home), then the usual directories.

```
opencode run --standalone --format json --auto [-m <provider/model>] "<prompt>"                       # fresh
opencode run --standalone --format json --auto [-m <provider/model>] --session <ses_id> "<prompt>"  # resume
```

- **Flags.** `--standalone` runs a private `opencode serve --stdio` child instead of the user's
  background service, so the wake owns its process and env; the shared server would never see
  provider keys from the waking shell. `--auto` approves every permission
  not explicitly denied; the AIPass hooks are the gates.
- **Model.** `--model` is passed verbatim as `-m` (`provider/model`, optionally `#variant`, e.g.
  `opencode/glm-5.3-flash-free`, one of the two free models documented zero-retention);
  without it no `-m` is sent and OpenCode chooses. The status block prints `provider → opencode`
  and `model → <slug>` or `model → opencode default`. `resolve_wake_model` and the Fable grant
  are Claude's and are not consulted.
- **OpenCode mints the session id.** A fresh wake passes no `--session` and writes no pointer.
  OpenCode's free tier refuses a session whose id is not in OpenCode's own shape, and that
  shape is undocumented, so the fleet never invents one. `sessionID` arrives on the first
  stream line, before any model call; at the end of every attempt, failed ones included, the
  monitor records it (`set_by: "monitor-opencode"`, `provider: "opencode"`). A run refused
  at once still leaves the branch pointing at the session OpenCode created. A resume passes
  the pointer's id as `--session`.
- **The pointer check reads OpenCode's store, never a file glob.** Sessions live in SQLite at
  `~/.local/share/opencode/opencode.db` (`OPENCODE_DB` overrides), table `session_v2`. The
  pointer resumes only when `session_v2` has its id with `directory` equal to the branch; the
  store is opened read-only (`mode=ro`), so a missing store is reported, never created. Any other
  answer, or a pointer for another provider, starts fresh with a new id.
- **Managers** wake in the same lanes as on Codex. On a @daemon self-wake the tmux session runs
  `[OPENCODE_CONFIG_CONTENT='{"model": "<slug>"}'] opencode --standalone --auto --prompt "$(cat
  .daemon/last_wake_prompt.txt)"`. `--standalone` keeps the TUI off the user's shared
  `opencode serve --service`, which keeps the env of whoever started it, so `AIPASS_HOME` would
  never reach the hooks. The TUI has no model flag; the inline config carries the slug.
- **The monitor** is told `--provider=opencode` before `--`. Startup is the first stdout byte.
  The stream is one JSON object per line, `{type, timestamp, sessionID, part|error}`, with no
  closing event. The result is the LAST `text` part; `usage` and `total_cost_usd` sum every
  `step_finish`, and `num_turns` counts them, in the report's shape. An `error` event fails the
  run and stops the retries, because the stream has named its cause; the bounce carries the
  line verbatim. `provider.free-limit` or `status: 429` bounces as `API rate limit (opencode
  429, retryAfter <s>s, ...)` from `retryAfterMs`. Exit 0 with no `text` part is
  `OPENCODE_STREAM_FAILED` (-6), bounced and never re-run. Other failures retry the same argv;
  strike 3 of a resume drops `--session <id>`, so OpenCode mints a new session.
- **Env.** The monitor strips every `OPENCODE*` variable from the agent's env except
  `OPENCODE_DB`, which the wake's store check and the child must agree on.
  It also sets `PWD` to the branch: OpenCode files a session under `PWD`, not the process
  cwd, so an inherited `PWD` would record the caller's directory and break every resume.
- **Processes.** `opencode` is in the pgrep and zombie set. An `opencode serve` with
  `--service` (the user's daemon) or `--stdio` (a standalone child) is not a session; the TUI
  and any other form are.

## The recipient's dashboard is refreshed before the spawn

`wake.py` calls `refresh_recipient_dashboard()` (`apps/handlers/dispatch/wake_dashboard.py`)
for the RECIPIENT branch at the one point past every gate and above all three spawn lanes —
the tmux manager session, the systemd scope and the detached `Popen`. A woken agent reads
`DASHBOARD.local.json` as its single status glance; unrefreshed, the card is whatever its
own last session left behind and reports no new mail while the dispatch that woke it sits
in the inbox.

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

- [wake_lanes.md](wake_lanes.md) — the admin, cross-project and `@all` lanes, and the reply return path
- [dispatch_register_and_feed.md](dispatch_register_and_feed.md) — the register row a wake opens and the feed it writes
- [identity_and_boundaries.md](identity_and_boundaries.md) — who may claim to be the sender a wake trusts
- [sending_and_delivery.md](sending_and_delivery.md) — the delivery pipeline a dispatch rides in on
- [cli_contract.md](cli_contract.md) — exit codes and the help-flag rule
