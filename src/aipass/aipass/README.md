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
aipass init                         # Guided setup (10 stages, resumable)
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
│   │   ├── handoff.py                     # CLI handoff — tmux (Linux/Mac) / wt.exe (Windows) session launch
│   │   ├── help_chat.py                   # README-backed Q&A (reads via readme_map handler)
│   │   ├── init_flow.py                   # 10-stage guided setup
│   │   ├── install.py                     # aipass install — one-command bootstrap (clone + setup + init)
│   │   ├── new_project.py                 # aipass new — create projects inside the installation
│   │   ├── adopt.py                       # aipass adopt — bring an existing projects/ dir into AIPass
│   │   ├── profile.py                     # User profile read/write
│   │   ├── read.py                        # aipass read — render a branch README, live-read
│   │   ├── trust.py                       # Trust registry — aipass trust / aipass revoke
│   │   └── feedback.py                    # Feedback pulse toggle — aipass feedback on/off
│   ├── handlers/
│   │   ├── cross_os/                      # Cross-OS pre-flight: gap_registry, preflight, run_record
│   │   ├── handoff_platform/              # Platform-specific handoff detection
│   │   ├── init/                          # bootstrap.py, scaffold_content.py, git_auth.py
│   │   ├── new_project/                   # Project creation logic (registry, template, scaffold, git init)
│   │   │   └── adopt.py                   # Project adoption logic (additive scaffold onto an existing dir)
│   │   ├── json/                          # JSON read/write utilities
│   │   ├── ping_sweep/                    # Branch reachability verification
│   │   ├── provider_reconcile.py          # Stale deny-rule detection + fix
│   │   ├── readme_map/                    # Live file reads + branch routing
│   │   ├── structure_scan/                # Agent placement + pollution detection
│   │   ├── system_detect/                 # OS, shell, Python, RAM, CPU
│   │   ├── telegram_readiness.py          # Telegram bot-host readiness checks (doctor)
│   │   └── ui/                            # Progress bars, menus, banners
│   └── plugins/
├── tests/                                 # 981 passing
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
| `aipass doctor --fix` | Remediation report with `drone @spawn repair` commands |
| `aipass doctor --json` | JSON output for structure scan results |
| `aipass doctor --cross-os` | Cross-OS pre-flight — OS-gap cross-ref + routing/versions/hookstatus |
| `aipass doctor --cross-os --e2e` | ...also runs the real e2e wiring suite (heavy, opt-in) |
| `aipass doctor --cross-os --record [PATH]` | Write a machine-filled Run Record for the human acceptance pass |
| `aipass init` | 10-stage guided setup (resumable) |
| `aipass init update [target]` | Refresh managed scaffold + provision owner-tier git auth |
| `aipass init update --dry-run` | Preview the git-auth repairs only — writes nothing |
| `aipass install` | One-command bootstrap — clone + setup.sh + hooks, then hand off to init |
| `aipass profile` | Show/edit user profile |
| `aipass read [branch]` | View a branch README rendered in the terminal (bare: module info + branch list) |
| `aipass handoff` | Show CLI-handoff status |
| `aipass handoff launch [--cli claude\|codex]` | Launch chosen CLI in a new session (tmux / wt.exe) |
| `aipass <free text>` | Multi-word unknown input falls through to `aipass help` |
| `aipass new <name>` | Create a project in projects/ — own git repo, AIPass scaffold, resident agent |
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

## Integration Points

### Depends On

- `@drone` — routing, command dispatch
- `@seedgo` — standards audit
- `@spawn` — first agent creation + structural repair
- `@flow` — plan lifecycle (open/close)
- `@ai_mail` — test emails
- `@prax` — health signals, logging
- `pytest` — test execution

### Provides To

Humans only. Nothing in AIPass depends on this branch.

## Tests

981 passing — `pytest src/aipass/aipass/tests/`

## Known Issues

- Running the file directly (`python apps/aipass.py`) fails on package imports (ModuleNotFoundError) — use the installed `aipass` entry point, which works from any directory.

## Last Updated

Last Updated: 2026-08-13
