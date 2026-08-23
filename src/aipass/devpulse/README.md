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
│   │   └── watchdog.py          # Directed wake system command routing
│   ├── handlers/
│   │   ├── compass/             # Decision store (SQLite/FTS5), rating, query, review
│   │   ├── feedback/            # Inbox, compose, storage
│   │   ├── json/                # JSON operation logging (json_handler)
│   │   ├── owner/               # Owner gate + admin grant (keygen, mint, 5-leg verify)
│   │   └── watchdog/            # Agent, timer, schedule, registry
│   └── plugins/                 # Plugin extension point
├── devpulse_json/               # JSON handler storage (config, data, logs per module)
├── tests/                       # 448 tests
├── artifacts/                   # Birth certificate, reports
├── dropbox/                     # Received files, archived plans, install audit
├── docs/                        # Transition notes
└── DASHBOARD.local.json         # Live state (refreshed by prax)
```

## Commands

All commands via `drone @devpulse <command>`:

### Watchdog — directed wake system (owner-only)

**Who may call it:** the project OWNER only — the first agent, seated as `owner: true`
in the project's sealed `*_REGISTRY.json`. Portable: `@devpulse` in AIPass, `@vera` in
Vera Studio, whoever owns elsewhere. A refusal means your project's owner isn't seated —
run `aipass doctor` to see why and `aipass doctor --fix` to repair (DPLAN-0239).

**How the wake works (read this once, save a debugging session):**

1. `drone @ai_mail dispatch @target "Subject" "Body"` — hand off the work.
2. **Immediately arm the watchdog via the harness Monitor TOOL** — never Bash
   `run_in_background` (its output goes nowhere and cannot wake you):
   `drone @devpulse watchdog agent @target --timeout 600`
3. The status line shows **"1 monitor"** the moment it's armed — that IS the
   active-dispatch indicator. When `@target` finishes, the watchdog exits, the
   Monitor completes, and **your session is re-invoked with the result — that IS
   the wake.**

There is no passive wake: ai_mail's wake-back spawns a new headless process and can
never inject into a live interactive session (`BLOCKED — interactive session` in the
logs is that guard working as designed; it only serves senders whose session closed).
If you dispatched and idle without arming, nothing will ever wake you.

`@target` resolves in the **caller's own project** (then falls back to scanning
`~/Projects` registries) — external-project owners monitor their own agents with it.
Default timeout is **600 s**; pass `--timeout <s>` for longer builds. Mid-watch it
also emits `[watchdog.stall]` / `[watchdog.resumed]` events (no JSONL activity 120 s
with no in-flight tool = probable stuck agent).

**Baseline — the always-on wake (round 4, DPLAN-0317):** completion is
**reported, not discovered.** The agent that finishes says so; `@ai_mail` writes
that report to a durable notification feed, and a per-session *wire* (armed via
the Monitor tool: `drone @devpulse watchdog baseline`) turns each report into a
wake. Nothing polls, nothing is scheduled, and at idle the entire system is one
`stat()` on a file.

Two rules the wire enforces and neither is optional:

- **Only completions wake.** The feed also carries dispatch *start* edges, and
  those are dropped. An agent may mail a report and then mail a correction —
  you want to be woken once, when it is actually finished.
- **Only YOUR dispatches wake you.** The feed names the branch that *finished*,
  never the branch that *sent* the work, so every citizen's completion used to
  wake this seat fleet-wide. `@ai_mail` now stamps `sender` on the completion
  line and the wire compares it against this project's sealed owner. A record
  with no sender is **not** yours — unattributable fails closed.

`/clear` or a new chat kills the wire; nothing else is running to kill. The
reports stay on the feed, so re-arming replays whatever arrived while you were
gone as `MISSED` lines. The statusline shows `watchdog:on` (green) only when a
wire for the *current* session is live **and** ticking; `HUNG`, `UNWIRED` and
`off` are all "re-arm".

**Crash coverage without a watcher:** every dispatch is registered at send time
with an `expected_by` taken from dispatch_monitor's hard timeout. An entry past
that with no completion means the monitor *died* — and that is a fact about a
file, true whether or not anything is looking. `watchdog status` reads it. There
is nothing to keep alive for it to be noticed.

**Round 3 and earlier had a detection daemon. It is gone.** `baseline.py` was a
detached process polling ~19 branches' `.dispatch.lock` every 2 s to work out
who had finished. It was deleted because **the event it synthesised was already
being written**: `dispatch_monitor.py` reports the completion 1–2 s *before* the
poll notices the lock disappear, and the wire was draining both sources with no
dedupe between them. Every completion produced **two wakes**, for months, and
nobody spotted it because a duplicate wake looks exactly like a working wake.
Measured live on 2026-08-22 — events file vs notification feed, same events:

```
08:51:59 backup  | 08:51:59 backup
08:52:15 daemon  | 08:52:14 daemon
08:55:02 spawn   | 08:55:00 spawn
11:16:02 flow    | 11:16:01 flow
```

Idle cost before r3's gate: **7.72% of a core** — 1640 CPU-seconds across 5.9
hours in which zero dispatches occurred. r3 gated that to 0.017%, which was the
wrong fix: `feed.py`'s own header already said *"detection by inference is
replaced by detection by report."* The comment named the destination; the code
took one step. r4 took the rest.

The daemon's source is preserved where source is preserved — **git history**,
recoverable at the commit that removed it. It is deliberately not parked in a
`.archive/` directory: those are gitignored disposal zones, cleaned without
warning, so nothing that must survive may live there.
`watchdog baseline --daemon` is refused by name.

| Command | What it does |
|---|---|
| `watchdog baseline` | Arm the always-on wake for this session (takes over any older wire) |
| `watchdog agent @target [--timeout s]` | Wake when the dispatched agent exits (default 600 s) |
| `watchdog timer <duration>` | Wake after duration (5m, 30s, 2h, 1h30m) |
| `watchdog timer start/stop <name>` | Named duration tracking |
| `watchdog schedule <HH:MM>` | Wait until a specific time |
| `watchdog status` | Show active watchdogs |
| `watchdog cancel <id>` | Cancel a running watchdog |
| `watchdog list` | List all watchdog entries |

### Feedback — the owner-to-owner channel (owner-only)

ai_mail and dispatch stop at the project boundary — **cross-project comms is
impossible by design, except feedback.** Project owners (managers) talk owner-to-owner
through it: an external project's owner runs `drone @devpulse feedback send ...` from
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

### Compass — rated decision store

Curated truth-store of rated decisions (`good` / `bad` / `impressive` / `interesting`) — repeat the good, avoid the bad. Devpulse-owned SQLite/FTS5, separate from @memory (which ingests everything; compass is judged decisions only). The DB is gitignored.

| Command | What it does |
|---|---|
| `compass add "context" "decision" --rating R` | Store a rated decision (`--note`, `--tags`, `--source`) |
| `compass query "question" [--rating R] [--limit N]` | Search decisions (rating shown per hit) |
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
| seedgo | Standards audits, checkers (35 standards) |
| prax | Monitoring, logs, dashboard |
| memory | ChromaDB vectors, archival, search |

### Provides To

All branches via dispatch orchestration. Watchdog monitoring for any dispatched agent. Feedback channel for cross-branch communication. Git operations (commit, PR, merge) for the entire project.

*Last Updated: 2026-08-19*

---

[← Back to AIPass](../../../README.md)
