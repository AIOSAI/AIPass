# {{BRANCHNAME}}

**Resident project agent and manager.**

**Module:** `{{MODULE}}` | **Class:** manager | **Created:** {{DATE}}

---

## What I Do

- Manage this project as its resident agent (citizen_class: manager)
- Route commands to discovered modules
- Coordinate project work and maintain project context

---

## Quick Start

```bash
# Confirm the agent is alive
drone @{{BRANCH}} hello

# Show connected modules
drone @{{BRANCH}}

# Full help text
drone @{{BRANCH}} --help
```

---

## Commands

All commands run through `drone @{{BRANCH}} <command>`.

```bash
drone @{{BRANCH}}                # Show connected modules
drone @{{BRANCH}} hello          # Confirm the agent is alive
drone @{{BRANCH}} --help         # Full help text
drone @{{BRANCH}} --version      # Version string
```

---

## Architecture

```
apps/
├── {{BRANCH}}.py              # Entry point — CLI routing, introspection, help
├── modules/                   # Business logic (auto-discovered)
└── handlers/                  # Implementation details
```

### Three-Layer Design

1. **Entry point** (`{{BRANCH}}.py`) — Routes CLI commands, never imports handlers directly
2. **Modules** (`modules/`) — Business logic coordinators, parse arguments, delegate to handlers
3. **Handlers** (`handlers/`) — Implementation details, pure functions where possible

---

## Integration

### Depends On

- **aipass.prax** — Logging via `system_logger`
- **aipass.cli** — Console output (header, error, warning)

---

*Created by `aipass new` via spawn project_agent template.*

---

*Last Updated: {{DATE}}*
