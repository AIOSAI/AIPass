[← Back to AIPass](../../../README.md)

# DevPulse

> Orchestration hub for AIPass. The user's primary AI collaborator — designs, plans, debugs, coordinates the other branches, and builds its own modules.

DevPulse handles the day-to-day: working with the user to plan, design, troubleshoot, and adjust. It builds its own modules directly (watchdog, feedback, json_handler), manages all git operations for the project, dispatches heavy multi-file builds to sub-agents, and ventures into other branches to investigate, debug, and fix small bugs. The only branch with git write access.

## Start here

| You want to | Read |
|---|---|
| What's happening right now | `DASHBOARD.local.json` |
| Identity, memory, session history | [`.trinity/`](.trinity/) |
| Active plans | `drone @flow list open` |
| Branch list | `drone systems` |

## Quick Start

```bash
# Talk to the hub — it picks up where the last session left off
cd src/aipass/devpulse
claude

# Or drive it via drone from anywhere in AIPass
drone @devpulse compass query "registry"   # search rated decisions
drone @devpulse feedback inbox             # cross-project feedback
```

## Invoke

```bash
cd src/aipass/devpulse
claude
```

Say "hi" and DevPulse picks up where the last session left off — reads identity, memory, inbox, and git status automatically.

## Architecture

```
src/aipass/devpulse/
├── .trinity/                    # Identity & memory (passport, local, observations)
├── .aipass/                     # Branch prompt (injected every turn)
├── .ai_mail.local/              # Mailbox (dispatch, notifications)
├── apps/
│   ├── devpulse.py              # Entry point — auto-discovers modules
│   ├── modules/
│   │   ├── admin_grant.py       # Birth-cert admin privilege ceremony command routing
│   │   ├── compass.py           # Rated decision engine (SQLite/FTS5) command routing
│   │   ├── feedback.py          # Feedback mailbox command routing
│   │   └── watchdog.py          # Always-on dispatch reporting + directed wakes
│   ├── handlers/
│   │   ├── compass/             # Decision store (SQLite/FTS5), rating, query, review
│   │   ├── feedback/            # Inbox, compose, storage
│   │   ├── json/                # JSON operation logging (json_handler)
│   │   ├── owner/               # Owner gate + admin grant (keygen, mint, 5-leg verify)
│   │   └── watchdog/            # Agent, timer, schedule, registry
│   ├── integrations/            # Extension point (empty — README only)
│   └── plugins/                 # Plugin extension point (empty — README only)
├── devpulse_json/               # JSON handler storage (config, data, logs per module)
├── tests/                       # 598 tests (594 passed, 4 skipped — 2026-08-25)
├── tools/                       # One-shot scanners & probes (~30 scripts) + reports/
├── prototypes/                  # Shape-exploration prototypes
├── templates/                   # Local templates
├── artifacts/                   # Birth certificate, reports
├── dropbox/                     # Received files, archived plans, campaign logs
├── docs/                        # Transition notes
└── DASHBOARD.local.json         # Live state (refreshed by prax)
```

## Commands

All commands via `drone @devpulse <command>`:

### Watchdog — always-on dispatch reporting (owner-only)

**Who may call it:** the project OWNER only — the first agent, seated as `owner: true`
in the project's sealed `*_REGISTRY.json`. Portable: `@devpulse` in AIPass, `@vera` in
Vera Studio, whoever owns elsewhere. A refusal means your project's owner isn't seated —
run `aipass doctor` to see why and `aipass doctor --fix` to repair (DPLAN-0239).

**The model — a login, not a service (r4, DPLAN-0317):** watchdog is always on
because nothing runs. Dispatching registers the job at send time; the agent that
finishes **reports**; `@ai_mail` writes that report to a durable notification
feed, where it **queues** whether anyone is listening or not. A conversation
**signs in** to receive — one call via the harness Monitor TOOL (never Bash
`run_in_background`, whose output goes nowhere):

```
drone @devpulse watchdog baseline
```

Sign-in syncs whatever queued while you were logged out (`MISSED` lines), pushes
new reports live from then on, and logs out any older session — the newest
sign-in owns delivery. `/clear` or a new chat destroys only the receiver — the
conversation's ear; reports keep queueing regardless. At idle the entire system
is one `stat()` on a file. The harness status line's **"1 monitor"** is the
signed-in session itself, not a watcher — nothing is being watched.

