# Drone

**Purpose:** Command router and symbolic addressing for AIPass. Resolves `@branch` names to paths at runtime via `AIPASS_REGISTRY.json`, routes commands to module entry points, and discovers available commands across the system.
**Module:** `aipass.drone`
**Created:** 2026-03-05

---

## Overview

### What I Do
- Resolve `@branch` symbolic names to absolute paths via `AIPASS_REGISTRY.json`
- Route commands to registered branches and internal modules
- Discover available commands across the system
- Provide `drone systems` introspection of all registered components

## Commands / Usage

Drone provides a CLI for terminal use and a Python API for programmatic access.

### CLI

```bash
drone systems                    # List all registered modules and branches
drone @seedgo verify             # Route "verify" to the seedgo module
drone @seedgo audit aipass       # Route "audit aipass" to seedgo
drone @module --help             # Show help for any module
drone --version                  # Show version
drone --help                     # Show usage information
```

### Python API

```python
from aipass.drone import resolve_branch, list_branches, route_command

# Resolve @name to absolute path
path = resolve_branch("@seedgo")

# List all registered branches
branches = list_branches()               # All branches
active = list_branches(status="active")  # Filter by status

# Route a command to a branch
result = route_command("@seedgo", "verify")
print(result.stdout)      # Command output
print(result.exit_code)   # 0 on success
```

### Registry Management

```python
from aipass.drone import set_registry_path, get_registry_path

# Use a custom registry location
set_registry_path("/path/to/AIPASS_REGISTRY.json")

# Or set via environment variable
# export AIPASS_REGISTRY_PATH=/path/to/registry.json
```

### Error Handling

```python
from aipass.drone import resolve_branch, BranchNotFoundError, CommandExecutionError

try:
    path = resolve_branch("@nonexistent")
except BranchNotFoundError:
    print("Branch not found in registry")

try:
    result = route_command("@seedgo", "audit", args=["aipass"], timeout=120)
except CommandExecutionError as e:
    print(f"Command failed: {e}")
```

---

## Architecture

```
drone/
├── cli.py                 # pip entry point (drone command)
├── drone_adapter.py       # Self-routing adapter for drone @drone
├── __init__.py            # Public API exports
├── apps/
│   ├── drone.py           # Core entry point
│   ├── modules/           # Business logic
│   │   ├── config.py      # Registry path resolution
│   │   ├── resolver.py    # Branch resolution (@name -> path)
│   │   ├── router.py      # Command routing via subprocess
│   │   ├── discovery.py   # Module and command discovery
│   │   └── module_registry.py  # Internal module routing
│   └── handlers/          # Implementation
│       ├── executor.py    # Safe subprocess execution
│       └── exceptions.py  # Exception hierarchy
├── docs/                  # Documentation
└── tests/
```

---

## Interactive Commands

By default, drone captures subprocess output (`capture_output=True`) with a 30s timeout. This is safe for AI-to-AI routing but strips Rich colors, buffers progress bars, and kills long-running commands.

Commands in the interactive tuple bypass capture and inherit the terminal directly — enabling live Rich output, colors, and no timeout. Only add commands here when Patrick needs full terminal experience.

**Per-command allowlist** (in `apps/drone.py`):

| Command      | Reason                                      |
|--------------|---------------------------------------------|
| `monitor`    | Prax real-time monitoring (live TUI)        |
| `snapshot`   | Backup snapshot (Rich progress bars)        |
| `versioned`  | Backup versioned (Rich progress, long-running) |

**Per-branch allowlist** — all commands from these branches get interactive mode:

| Branch | Reason                                      |
|--------|---------------------------------------------|
| `cli`  | User-facing CLI with Rich formatted output  |

To add: edit `interactive_commands` or `interactive_branches` in `_handle_target()` in `apps/drone.py`.

---

## Integration Points

### Depends On
- `AIPASS_REGISTRY.json` — Branch registry at repo root (read for resolution)
- Python stdlib (`pathlib`, `sys`, `subprocess`, `json`)

### Provides To
- All modules — command routing via `drone @target command`
- All modules — branch/module discovery via `drone systems`
- `aipass.seedgo` — routed via `drone @seedgo`
- `aipass.spawn` — routed via `drone @spawn`

---

**Last Updated:** 2026-03-17
