[← Back to AIPass](../../../README.md)

# DEVPULSE

> Orchestration hub for AIPass — the user's primary AI collaborator. Plans, designs, debugs, dispatches work to the other branches, builds its own modules, and is the only branch with git write.

## Quick Start

```bash
cd src/aipass/devpulse && claude       # say "hi" — startup grounds the session
drone @devpulse                        # live self-map of modules
drone @devpulse <module> --help        # full reference for any module
```

## What It Does

Five modules, each a door another seat or the owner walks through.

**Watchdog** carries dispatch reports back to the session that sent the work. A one-shot wire, armed in the background, sits silent and exits on the first completion of a dispatch this seat sent; that exit is the one wake. Nothing happening means nothing happens. How it works: [docs/watchdog.md](docs/watchdog.md).

**Feedback** is the cross-project channel. External project owners send here and devpulse replies; a dispatched `projects/*` citizen answers here too, never in the inbox.

**Compass** is the rated decision store: what we decided and how it turned out, rated good, bad, impressive or interesting. @memory holds what happened; compass holds what was chosen. A gitignored SQLite/FTS5 store, queried at forks.

**Admin grant** is the admin seat: a signed privilege block on this branch's birth certificate that lets it dispatch any agent in any directory. Verified on every use, the key outside every repo, the ceremony run by the owner.

**Release notify** is the merge train's last step: one mail to every project manager and one commons thread per version.

Beyond the modules, this branch is the git gatekeeper for the whole repository: every commit, push, PR and merge goes through `drone @git` from this seat, and a dirty tree anywhere is another citizen's live work until the owner and this seat decide otherwise.

## Live Inventory

The list of modules, verbs and flags is generated from the code that runs them, so it is not written down here and cannot go stale on this page:

- `drone @devpulse` — the self-map: the discovered modules and what this branch is.
- `drone @devpulse --help` — the full command surface. Each module answers for its own verbs: `drone @devpulse watchdog --help`, `drone @devpulse compass --help`.

## How To Reach Me

- Mail: `drone @ai_mail email @devpulse "Subject" "Body"`. This is a manager seat: never dispatched, always awake when the owner is, so plain email is read live.
- A project owner outside the fleet: `drone @devpulse feedback send "subject" "body"`, answered in the same channel.
- Architecture questions, rulings, anything that needs the owner: say so in the mail and it is put in front of him in his words.

## Commands

All via `drone @devpulse <module> <command>`. Each module's `--help` is the full reference.

### Watchdog — dispatch reports (owner-only)

| Command | What it does |
|---|---|
| `watchdog baseline --once` | Arm the one-shot wire (background); exits on the first completion, carrying the report |
| `watchdog status` | Wire state, outstanding and overdue dispatches |
| `watchdog agent @target [--timeout s]` | Stall-watch one long job |
| `watchdog timer <duration>` | Wake after a duration (named timers: `timer --help`) |
| `watchdog schedule <HH:MM \| +N> [command]` | Wait until a time, optionally run a command |
| `watchdog cancel <handle>` | Cancel a watch (`--all` for every one) |

### Feedback — cross-project owner channel (owner-only)

| Command | What it does |
|---|---|
| `feedback` / `feedback inbox` | Summary / list |
| `feedback view <id>` / `feedback reply <id> "msg"` | Read / answer |
| `feedback send "subject" "body"` | Send to devpulse (any project owner) |
| `feedback clear <id>` | Remove (`--all` removes every read one) |

### Compass — rated decisions

| Command | What it does |
|---|---|
| `compass query "question"` | Search decisions |
| `compass add "context" "decision" --rating R` | Store one (`--supersedes N` corrects an older entry) |
| `compass rate <id> <rating>` / `archive <id>` / `note <id> "text"` | Re-rate / archive / annotate |
| `compass stats` / `compass review` | Counts / surface one to review |

### Admin grant — the admin seat (owner-only mint)

| Command | What it does |
|---|---|
| `admin_grant status` / `admin_grant verify` | Lane state / full contract check |
| `admin_grant keygen [--force]` / `admin_grant mint` | Create the signing key / sign the block |

### Release notify — the merge train's last step

| Command | What it does |
|---|---|
| `release-notify v<version>` | Send (`--dry-run` previews, `--force` resends) |

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
└── docs/                  # Depth — one page per module
```

Live numbers come from their doors, not this file: `drone @seedgo audit aipass @devpulse` for standards, the pytest suite for tests, `CHANGELOG.md` at the repo root for history.

## Documentation

Depth lives in [docs/](docs/), in the shape `drone @seedgo standards_query aipass_standards docs_page` shows:

| Doc | What it covers |
|---|---|
| [watchdog.md](docs/watchdog.md) | The one-shot wire: how it arms, what wakes it, why never the Monitor tool |

## Integration Points

### Depends On

drone (routing), ai_mail (dispatch, mail), flow (plans), seedgo (standards), prax (logging, json service, dashboard), memory (vectors, search), cli (rendering).

### Provides To

Git operations for the whole project, dispatch orchestration, watchdog reports, the feedback channel. Imported by @ai_mail (owner verification), @hooks (compass hits in prompts) and @commons (dashboard).

---

**Last Updated:** 2026-09-19

---

[← Back to AIPass](../../../README.md)
