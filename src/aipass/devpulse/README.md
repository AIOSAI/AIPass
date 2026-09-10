[← Back to AIPass](../../../README.md)

# DevPulse

> Orchestration hub for AIPass. The user's primary AI collaborator — designs, plans, debugs, coordinates the other branches, and builds its own modules.

DevPulse handles the day-to-day: working with the user to plan, design, troubleshoot, and adjust. It builds its own modules directly (watchdog, feedback, compass, admin_grant), manages all git operations for the project, dispatches heavy multi-file builds to sub-agents, and ventures into other branches to investigate, debug, and fix small bugs. The only branch with git write access.

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
│   │   ├── release_notify.py    # Release mail fan-out to project managers
│   │   └── watchdog.py          # Always-on dispatch reporting + directed wakes
│   ├── handlers/
│   │   ├── compass/             # Decision store (SQLite/FTS5), rating, query, review
│   │   ├── feedback/            # Inbox, compose, storage
│   │   ├── release_notify/      # Manager discovery, mail body, delivery + per-version stamp
│   │   ├── json/                # json_handler.py — the fleet's ONE json shim (binds @prax's service; sha256 3456b766…, 1724 bytes; DPLAN-0325)
│   │   ├── owner/               # Owner gate + admin grant (keygen, mint, 5-leg verify)
│   │   └── watchdog/            # Agent, timer, schedule, registry, wire, presenter
│   ├── integrations/            # Extension point (README only)
│   └── plugins/                 # Plugin extension point (README + empty __init__.py)
├── devpulse_json/               # Storage written by @prax's json service through the shim (config/data/log trio per module, 64 files)
├── tests/                       # 466 test functions across 22 files; pytest expands to 571 cases (569 passed, 2 skipped, 46 s — 2026-09-07)
├── tools/                       # One-shot scanners & probes (31 scripts) + reports/
├── prototypes/                  # Shape-exploration prototypes
├── templates/                   # Local templates
├── artifacts/                   # Birth certificate, reports
├── dropbox/                     # Received files, archived plans, campaign logs
├── docs/                        # README stub only
└── DASHBOARD.local.json         # Live state (refreshed by @prax: drone @prax dashboard refresh @devpulse)
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

