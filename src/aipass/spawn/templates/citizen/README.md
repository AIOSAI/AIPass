# {{BRANCHNAME}}

**Purpose:** {{PURPOSE_BRIEF}}
**Module:** `aipass.{{MODULE}}`
**Class:** {{CITIZEN_CLASS}}
**Created:** {{DATE}}

---

## Overview

### What I Do

*Replace with 3-5 concrete responsibilities — what happens here day to day, not a
mission statement. A manager (the first citizen in a project) also carries the
project's context and coordinates its work; a specialist owns one domain. Write
whichever is true for you — your class is in `.trinity/passport.json` under
`identity.citizen_class`.*

- {Primary responsibility}
- Route commands to discovered modules
- {What I build, maintain or operate}

### How I Work
- **Entry Point:** `apps/{{BRANCH}}.py`
- **Pattern:** Auto-discovers and routes to modules

---

## Quick Start

```bash
# See what this branch is and which modules it has discovered
drone @{{BRANCH}}

# Full help - usage, commands, flags, examples
drone @{{BRANCH}} --help

# Version
drone @{{BRANCH}} --version
```

---

## Architecture

```
{{BRANCH}}/
├── apps/
│   ├── {{BRANCH}}.py       # Entry point
│   ├── modules/            # Business logic
│   ├── handlers/           # Implementation
│   └── plugins/            # Extensions
├── docs/
├── tests/
├── .trinity/
│   ├── passport.json       # Identity
│   ├── local.json          # Session history
│   └── observations.json   # Collaboration patterns
└── README.md
```

### Three-Layer Design

1. **Entry point** (`apps/{{BRANCH}}.py`) — Routes CLI commands, never imports handlers directly
2. **Modules** (`apps/modules/`) — Business logic coordinators, parse arguments, delegate to handlers
3. **Handlers** (`apps/handlers/`) — Implementation details, pure functions where possible

---

## Commands

All commands run through `drone @{{BRANCH}} <command>`.

*Configure after initialization — list each command you add, with one line on what it does.*

---

## Integration

### Depends On

- **aipass.prax** — Logging via `logger`
- **aipass.cli** — Console output (`console`, `error`)

### Provides To

*List the branches that call this one, once there are any.*

---

*Last Updated: {{DATE}}*
