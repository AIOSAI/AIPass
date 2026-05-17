# AIPASS

Concierge and librarian for AIPass. Greets new users, walks them through setup, answers how-things-work questions, hands off to their chosen CLI.

## Invoke

```
drone @aipass <command>
```

## Architecture

```
aipass/
├── apps/
│   ├── aipass.py                          # Entry point — subcommand dispatch
│   ├── modules/
│   │   ├── doctor.py                      # System health aggregation
│   │   ├── doctor_fix.py                  # Remediation report (--fix, --json)
│   │   ├── doctor_wire.py                 # Auto-wire prompt helpers
│   │   ├── handoff.py                     # CLI handoff (placeholder)
│   │   ├── help_chat.py                   # README-backed Q&A
│   │   ├── init_flow.py                   # 12-stage guided setup
│   │   └── profile.py                     # User profile read/write
│   ├── handlers/
│   │   ├── handoff_platform/              # Platform-specific handoff detection
│   │   ├── init/                          # bootstrap.py, scaffold_content.py
│   │   ├── json/                          # JSON read/write utilities
│   │   ├── ping_sweep/                    # Branch reachability verification
│   │   ├── readme_map/                    # Live file reads + branch routing
│   │   ├── structure_scan/                # Agent placement + pollution detection
│   │   ├── system_detect/                 # OS, shell, Python, RAM, CPU
│   │   └── ui/                            # Progress bars, menus, banners
│   └── plugins/
├── tests/                                 # 412 passing
├── .trinity/                              # Identity + session history + observations
└── README.md
```

## Commands

| Command | Description |
|---------|-------------|
| `aipass` | Help banner |
| `aipass help [Q]` | README-backed Q&A with branch routing |
| `aipass doctor` | System health — structure, registry, hooks, pytest |
| `aipass doctor --fix` | Remediation report with `drone @spawn repair` commands |
| `aipass doctor --json` | JSON output for structure scan results |
| `aipass init` | 12-stage guided setup (resumable) |
| `aipass profile` | Show/edit user profile |
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

412 passing — `pytest src/aipass/aipass/tests/`

## Known Issues

- `aipass.py` line 23: `from aipass.prax import logger` fails outside package context (ModuleNotFoundError). Works via drone routing only.

## Last Updated

Last Updated: 2026-05-16