**Dead-monitor backstop (FPLAN-0499, DPLAN-0314 "outcome M"):** a dispatch whose
monitor died — host reboot, OOM, kill — can never report, so the receiver announces
it: at sign-in and every 5 minutes it reads `@ai_mail`'s dispatch register once
(no agent is polled, no process is armed) and pushes one line per dispatch of yours
whose monitor is gone: `monitor_alive` false (ai_mail records the monitor's pid and
checks `/proc` at read time — a death is announced within one cadence, wording
"its monitor (pid N) is gone before the hard timeout"), or past `expected_by`
(ai_mail's hard timeout — a live monitor cannot overrun it). `monitor_alive` is
tri-state; `None` (a row that never learned a pid) keeps the overdue rule only:

```
DEAD @prax [70da6e9c] dispatched 09-07 12:00 "..." — no completion by 09-07 14:00, the hard timeout: its monitor died (reboot, OOM, kill). Re-dispatch in continue mode.
```

Each death is announced once ever (cursor `devpulse_json/wire_dead_cursor.json`), so
a re-sign-in never repeats one. `drone @devpulse watchdog status` shows the same
rows on demand as "Dispatches overdue".

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
| `admin_grant keygen --force` | Regenerate the key (invalidates the existing signature) |
| `admin_grant mint` | Add + sign the admin privilege block (owner-only) |

### Release notify — the merge train's last step (DPLAN-0335 leg 1)

When a release tag goes out, every project manager on this machine should hear about it
on their next wake. `release-notify` enumerates them (passports with `citizen_class: manager`
under an active root in `AIPASS_ROOTS.json`, plus every project under `projects/`; the AIPass
source repo is skipped — it has no scaffold of its own to update), mails each one the version,
the release URL, the top of the CHANGELOG and the preview-first ritual (doctor → `init update
--dry-run` → ask Patrick or devpulse → apply → doctor), and posts one `general` thread. One
send per version: the stamp is `.devpulse/release_notify.json`.

| Command | What it does |
|---|---|
| `release-notify v<version>` | Mail every manager + post one commons thread, then stamp the version |
| `release-notify v<version> --dry-run` | Print recipients, what was skipped and why, and the whole body — sends nothing, writes nothing |
| `release-notify v<version> --force` | Send again for a version already stamped |

A failed send is named and the fan-out continues; the exit code is non-zero if any recipient
or the commons post failed.

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
| seedgo | Standards audits, checkers (47 scored categories: 46 checkers + diagnostics) |
| prax | Logger in all four modules, the json service behind the shim, monitoring, dashboard refresh |
| memory | ChromaDB vectors, archival, search |
| cli | `console` / `error` rendering in every module (`from aipass.cli.apps.modules import ...`) |

### Provides To

All branches via dispatch orchestration. Watchdog reporting for every dispatched agent. Feedback channel for cross-branch communication. Git operations (commit, PR, merge) for the entire project.

Three production files elsewhere in the fleet import this branch (measured 2026-09-06): `ai_mail/apps/handlers/users/verified_caller.py` (owner verification), `commons/apps/handlers/dashboard/dashboard_writer.py`, and `hooks/apps/handlers/prompt/compass_recall.py` (compass hits injected into prompts).

## Status & Known Issues

Verified 2026-09-06 (README truth pass round 2, FPLAN-0490 — every command table above checked against tonight's `--help`, the suite run, every count measured, the four 08-25 issues re-tested live); counts re-measured 2026-09-07 after the DPLAN-0323 seal.

| Signal | Measured 2026-09-07 |
|---|---|
| Tests | 466 `def test_` across 22 files; 571 cases, 569 passed / 2 skipped in 39 s (`.venv` python, from the repo root in the CI shape: `python -m pytest src/aipass/devpulse -c pyproject.toml --rootdir=.`). 2026-09-07 FPLAN-0508 (no stragglers): v5 `pytest_quality` reads 100 on assertion_shape, no_oracle and unentered_assert — eleven either/or assertions now pin the one string the code prints, six isinstance-only units pin values (three of them archived to `tests/.archive/` as subsumed by their neighbours), two vacuous loops assert before iterating, six oracle-less inbox/wire tests read what they print. Earlier: `tests/test_json_handler.py` archived on 09-06 (its six shim pins run for all 18 branches in seedgo's contract suite). |
| Seedgo | `drone @seedgo audit aipass @devpulse` — Overall 100, every scored category 100 across the **46** consulted entries (v4 `test_quality` retired from the pack 2026-09-07), no type errors; 10 bypass rules in `.seedgo/bypass.json` |
| json handler | `apps/handlers/json/json_handler.py` is the fleet shim: sha256 `3456b766…`, binds `aipass.prax.json_handler`, adds nothing |
| Version | `drone @devpulse --version` prints `devpulse 1.0.2` — one `VERSION` constant in `apps/devpulse.py`, kept in step with the file header |

**Resolved since 08-25** (re-tested tonight, not carried forward on trust):

- ~~`watchdog cancel` always prints KILLED~~ — `killed or True` is gone from `registry.py` (commit `32349742`); cancel now reports `was_alive` / `reason` per handle.
- ~~Refusals that exit 0~~ — `compass archive 999999`, `compass rate 999999 good` and `feedback view zzzz` all exit 2; every module calls `mark_command_failed()`. The last survivor, `watchdog cancel <unknown>`, printed FAILED and exited 0 until 2026-09-06 — it now goes through `error()` and exits 2.
- ~~`--version` hardcoded~~ — printed `devpulse 1.0.0` against a `1.0.1` header; one `VERSION` constant now (1.0.2), fixed 2026-09-06.

**Resolved 2026-09-07** (Patrick's blanket ruling on the held items, FPLAN-0492):

- ~~statusline.sh untracked~~ — a byte-identical copy is tracked at `tools/statusline.sh` (6140 bytes); install on another machine is `cp tools/statusline.sh ~/.claude/statusline.sh` (the statusline path is provider config, so the copy is the versioned source and the home file is the deployment).
- ~~Foreground-wire gap, half cured~~ — the statusline's green now also requires the registered wire's `metadata.wrapper == "monitor"`; a foreground or background wire with no listener paints `watchdog:OUT`. Verified on this session's monitor wire: still `watchdog:in`.
- **Unknown command or flag refused silently** — `drone @devpulse <bogus>` exited 1 with empty stdout and stderr (the 09-07 fleet sweep's REFUSES-SILENT). `route_command` now names the token, offers a did-you-mean, and lists the known commands.

**Open:** nothing known as of 2026-09-07. The one standing caveat: a wire armed *before* the 09-07 statusline change carries no `wrapper` field and paints `watchdog:OUT` until re-armed through the Monitor tool.

*Last Updated: 2026-09-07*

---

[← Back to AIPass](../../../README.md)
