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

| Command | What it does |
|---|---|
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

*Last Updated: 2026-08-16*

---

[← Back to AIPass](../../../README.md)
