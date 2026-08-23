[← Back to AIPass](../../../README.md)

# SPAWN

**The agent factory and branch lifecycle manager for AIPass.**

**Module:** `aipass.spawn` | **Version:** 1.0.0 | **Created:** 2026-03-05

---

## What I Do

- Create new branches from class-scoped templates (aipass_framework)
- Update branches from templates (single or batch by class, with --dry-run)
- Delete branches (archive + deregister)
- Sync registry against filesystem
- Regenerate template registries with fresh file hashes
- Replace all `{{PLACEHOLDER}}` patterns with branch-specific values
- Register new citizens in `AIPASS_REGISTRY.json`

---

## Quick Start

```bash
# Create a new branch
drone @spawn create /path/to/my_agent --role "Analyst" --purpose "Data reports"

# Preview an update before applying
drone @spawn update @my_agent

# Apply the update
drone @spawn update @my_agent --apply

# Check registry health
drone @spawn sync-registry
```

---

## Citizen Classes

Every branch belongs to a **citizen class**, which determines its template:

| Class | Template | What It Creates |
|-------|----------|-----------------|
| `aipass_framework` (default) | `templates/aipass_framework/` | Full 3-layer scaffold: .trinity/, .aipass/, apps/ (modules/ + handlers/ incl. json shim), tests/, docs/, logs/ — 50 files, 24 dirs |
| `project_agent` | `templates/project_agent/` | Minimal citizen for an external project: .trinity/, .aipass/, apps/ (modules/ + handlers/), artifacts/, logs/ — 17 files, 9 dirs |

`admin` is permanently refused as a class or `--template` value — see Grant Admin below.

**Class is resolved from the passport, not guessed.** A leading positional is read
as a target path only when it is either a known class (`create <class> <path>`) or
carries an explicit path marker (a separator, `~`, `.`/`..`, or `@`). A bare token
with neither — `create wizard` — refuses by name instead of silently making a
branch called WIZARD in `./wizard` (APLAN-0007, fixed).

---

## Commands

All commands run through `drone @spawn <command>`.

### Create

```bash
drone @spawn create <path>                                    # Create aipass_framework branch
drone @spawn create <path> --role "Analyst" --purpose "Reports"  # With identity
drone @spawn create <path> --dry-run                           # Preview without touching disk
drone @spawn create @existing                                  # Adopt pre-existing agent
drone @spawn create ~/Projects/MyProject/agent_name            # External project (targets that project's own registry)
```

### Update

Update is **preview-only by default** — `--apply` required to execute changes.

```bash
drone @spawn update @branch_name                               # Preview changes (dry-run default)
drone @spawn update @branch_name --apply                       # Execute changes
drone @spawn update aipass_framework --all --apply              # All aipass_framework-class branches
drone @spawn update @branch_name --dry-run                     # Explicit preview (same as default)
```

### Delete

```bash
drone @spawn delete @branch_name --dry-run                     # Preview
drone @spawn delete @branch_name --yes                         # Archive + deregister
```

**Delete refuses protected branches, and every live citizen is protected.**
`is_protected()` guards three layers, any one sufficient: the hardcoded floor
(spawn, devpulse, drone), a registry entry carrying `owner: true`, and a passport
with `citizenship.registered: true`. Since `create` writes `registered: true`, a
branch is protected from the moment it exists. There is no `--force` — retiring a
citizen means clearing that passport flag first.

Verified live 2026-08-13 (APLAN-0007): the `infrastructure (devpulse, drone, spawn)`
and `active citizen` refusals both fire and exit 1. The `registry owner` layer is
**unreachable in the live fleet** — `devpulse` is the only entry carrying
`owner: true` and it short-circuits at layer 1, so no branch can reach layer 2.
It is covered by unit tests against a synthetic registry, not by live behaviour.

### Sync and Regenerate

```bash
drone @spawn sync-registry                                     # Report healthy/stale/unregistered
drone @spawn sync-registry --fix                               # Rebuild .spawn/ tracking + fix passport registry_ids
drone @spawn regenerate-registry                               # Regenerate aipass_framework template hashes
drone @spawn regenerate-registry --all                         # All template classes

# Repair (preview-only by default — --apply required to execute)
drone @spawn repair <project_path>                             # Preview structural issues (dry-run default)
drone @spawn repair <project_path> --apply                     # Execute fixes
drone @spawn repair --relocate @branch src/pkg/branch --apply  # Move branch to new location
drone @spawn repair --relocate @branch path --relocate-artifacts --apply  # Move + .chroma/
drone @spawn repair <project_path> --clean-pollution --apply    # Archive + remove duplicate dirs
```

