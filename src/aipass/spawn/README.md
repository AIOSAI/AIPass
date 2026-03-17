# SPAWN

**Purpose:** Branch creation, lifecycle management, and citizen class system. Creates new branches from class-scoped templates, manages updates, and grants citizenship.
**Module:** `aipass.spawn`
**Created:** 2026-03-05

---

## Overview

### What I Do
- Create new branches from class-scoped templates (builder, birthright)
- Grant birthright citizenship via the `passport` command
- Replace all `{{PLACEHOLDER}}` patterns with branch-specific values
- Update branches from templates (single or batch by class)
- Delete (archive + deregister) branches
- Sync registry and templates against filesystem
- Regenerate `.template_registry.json` with fresh file hashes
- Validate no unreplaced placeholders remain

### Citizen Classes

Branches are scoped by **citizen class**, which determines the template used:

| Class | Template | What it creates |
|-------|----------|-----------------|
| `builder` (default) | `templates/builder/` | Full 3-layer scaffold: apps/, modules/, handlers/ |
| `birthright` | `templates/birthright/` | Minimal citizenship: .trinity/, .aipass/, README.md |

### Usage

**Create a builder branch (full scaffold):**
```bash
drone @spawn create /path/to/new/agent
drone @spawn create builder /path/to/new/agent --role "Analyst" --purpose "Reports"
```

**Grant birthright citizenship (minimal identity):**
```bash
drone @spawn passport @new_branch --role "Observer" --purpose "Monitoring"
```

**Update branches from template:**
```bash
drone @spawn update @branch_name              # Single branch (uses its passport class)
drone @spawn update builder --all             # All builder-class branches
drone @spawn update birthright --all          # All birthright-class branches
drone @spawn update --dry-run @branch_name    # Preview changes
```

**Delete, sync:**
```bash
drone @spawn delete @branch_name              # Archive + deregister
drone @spawn sync-registry                    # Repair registry vs filesystem
drone @spawn sync-templates                   # Pull managed files from sources
```

**Python API:**
```python
from aipass.spawn import spawn_agent

result = spawn_agent(
    "/path/to/new/agent",
    role="Data Analyst",
    purpose="Process incoming reports",
    traits="Precise, thorough"
)
# result dict includes: success, branch_name, path, files_copied, validation_issues
```

---

## Architecture

```
spawn/
├── __init__.py              # Public API (exports spawn_agent)
├── apps/
│   ├── spawn.py             # Entry point (CLI)
│   ├── modules/
│   │   ├── core.py          # Create orchestrator — coordinates spawn steps
│   │   ├── passport.py      # Passport CLI — grant birthright citizenship
│   │   ├── update.py        # Update CLI — parses args, delegates to handler
│   │   ├── delete.py        # Delete CLI — parses args, delegates to handler
│   │   ├── sync_registry.py # Sync registry CLI — report and repair
│   │   └── sync_templates.py # Sync templates CLI — pull from sources
│   └── handlers/
│       ├── class_registry.py     # Citizen class registry — maps classes to templates
│       ├── passport_ops.py       # Passport grant implementation
│       ├── file_ops.py           # Template copy, path renaming
│       ├── metadata.py           # Branch name extraction, profile detection
│       ├── placeholders.py       # {{PLACEHOLDER}} replacement engine
│       ├── registry.py           # AIPASS_REGISTRY.json CRUD
│       ├── json_ops.py           # JSON read/write operations
│       ├── json/
│       │   └── json_handler.py   # JSON I/O abstraction
│       ├── meta_ops.py           # Branch metadata generation
│       ├── change_detection.py   # File diff detection
│       ├── reconcile.py          # Registry/filesystem reconciliation
│       ├── update_ops.py         # Update implementation (class-aware)
│       ├── delete_ops.py         # Delete implementation logic
│       ├── sync_registry_ops.py  # Registry sync implementation
│       └── sync_templates_ops.py # Template sync implementation
├── templates/
│   ├── builder/             # Full scaffold template (apps/, modules/, handlers/)
│   ├── birthright/          # Minimal template (.trinity/, .aipass/, README.md)
│   └── .archive/
│       └── agent_mock_branch/   # Reference implementation
├── tools/                   # Branch verification utilities
├── docs/                    # Documentation
├── spawn_json/              # JSON tracking directory
└── tests/                   # Test suite
```

---

## Spawn Workflow

### Create (builder class)
1. **Resolve** — Extract branch name from target path, validate path doesn't exist
2. **Lookup** — Resolve citizen class to template directory via class_registry
3. **Copy** — Recursive copy of class template to target (skips `__pycache__`, `.gitkeep`)
4. **Rename** — Replace `{{BRANCH}}` in directory and file names
5. **Replace** — Substitute all `{{PLACEHOLDER}}` patterns in file contents
6. **Registry** — Regenerate `.template_registry.json`, register in `AIPASS_REGISTRY.json`
7. **Validate** — Scan for any remaining `{{...}}` patterns

### Passport (birthright class)
1. **Check** — Verify .trinity/ doesn't already exist
2. **Copy** — Copy birthright template (.trinity/, .aipass/, README.md)
3. **Replace** — Substitute placeholders in copied files
4. **Register** — Add to AIPASS_REGISTRY.json

### Update (class-aware)
- Single branch: reads `citizen_class` from passport, uses matching template
- Batch: `builder --all` or `birthright --all` filters by class
- `--all` without a class is blocked (safety)

---

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and headers
- Python stdlib (`pathlib`, `json`, `shutil`, `hashlib`, `re`)

### Provides To
- All modules — branch creation, lifecycle management, citizenship
- Registry: Reads/writes `AIPASS_REGISTRY.json`

---

*Last Updated: 2026-03-17*