Statusline: `watchdog:in` (green) — this session is signed in and ticking.
`HUNG` (signed in, receiver frozen), `ELSEWHERE` (another session holds the
sign-in), `OUT` (nobody is signed in) — all red, all mean sign in again.

**There is no passive wake.** ai_mail's wake-back spawns a new headless process
and can never inject into a live interactive session (`BLOCKED — interactive
session` in the logs is that guard working as designed; it only serves senders
whose session closed). Dispatch and idle without signing in and nothing will
ever wake you — the report just queues.

Two rules the receiver enforces, neither optional:

- **Only completions wake.** The feed also carries dispatch *start* edges, and
  those are dropped — you are woken once, when the work is actually finished.
- **Only YOUR dispatches wake you.** The feed names the branch that *finished*,
  never the branch that *sent*, so every citizen's completion used to wake this
  seat fleet-wide. `@ai_mail` stamps `sender` on the completion line and the
  receiver compares it against this project's sealed owner. A record with no
  sender is **not** yours — unattributable fails closed.

**Crash coverage needs nothing running.** Every dispatch is registered at send
time with an `expected_by` taken from dispatch_monitor's hard timeout. An entry
past that with no completion means the monitor *died* — a fact about a file,
true whether or not anything is looking. `watchdog status` reads it.

**Rounds 1–3 had a detection daemon; r4 deleted it** (commit `5444dd9a`). It
polled ~19 branches' `.dispatch.lock` every 2 s to synthesize an event that
`dispatch_monitor.py` had already reported 1–2 s earlier — every completion
produced **two wakes**, for months, unnoticed because a duplicate wake looks
exactly like a working wake. Idle cost: 7.72 % of a core. The source is
preserved where source is preserved — git history, at the removing commit —
deliberately not in `.archive/` (gitignored disposal, cleaned without warning).
`watchdog baseline --daemon` is refused by name.

`watchdog agent @target [--timeout s]` remains for **mid-run stall detection**
on a single long job (`[watchdog.stall]` / `[watchdog.resumed]` after 120 s of
JSONL silence with no in-flight tool) — it is no longer needed to be woken, and
arming one per dispatch is a second poller doing the receiver's job. `@target`
resolves in the caller's own project, then falls back to `~/Projects`
registries.

| Command | What it does |
|---|---|
| `watchdog baseline` | Sign this session in to receive dispatch reports (logs out any older session) |
| `watchdog baseline --once` | Wire until the first delivered completion (run_in_background form) |
| `watchdog agent @target [--timeout s]` | Stall-watch one dispatched agent (default 600 s) |
| `watchdog timer <duration>` | Wake after duration (5m, 30s, 2h, 1h30m) |
| `watchdog timer start/stop <name>` | Named duration tracking |
| `watchdog timer list / report` | Active + historical timers / formatted session summary |
| `watchdog schedule <HH:MM \| +N> [command]` | Wait until a time (or +duration), optionally run a command |
| `watchdog status` | Signed-in session, outstanding dispatches, overdue entries |
| `watchdog cancel <handle>` | Cancel one watch (`--all` kills every active watch) |
| `watchdog list` | Alias for status |

### Feedback — the owner-to-owner channel (owner-only)

Dispatch crosses the project boundary in ONE direction only — devpulse's admin
seat reaches out; a dispatched project citizen answers on ai_mail's reply lane
(replies-only return path). For everything else, **feedback is the cross-project
channel**: an external project's owner runs `drone @devpulse feedback send ...` from
their project and it lands in devpulse's feedback mailbox; devpulse answers with
`feedback reply`. Same owner gate as watchdog — unseated projects are refused until
`aipass doctor --fix` seats them.