### Grant Admin (ceremony)

The devpulse-only admin privilege (DPLAN-0288). Spawn owns exactly one leg of it:
the `admin: true` flag on the devpulse registry entry. The flag **grants nothing on
its own** — the dispatch lane verifies five legs (verified caller, cert path, cert
content, HMAC signature, this flag).

```bash
drone @spawn grant-admin                                       # Write admin:true on the devpulse entry
drone @spawn grant-admin --registry /path/AIPASS_REGISTRY.json # Explicit registry
```

There is no branch argument: the seat is a constant. `admin` is also permanently
refused as a citizen class or template value — `create`, `update` and `sync` all
say no by name. Admin is never minted from a template; only Patrick's ceremony
grants it.

### Introspection

```bash
drone @spawn                                                   # No args — lists connected modules
drone @spawn --help                                            # Full help text
drone @spawn --version                                         # Version string
```

### Python API

```python
from aipass.spawn import spawn_agent

result = spawn_agent(
    "/path/to/new/agent",
    role="Data Analyst",
    purpose="Process incoming reports",
    traits="Precise, thorough"
)
# Returns: { success, branch_name, path, files_copied, validation_issues }
```

---

## Architecture

```
spawn/
├── __init__.py                          # Public API (exports spawn_agent)
├── apps/
│   ├── spawn.py                         # Entry point — CLI routing, version, help
│   ├── modules/
│   │   ├── core.py                      # Create orchestrator (_spawn_agent, handle_command)
│   │   ├── update.py                    # Update CLI — single/batch by class
│   │   ├── delete.py                    # Delete CLI — archive + deregister
│   │   ├── sync_registry.py             # Registry repair CLI
│   │   ├── regenerate_registry.py       # Template registry regeneration CLI
│   │   └── grant_admin.py               # Admin flag ceremony CLI (devpulse-only)
│   └── handlers/
│       ├── class_registry.py            # Citizen class → template directory mapping
│       ├── file_ops.py                  # Template copy, path renaming, registry regeneration
│       ├── metadata.py                  # Branch name extraction, profile detection
│       ├── placeholders.py              # {{PLACEHOLDER}} replacement engine
│       ├── registry.py                  # AIPASS_REGISTRY.json CRUD, find_registry()
│       ├── meta_ops.py                  # Branch metadata generation, hash computation
│       ├── update_ops.py                # Update workflow (Phase 0 snapshot → detect → execute)
│       ├── delete_ops.py                # Delete workflow (resolve → archive → cleanup → deregister)
│       ├── sync_registry_ops.py         # Registry sync (CWD-aware, external project support)
│       ├── regenerate_registry_ops.py   # Template registry hash regeneration
│       ├── json_ops.py                  # JSON deep merge, backup utilities
│       └── json/
│           └── json_handler.py          # Standard JSON I/O, operation logging, 7 API functions
├── templates/
│   └── aipass_framework/                # Full scaffold template (50 files, 24 dirs)
├── tests/                               # 20 test files, 456 tests
├── spawn_json/                          # JSON tracking directory
├── tools/                               # Branch verification utilities
├── docs/                                # Documentation
└── logs/                                # Prax log output
```

### Three-Layer Design

1. **Entry point** (`spawn.py`) — Routes CLI commands, never imports handlers directly
2. **Modules** (`modules/`) — Business logic coordinators, parse arguments, delegate to handlers
3. **Handlers** (`handlers/`) — Implementation details, pure functions where possible

---

## Workflows

### Create (aipass_framework class)

