# AIPASS

The friendly front door for AIPass. Walks new users through setup, runs system diagnostics, answers documentation questions, and creates projects inside the AIPass environment.

## Quick Start

```bash
aipass                              # Show available commands
aipass doctor                       # Check system health
aipass help what does drone do      # Search branch documentation
aipass what does drone do           # Same — free text falls through to help
aipass read drone                   # Full branch README, rendered in the terminal
aipass new myapp --template python  # Create a new project
aipass adopt myapp --dry-run        # Preview adopting an existing projects/ dir
aipass init run                     # Guided setup (10 stages, resumable)
```

## Invoke

```
aipass <command> [options]
aipass <command> --help
```

## Architecture

```
aipass/
├── apps/
│   ├── aipass.py                          # Entry point — subcommand dispatch
│   ├── modules/
│   │   ├── doctor.py                      # System health aggregation + cross-OS pre-flight (--cross-os)
│   │   ├── _doctor_fix.py                 # Remediation report (--fix, --json) [internal]
│   │   ├── _doctor_wire.py                # Auto-wire provider settings + stale-deny re-export [internal]
│   │   ├── handoff.py                     # CLI handoff — thin coordinator, delegates to handoff_platform/
│   │   ├── help_chat.py                   # README-backed Q&A (reads via readme_map handler)
│   │   ├── init_flow.py                   # 10-stage guided setup + update / scaffold / agent forms
│   │   ├── install.py                     # aipass install — one-command bootstrap (clone + setup + chat)
│   │   ├── new_project.py                 # aipass new — create projects inside the installation
│   │   ├── adopt.py                       # aipass adopt — bring an existing projects/ dir into AIPass
│   │   ├── profile.py                     # User profile read/write
│   │   ├── read.py                        # aipass read — render a branch README, live-read
│   │   ├── trust.py                       # Trust registry — aipass trust / aipass revoke
│   │   └── feedback.py                    # Feedback pulse toggle — aipass feedback on/off
│   ├── handlers/
│   │   ├── cross_os/                      # Cross-OS pre-flight: gap_registry, preflight, run_record
│   │   ├── handoff_platform/              # OS-dispatched CLI session launch — tmux, wt.exe, inline
│   │   ├── init/                          # bootstrap.py, git_auth.py (re-exports shared/scaffold_content.py)
│   │   ├── new_project/                   # Project creation logic (registry, template, scaffold, repo init)
│   │   │   └── adopt.py                   # Project adoption logic (additive scaffold onto an existing dir)
│   │   ├── json/                          # Branch-local shim — delegates to shared/json_handler.py
│   │   ├── help_flag.py                   # wants_help() — --help detection in any argv position
│   │   ├── ping_sweep/                    # Branch reachability verification
│   │   ├── provider_reconcile.py          # Stale deny-rule detection + fix
│   │   ├── provider_wire.py               # Provider settings wiring (used by doctor --fix)
│   │   ├── readme_map/                    # Live file reads + branch routing
│   │   ├── sandbox_check/                 # Sandbox / containment detection
│   │   ├── structure_scan/                # Agent placement + pollution detection
│   │   ├── system_detect/                 # OS, shell, Python, RAM, CPU
│   │   ├── telegram_readiness.py          # Telegram bot-host readiness checks (doctor)
│   │   └── ui/                            # Rich progress bars, spinners, check glyphs, step headers
│   ├── integrations/                      # Placeholder — no code yet
│   └── plugins/                           # Placeholder — no code yet
├── shared/                                # Cross-handler code — json_handler, json_ops,
│                                          #   project_home, registry_discovery, scaffold_content
├── tests/                                 # 1061 passing
├── requirements.project.txt               # Project-specific Python dependencies
├── .trinity/                              # Identity + session history + observations
└── README.md
```

## Commands