| Command | What it does |
|---|---|
| `feedback` | Inbox summary |
| `feedback inbox` | List all messages |
| `feedback view <id>` | Read a message |
| `feedback reply <id> "msg"` | Reply to sender |
| `feedback send "subject" "body"` | Send feedback to devpulse (any project's owner may call) |
| `feedback clear <id>` | Remove a message (`--all` removes all read) |

### Compass — rated decision store

Curated truth-store of rated decisions (`good` / `bad` / `impressive` / `interesting`) — repeat the good, avoid the bad. Devpulse-owned SQLite/FTS5, separate from @memory (which ingests everything; compass is judged decisions only). The DB is gitignored.

| Command | What it does |
|---|---|
| `compass add "context" "decision" --rating R` | Store a rated decision (`--note`, `--tags`, `--source devpulse\|user`, `--supersedes N` archives+links the corrected entry) |
| `compass query "question" [--rating R] [--limit N] [--include-archived]` | Search decisions (rating shown per hit) |
| `compass stats` | Counts by rating / status |
| `compass rate <id> <rating>` | Re-rate a decision |
| `compass archive <id>` | Archive a decision |
| `compass note <id> "text"` | Set a decision's note |
| `compass review` | Surface one decision to review |

### Admin grant — birth-cert privilege ceremony (owner-only mint)

Devpulse — and only devpulse — holds an admin privilege that lets it dispatch ANY
agent, managers included (DPLAN-0288 / FPLAN-0401). The grant is a signed
`privileges` block on the existing birth certificate (`artifacts/birth_certificate.json`),
HMAC-SHA256 signed with a key OUTSIDE every repo (`~/.aipass/admin_grant.key`).
Verification is a 5-leg contract — caller, cert-path-from-registry, content,
signature, registry flag — all must pass, every refusal named, missing key = lane
dark. This module is the ceremony tooling and the contract's reference
implementation; @ai_mail mirrors it on the dispatch lane. The user runs the ceremony.

| Command | What it does |
|---|---|
| `admin_grant status` | Ceremony/lane state (key, cert, signature, verify) |
| `admin_grant verify` | Run the full 5-leg contract check |
| `admin_grant keygen` | Generate the signing key (owner-only, refuses overwrite) |
| `admin_grant mint` | Add + sign the admin privilege block (owner-only) |

## Git Operations

DevPulse is the only branch with git write access. All git/gh commands are blocked at the project level — drone bypasses via subprocess with a tier system that grants write only to devpulse.

Workflow: work on `dev` branch, PR to `main` when satisfied. Agents build and test, devpulse reviews and commits.

```bash
drone @git status --all          # Full repo changes
drone @git commit "msg" --all    # Commit all changes
drone @git dev-pr "description"  # PR dev→main
drone @git merge <PR#>           # Merge PR (user requests only)
drone @git sync                  # Pull latest
drone @git log                   # Recent commits
```

## Integration Points

### Depends On

| Branch | What for |
|---|---|
| drone | Command routing, subprocess, @branch resolution |
| ai_mail | Dispatch (send + wake agents), email delivery |
| flow | FPLANs (building), DPLANs (planning), APLANs (autonomous) |
| seedgo | Standards audits, checkers (45 standards) |
| prax | Monitoring, logs, dashboard |
| memory | ChromaDB vectors, archival, search |

### Provides To

All branches via dispatch orchestration. Watchdog reporting for every dispatched agent. Feedback channel for cross-branch communication. Git operations (commit, PR, merge) for the entire project.

## Status & Known Issues

Verified 2026-08-25 (README truth pass — every command above run read-only, tests executed, counts measured).

- **Live bug** — `watchdog/registry.py:425` `killed or True` is always True: `watchdog cancel` prints KILLED even when the process survived SIGTERM. No test covers it (all 3 assert True). Fix queued as its own commit.
- **Refusals that exit 0** — feedback, admin_grant (×2) and compass (×3) use `warning()` for refusals, which skips `mark_command_failed()`, so a refused command exits 0. Fleet-wide sweep pending (@canary).
- **statusline.sh untracked** — the watchdog statusline lives at `~/.claude/statusline.sh`, outside the repo; on any other machine watchdog paints red until hand-copied. Fix direction undecided (Patrick's call — provider config dir).
- **Foreground-wire gap** — a `baseline` wire armed without the Monitor tool still paints `watchdog:in` green with no listener; `via=monitor` field offered, awaiting go-ahead.

*Last Updated: 2026-08-25*

---

[← Back to AIPass](../../../README.md)