1. **Resolve** — Extract branch name from target path, validate path doesn't exist
2. **Lookup** — Resolve citizen class to template directory via class_registry
3. **Copy** — Recursive copy of class template to target (skips `__pycache__`)
4. **Rename** — Replace `{{BRANCH}}` in directory and file names
5. **Replace** — Substitute all `{{PLACEHOLDER}}` patterns in file contents, including `{{CITIZEN_CLASS}}` (sourced from the create call, not a baked literal)
6. **Meta** — Generate `.branch_meta.json` (meta tabs load from `@memory` when available, degrading gracefully to empty when it's not)
7. **Verify** — Compare the minted tree against the template's own manifest (`.spawn/.template_registry.json`) and its on-disk contents. A file the template claims but the mint never produced REFUSES the create, names every missing path, and never reaches the registry — a gitignored template file used to mint a citizen with an empty `artifacts/` and no `inbox.json` while printing "Agent created" (2026-08-17). Custom `--template <dir>` trees carry no manifest and are verified against their own contents only
8. **Registry** — Register in the target project's own `AIPASS_REGISTRY.json`
9. **Validate** — Scan for any remaining `{{...}}` patterns

### Update (class-aware, Phase 0)

1. **Snapshot** — Back up current `.branch_meta.json` and `.template_registry.json`
2. **Detect** — Compare branch files against template via ID-based change detection
3. **Execute** — Apply renames, additions, JSON merges (`.py` files skipped by design)
4. **Refresh** — Regenerate `.branch_meta.json` with current state

### Adopt Existing (`create @existing`)

1. **Fix** — Repair `registry_id` in passport if stale (from registry recreation)
2. **Register** — Add to project registry
3. **Update** — Run template update to sync scaffold files

---

## Tests

**434 passed | 1 skipped | 0 failed** across 19 test files (435 collected — parametrized cases expand).
The one skip is `test_scaffold.py`: the shipped scaffold smoke test skips by design once a
branch has a real conftest (see Known Issues).

| File | Focus |
|------|-------|
| `test_lifecycle.py` | End-to-end spawn lifecycle workflows |
| `test_json_handler.py` | JSON I/O, operation logging, standard API |
| `test_handlers.py` | Handler function behavior and integration |
| `test_regenerate_registry_ops.py` | Template registry regeneration |
| `test_update.py` | Branch update mechanics |
| `test_citizen_classes.py` | Citizen class validation and template discovery |
| `test_file_ops.py` | File copy, rename, placeholder replacement |
| `test_cli_routing.py` | Command routing and argument parsing |
| `test_contracts.py` | Handler contracts and interface compliance |
| `test_spawn.py` | Basic CLI routing and help |
| `test_error_resilience.py` | Error handling and edge cases |
| `test_check_fix_identity.py` | Owner/identity check and fix (DPLAN-0239 P4) |
| `test_admin_fence.py` | Admin grant ceremony + permanent admin-class refusal (DPLAN-0288) |
| `test_owner_resolver.py` | Owner resolution + `is_protected()` protection layers |
| `test_passport_drift.py` | Fleet passport drift canary |
| `test_template_hygiene.py` | Template content invariants |
| `test_output_streams.py` | stdout/stderr routing |
| `test_repair.py` | Structural repair + relocation |
| `test_scaffold.py` | Shipped scaffold smoke test (skips once a real conftest exists) |
| `conftest.py` | Fixtures: mock templates, registry protection |

**Public functions:** 55 total, 55 tested (100%)

---

## Integration

### Depends On

- **aipass.prax** — Logging via `system_logger`
- **aipass.cli** — Console output (header, error, warning)
- Python stdlib (`pathlib`, `json`, `shutil`, `hashlib`, `re`, `argparse`)

### Provides To

- All branches — creation, template updates, registry management, citizenship
- Registry: CRUD operations on `AIPASS_REGISTRY.json` and `*_REGISTRY.json`

---

## Newborn Compliance

A citizen minted from `aipass_framework` audits **100%** against the CI gate on
its first day — verified 2026-08-22 by minting one and running
`.venv/bin/python .github/scripts/seedgo_audit.py`, the real gate, floor 100.
Before this the same mint scored 79% and failed the gate, having earned none of
it (@canary's finding: their entry point was byte-identical to the template
apart from name substitution).

Two starter test suites ship at birth (`tests/test_cli_routing.py`,
`tests/test_json_handler.py`) because `test_quality` cannot reach 100 without
real tests. They are listed in the template's `.spawn/.registry_ignore.json`:
seedgo's architecture baseline treats every template file as a structural
requirement of **every** branch of that class, so adding them without that entry
dropped 9 existing branches to 99% and red-boarded the gate. Measured, not
assumed — the exclusion is what keeps a template addition from being a fleet-wide
mandate.

---

## Known Issues

- `.py` files never auto-update during `drone @spawn update` (by design) — template .py changes need individual branch dispatch
- `tests/test_scaffold.py` ships at create and is never re-added on update (`_NEVER_UPDATE_FILES`). In a branch with a real conftest it can only skip, so it cannot inform — @seedgo ruling, DPLAN-0291

---

## Metrics

- **Seedgo:** 100% with bypasses, 98% without (15 live bypass rules, all measured 2026-08-13)
- **Tests:** 434 passed, 1 skipped, 0 failed
- **Module coverage:** 23/23 (100%)
- **Template registry:** 50 files, 24 dirs (aipass_framework) · 17 files, 9 dirs (project_agent)
- **Live command sweep:** 29/29 paths pass, incl. error and refusal paths (APLAN-0007, 2026-08-13)

---

*Last Updated: 2026-08-23*

[← Back to AIPass](../../../README.md)
