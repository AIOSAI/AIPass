[← Back to AIPass](../../../README.md)

# DevPulse

> Orchestration hub for AIPass. The user's primary AI collaborator — designs, plans, debugs, coordinates all 11 branches, and builds its own modules.

DevPulse handles the day-to-day: working with the user to plan, design, troubleshoot, and adjust. It builds its own modules directly (watchdog, feedback, json_handler), manages all git operations for the project, dispatches heavy multi-file builds to sub-agents, and ventures into other branches to investigate, debug, and fix small bugs. The only branch with git write access.

## Start here

| You want to | Read |
|---|---|
| What's happening right now | [STATUS.local.md](STATUS.local.md) |
| Identity, memory, session history | [`.trinity/`](.trinity/) |
| Active plans | `drone @flow list open` |
| Branch list | `drone systems` |

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
│   │   ├── feedback.py          # Feedback mailbox command routing
│   │   └── watchdog.py          # Directed wake system command routing
│   ├── handlers/
│   │   ├── feedback/            # Inbox, compose, storage
│   │   ├── json/                # JSON operation logging (json_handler)
│   │   └── watchdog/            # Agent, timer, schedule, registry
│   └── plugins/                 # Plugin extension point
├── devpulse_json/               # JSON handler storage (config, data, logs per module)
├── tests/                       # 252 tests
├── artifacts/                   # Birth certificate, reports
├── dropbox/                     # Received files, archived plans, install audit
├── docs/                        # Transition notes
└── STATUS.local.md              # Current work beacon
```

## Commands

All commands via `drone @devpulse <command>`:

### Watchdog — directed wake system

| Command | What it does |
|---|---|
| `watchdog agent @target` | Monitor dispatched agent until it finishes |
| `watchdog timer <duration>` | Wake after duration (5m, 30s, 2h, 1h30m) |
| `watchdog timer start/stop <name>` | Named duration tracking |
| `watchdog schedule <HH:MM>` | Wait until a specific time |
| `watchdog status` | Show active watchdogs |
| `watchdog cancel <id>` | Cancel a running watchdog |
| `watchdog list` | List all watchdog entries |

### Feedback — personal cross-branch mailbox

| Command | What it does |
|---|---|
| `feedback` | Inbox summary |
| `feedback inbox` | List all messages |
| `feedback view <id>` | Read a message |
| `feedback reply <id> "msg"` | Reply to sender |
| `feedback send "subject" "body"` | Receive feedback from another agent |

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

*Last Updated: 2026-05-16*

---

[← Back to AIPass](../../../README.md)
