[← Back to AIPass](../../../README.md)

# DevPulse

> Orchestration hub for AIPass — the user's primary AI collaborator. Plans, designs, debugs, dispatches work to the other branches, builds its own modules, and is the only branch with git write.

## Quick Start

```bash
cd src/aipass/devpulse && claude       # say "hi" — startup grounds the session
drone @devpulse                        # live self-map of modules
drone @devpulse <module> --help        # full reference for any module
```

## Invoke

```bash
drone @devpulse <module> <command>     # from anywhere in AIPass
```

## Architecture

```
src/aipass/devpulse/
├── apps/
│   ├── devpulse.py        # Entry point — auto-discovers modules
│   ├── modules/           # admin_grant, compass, feedback, release_notify, watchdog
│   └── handlers/          # Implementation per module, plus the json shim and the owner gate
├── devpulse_json/         # Module storage through @prax's json service
├── tests/                 # pytest suite
├── tools/                 # One-shot scanners and probes; statusline.sh is the tracked statusline
├── prototypes/            # Shape-exploration prototypes
├── artifacts/             # Birth certificate, reports
├── dropbox/               # Inbound files, archived plans
└── docs/                  # Deep references — read when something breaks
```

## Commands

All via `drone @devpulse <module> <command>`. Each module's `--help` is the full reference.

### Watchdog — dispatch reports (owner-only)

Every dispatch reports back when it finishes; a session signs in to receive it (Monitor tool, never `run_in_background`). Only your own completions wake you; a dead monitor is announced once as a `DEAD` line. Statusline green `watchdog:in` = signed in, any red = sign in again. How it works: [docs/watchdog.md](docs/watchdog.md).

| Command | What it does |
|---|---|
| `watchdog baseline` | Sign this session in |
| `watchdog status` | Signed-in session, outstanding and overdue dispatches |
| `watchdog agent @target [--timeout s]` | Stall-watch one long job |
| `watchdog timer <duration>` | Wake after a duration (named timers: `timer --help`) |
| `watchdog schedule <HH:MM \| +N> [command]` | Wait until a time, optionally run a command |
| `watchdog cancel <handle>` | Cancel a watch (`--all` for every one) |

### Feedback — cross-project owner channel (owner-only)

External project owners send here and devpulse replies. Dispatched projects/* citizens answer here too, not in the inbox.

| Command | What it does |
|---|---|
| `feedback` / `feedback inbox` | Summary / list |
| `feedback view <id>` / `feedback reply <id> "msg"` | Read / answer |
| `feedback send "subject" "body"` | Send to devpulse (any project owner) |
| `feedback clear <id>` | Remove (`--all` removes every read one) |

### Compass — rated decisions

What we decided, rated good / bad / impressive / interesting; @memory holds what happened. Gitignored SQLite/FTS5 store.

| Command | What it does |
|---|---|
| `compass query "question"` | Search decisions |
| `compass add "context" "decision" --rating R` | Store one (`--supersedes N` corrects an older entry) |
| `compass rate <id> <rating>` / `archive <id>` / `note <id> "text"` | Re-rate / archive / annotate |
| `compass stats` / `compass review` | Counts / surface one to review |

### Admin grant — the admin seat (owner-only mint)

A signed privilege block on devpulse's birth certificate that lets this seat dispatch any agent in any directory. Verified on every use; the key lives outside every repo; the user runs the ceremony.

| Command | What it does |
|---|---|
| `admin_grant status` / `admin_grant verify` | Lane state / full contract check |
| `admin_grant keygen [--force]` / `admin_grant mint` | Create the signing key / sign the block |

### Release notify — the merge train's last step

Mails every project manager the new version and posts one commons thread; one send per version.

| Command | What it does |
|---|---|
| `release-notify v<version>` | Send (`--dry-run` previews, `--force` resends) |

## Integration Points

### Depends On

drone (routing), ai_mail (dispatch, mail), flow (plans), seedgo (standards), prax (logging, json service, dashboard), memory (vectors, search), cli (rendering).

### Provides To

Git operations for the whole project, dispatch orchestration, watchdog reports, the feedback channel. Imported by @ai_mail (owner verification), @hooks (compass hits in prompts) and @commons (dashboard).

## Status

Live numbers come from their doors, not this file: `drone @seedgo audit aipass @devpulse` for standards, the pytest suite for tests, `CHANGELOG.md` at the repo root for history.

*Last Updated: 2026-09-15*

---

[← Back to AIPass](../../../README.md)