| Command | Description |
|---------|-------------|
| `aipass` | Show available commands |
| `aipass help [Q]` | README-backed Q&A with branch routing |
| `aipass doctor` | System health — structure, registry, hooks, pytest |
| `aipass doctor --verbose` | Same, with per-check detail |
| `aipass doctor --fix` | Remediation report with `drone @spawn repair` commands |
| `aipass doctor --fix --json` | JSON remediation report — `--json` alone falls through to the normal report |
| `aipass doctor --cross-os` | Cross-OS pre-flight — OS-gap cross-ref + routing/versions/hookstatus |
| `aipass doctor --cross-os --e2e` | ...also runs the real e2e wiring suite (heavy, opt-in) |
| `aipass doctor --cross-os --record [PATH]` | Write a machine-filled Run Record for the human acceptance pass |
| `aipass init` | Print init usage — bare `init` does NOT start the guided setup |
| `aipass init run` | 10-stage guided setup (resumable) |
| `aipass init run --non-interactive` | CI/headless run |
| `aipass init run --name/--cli/--style/--template <v>` | Pre-fill a stage answer |
| `aipass init run --dry-run` | Walk all stages, write nothing |
| `aipass init --list` | List available project templates |
| `aipass init <path> [name]` | Scaffold AIPass files into an existing path (absent from `init --help`) |
| `aipass init agent <name>` | Create an agent via `drone @spawn` (absent from `init --help`) |
| `aipass init update [target]` | Refresh managed scaffold + provision owner-tier repo auth |
| `aipass init update --dry-run` | Preview the auth repairs only — writes nothing |
| `aipass install` | One-command bootstrap — clone + setup.sh + hooks, then a concierge welcome chat |
| `aipass install --path DIR` / `--here` | Choose the install home |
| `aipass install --non-interactive` / `--no-chat` / `--chat-only` | Headless, install-only, or chat-only |
| `aipass install --no-symlink` / `--force-symlink` | Control the global CLI symlinks |
| `aipass install --dry-run` | Walk the steps, no side effects |
| `aipass profile` | Show user profile |
| `aipass profile set <field> <value>` | Update a profile field |
| `aipass profile clear [--yes]` | Reset the profile |
| `aipass read [branch]` | View a branch README rendered in the terminal (bare: module info + branch list) |
| `aipass handoff` | Print handoff usage — bare does NOT show status, use `--info` |
| `aipass handoff --info` | Show stored CLI + platform status |
| `aipass handoff launch [--cli claude\|codex] [--cwd PATH] [--flag VARIANT]` | Launch chosen CLI in a new session (tmux / wt.exe) |
| `aipass <free text>` | Multi-word unknown input falls through to `aipass help` |
| `aipass new <name>` | Create a project in projects/ — own repo (`main` + `dev`, left on `dev`), AIPass scaffold, resident manager-class agent |
| `aipass new <name> --template python` | Create with Python template (pyproject + src/) |
| `aipass new <name> --no-agent` | Create without resident agent |
| `aipass adopt <name>` | Turn an existing `projects/<name>` directory into a full project — additive scaffold only |
| `aipass adopt <name> --no-agent` | Adopt without a resident agent |
| `aipass adopt <name> --dry-run` | Preview what adoption would do, writes nothing |
| `aipass trust [path]` | Show enrolled projects or enroll a project in the trust registry |
| `aipass revoke <path>` | Remove a project from the trust registry |
| `aipass trust prune` | Drop registry entries whose project path no longer exists |
| `aipass feedback on/off` | Toggle the feedback reminder pulse (delegates to @hooks) |
| `aipass --version` | Version |

## Admin setup

Admin is one privilege held by exactly one citizen — `@devpulse` — letting it
dispatch any agent, manager-class citizens included. It is **per-machine**,
**optional**, and **single-seat** (bolted to `devpulse`; there is no transfer
ceremony). A fresh install starts with the lane **dark**, which is a correct,
fail-closed state: admin actions simply refuse.

**Full walkthrough: [`docs/admin_setup.md`](docs/admin_setup.md)** — the five
legs, the threat model, and where each piece of the code lives.

Security model in short: passports are public profiles and grant nothing; the
security layer is the gitignored, machine-unique birth certificate, whose
`privileges` block is signed with a key at `~/.aipass/admin_grant.key` that
never enters a repo — so a clone never carries a grant.

The ceremony, in order — `keygen` → `mint` → registry flag → `verify`:

```bash
drone @devpulse admin_grant status    # lane state
drone @devpulse admin_grant keygen    # machine signing key (owner)
drone @devpulse admin_grant mint      # sign the privilege block (owner)
drone @spawn grant-admin              # admin: true on the registry entry
drone @devpulse admin_grant verify    # full 5-leg contract check
```

`keygen --force` regenerates the key and invalidates every existing signature —
that is the revocation story; there is no `revoke` verb.

`aipass doctor` reports an `admin lane` row (`lit` / `dark` / `partial`). It
observes presence only and never errors; `drone @devpulse admin_grant verify` is
the authoritative check.

## Integration Points

### Depends On

- `@drone` — routing; every outbound command in this branch is a `drone` subprocess call
- `@spawn` — agent creation (`init run`, `init agent`, `new`) + registry sync during `install`
- `@hooks` — `feedback` delegates to it outright; `doctor` and the cross-OS pre-flight check `drone @hooks status`
- `@ai_mail` — test-convention ping emails (`ping_sweep`)
- `@prax` — logging, imported by nearly every module and handler
- `@trigger` — soft dependency: `trigger.fire()` on write-failure cleanup, wrapped in try/except so it degrades
- `pytest` — test execution (`doctor` shells out to collect the suite)

`@seedgo` and `@flow` are part of this branch's working practice — audits before "done", plans for builds — but no code path here calls either. They appear in `ping_sweep`'s reachability list only.

### Provides To

Humans only. No `.py` source elsewhere in AIPass imports this branch.

## Tests

1061 passing — `pytest src/aipass/aipass/tests/`

## Known Issues

- Running the file directly (`python apps/aipass.py`) fails on package imports (ModuleNotFoundError) — use the installed `aipass` entry point, which works from any directory.
- `aipass --help` omits `feedback` and `handoff`, and its example line still claims `aipass init` starts the guided setup. Bare `aipass` lists `feedback` but also omits `handoff`.
- `aipass init --help` documents neither `aipass init <path> [name]` nor `aipass init agent <name>`, and omits the `--style` flag that `init run` accepts.
- `aipass handoff --help` claims bare `aipass handoff` shows status; it prints the usage block instead.
- `aipass install --no-chat` returns before the doctor pre-flight runs, so the pre-flight is skipped along with the chat.

## Last Updated

Last Updated: 2026-08-25
