[← Back to AIPass](../../../README.md)

# Drone

**Purpose:** Command router and symbolic addressing for AIPass. Resolves `@branch` names to paths at runtime via `AIPASS_REGISTRY.json`, routes commands to module entry points, manages git workflows, and discovers available commands across the system.
**Module:** `aipass.drone`
**Version:** 1.1.0
**Created:** 2026-03-05

---

## Overview

### What I Do
- Resolve `@branch` symbolic names to absolute paths via `AIPASS_REGISTRY.json`
- Route commands to registered branches and internal modules
- Manage git workflows: tier-based access (global read-only, owner write), commit, diff, log, sync, merge
- Discover and scan available commands across the system
- Provide `drone systems` introspection of all registered components
- Support external AIPass projects via dual registry lookup and module fallback

---

## Quick Start

```bash
drone systems                     # See all registered branches
drone @seedgo audit aipass        # Route a command to a branch
drone @flow --help                # Show help for any branch
drone scan @memory                # Discover available commands
```

---

## Commands / Usage

Drone provides a CLI for terminal use and a Python API for programmatic access.

### CLI

```bash
# Core routing
drone @seedgo audit aipass       # Route "audit aipass" to seedgo
drone @module --help             # Show help for any module
drone systems                    # List all registered modules and branches

# Git workflow — global tier (all branches)
drone @git status                # Git status scoped to branch directory
drone @git diff                  # Show git diff for your branch
drone @git diff --staged         # Show staged changes
drone @git log                   # Show recent git log (default: 10)
drone @git log 20                # Show last 20 commits
drone @git lock                  # Check lock status
drone @git tag --list            # List all tags (newest first)
drone @git issue list            # Passthrough to gh issue list
drone @git issue view 42         # Passthrough to gh issue view 42
drone @git run list              # Passthrough to gh run list
drone @git workflow list         # Passthrough to gh workflow list

# Git workflow — owner tier (the project's registry-declared owner)
drone @git commit "message"      # Commit whatever is already staged
drone @git commit "msg" --all    # Stage ALL repo changes and commit
drone @git commit "msg" f1 f2    # Stage only f1 f2, then commit
drone @git checkout dev          # Switch to dev branch
drone @git checkout main         # Switch to main branch
drone @git pr "desc"             # Push current branch and create PR to main
drone @git dev-pr "desc"         # Push dev and create PR to main
drone @git merge <PR#>           # Merge a PR and sync local main
drone @git delete-branch <name>  # Delete a remote branch (not main/dev)
drone @git close-pr <number>     # Close a PR by number
drone @git branches              # List remote branches
drone @git sync                  # Pull latest (branch-aware: main or dev)
drone @git sync --autostash      # Sync with autostash for dirty trees
drone @git smart-sync            # Fetch + detect divergence + rebase
drone @git unlock --force        # Force-release the PR lock
drone @git system-pr "desc"      # DEPRECATED — returns error message
drone @git tag v2.6.1            # Create + push annotated release tag
drone @git fix                   # Auto-fix stuck rebase / detached HEAD
drone @git fix --dry-run         # Detect issues without fixing

# Command discovery
drone scan @branch               # Discover available commands in a branch
drone activate @branch           # Scan + register all commands as shortcuts
drone list                       # List registered custom command shortcuts
drone remove <name>              # Remove a custom command shortcut

# Utilities
drone --version                  # Show version (v1.1.0)
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

### 3-Layer Pattern

```
drone/
├── cli.py                         # pip entry point (drone command)
├── __init__.py                    # Public API exports (v1.1.0)
├── apps/
│   ├── drone.py                   # Core entry + CLI routing
│   ├── modules/                   # Orchestrators (business logic)
│   │   ├── config.py              # Registry path resolution
│   │   ├── resolver.py            # Branch resolution (@name → path)
│   │   ├── router.py              # Command routing via subprocess
│   │   ├── discovery.py           # Module and command discovery
│   │   ├── module_registry.py     # Internal module routing
│   │   ├── registry.py            # Registry query operations
│   │   ├── commands.py            # Custom command shortcut orchestrator
│   │   ├── git_module.py          # Git workflow (tier-based access, 16 commands)
│   │   ├── scan.py                # Branch command scanning
│   │   └── broker.py             # Broker daemon orchestrator (sandbox delete)
│   ├── handlers/                  # Implementation details
│   │   ├── executor.py            # Safe subprocess execution (timeout, no shell)
│   │   ├── exceptions.py          # Exception hierarchy (10 exception types)
│   │   ├── router_handler.py      # Routing implementation + caller identity resolution
│   │   ├── registry_handler.py    # Registry file ops + dual registry lookup
│   │   ├── discovery_handler.py   # Discovery implementation + help parsing
│   │   ├── module_registry_handler.py  # Module loading (internal + external)
│   │   ├── generic_adapter.py     # StringIO capture for external modules
│   │   ├── routing_config.json    # External module declarations
│   │   ├── broker/
│   │   │   ├── daemon.py          # Broker daemon (unix socket, openat2, audit)
│   │   │   ├── client.py          # Broker client (inherited fd transport)
│   │   │   ├── path_resolver.py   # openat2 RESOLVE_BENEATH path resolution
│   │   │   └── protocol.py       # Typed JSON-line IPC (BrokerRequest/Response)
│   │   ├── json/
│   │   │   └── json_handler.py    # Structured operation logging
│   │   ├── scanning/
│   │   │   ├── scanner.py         # Help parsing + modules/ file scanning
│   │   │   └── formatters.py      # Rich output for scan results
│   │   ├── command_registry/
│   │   │   ├── ops.py             # Command shortcut CRUD
│   │   │   ├── lookup.py          # Greedy multi-word matching
│   │   │   └── formatters.py      # Rich output for command lists
│   │   └── git/
│   │       ├── auth.py                      # Tier-based access (verify_git_access)
│   │       ├── lock_handler.py              # Atomic lockfile (O_CREAT|O_EXCL)
│   │       ├── pr_handler.py                # DEPRECATED — returns error message
│   │       ├── diff_handler.py              # Scoped git diff (--staged support)
│   │       ├── log_handler.py               # Scoped git log (configurable count)
│   │       ├── commit_handler.py            # Commit changes (--all, selective files, or pre-staged)
│   │       ├── checkout_handler.py          # Branch switching (main/dev guard)
│   │       ├── dev_pr_handler.py            # Push dev and create PR to main
│   │       ├── branches_handler.py          # List remote branches
│   │       ├── delete_branch_handler.py     # Delete remote branch (main/dev protected)
│   │       ├── close_pr_handler.py          # Close PR by number (gh pr close)
│   │       ├── status_handler.py            # Scoped git status (subprocess)
│   │       ├── sync_handler.py              # Safe main sync (--autostash support)
│   │       └── tag_handler.py               # Release tagging (version + exists guards)
│   └── plugins/
│       ├── devpulse_ops/          # Privileged git operations (auth-gated)
│       │   ├── auth.py            # Passport-based identity gate (owner tier earned per-repo)
│       │   ├── pr_plugin.py       # System-wide PR (git add -A, system/ branches)
│       │   ├── merge_plugin.py    # PR merge (--merge) + local sync
│       │   ├── sync_plugin.py     # Smart sync (fetch, divergence detect, rebase)
│       │   └── fix_plugin.py      # Auto-fix stuck rebase / detached HEAD
│       └── hook_sounds/                   # DISABLED — moved to hooks branch (drone @hooks hooksound on/off)
│           └── hook_sounds_plugin.py.disabled
├── docs/                          # Public documentation
├── docs.local/                    # Investigation reports and policies
├── artifacts/                     # Live acceptance test scripts
└── tests/                         # 986 tests across 25 test files
```

### Routing Flow

1. **CLI input** → `drone.py:main()`
2. **Built-in commands** checked first: `systems`, `scan`, `activate`, `list`, `remove`
3. **`@target` routing** → branch resolution via `AIPASS_REGISTRY.json` → subprocess dispatch
4. **Module fallback** → if branch not found but is a registered module, routes internally
5. **Bare module names** → auto-discovered from `apps/modules/*.py`, routed via `importlib`
6. **Custom commands** → greedy multi-word matching against `drone_command_registry.json`

### Module System

Drone routes to two kinds of modules:

| Type | Modules | Routing |
|------|---------|---------|
| Internal | `git` | `importlib` import → `handle_command()` |
| External | `seedgo`, `cli`, `spawn` | `generic_adapter.capture_main()` via `routing_config.json` |

External modules are declared in `apps/handlers/routing_config.json` with entry points, descriptions, and versions.

### Caller Identity

Every routed command is attributed to a caller, stamped into `AIPASS_CALLER_BRANCH` and the `[CALLER:X]` log tag. `resolve_caller_identity()` in `router_handler.py` weighs two signals:

| Signal | Question it answers | Precedence |
|--------|--------------------|------------|
| `AIPASS_BRANCH_NAME` | Who this process **is** (assigned at spawn) | Wins |
| cwd `.trinity/passport.json` | Who lives **where** the process stands (inferred) | Fallback |
| cwd `*_REGISTRY.json` | Which **project** the process is in — never a citizen | Last resort |

Assigned identity beats location: an agent that cds into another branch is still itself. Nothing here grants authority — git's owner tier reads passports directly.

**Log severity is chosen by what the outcome means, not by how unusual it looks:**

| Situation | Level | Why |
|-----------|-------|-----|
| Assigned identity vs a **passport** naming someone else | `WARNING` | Two citizens claim one process — genuinely abnormal, stays loud |
| Assigned identity while standing in a **project** root | `INFO` | Not a conflict. A project name is location, not a rival claim of identity — the ordinary shape of every long-lived service |
| No passport and no registry found | `INFO` | An anonymous caller is a correct outcome. Attribution reads `unknown`; whoever refuses work for want of an identity owns the page |

Identity messages are logged **once per process per signature**. Neither signal can change under a running process, so a repeat restates the first. Suppression is per-process only, so a real conflict recurring across separate invocations still accumulates and still escalates. The per-call `[CALLER:X]` tag and stamp are never suppressed — every call stays individually attributable.

### Git Access Tiers

Auth centralized via `verify_git_access()` in `apps/plugins/devpulse_ops/auth.py`. Two tiers:

| Tier | Who | Commands |
|------|-----|----------|
| **Global** | All branches | `status`, `diff`, `log`, `lock`, `branches`, `tag --list`, `issue`, `run`, `workflow` |
| **Owner** | `devpulse` only | `pr`, `commit`, `checkout`, `dev-pr`, `delete-branch`, `close-pr`, `sync`, `unlock`, `system-pr`, `merge`, `smart-sync`, `fix`, `tag` |

- Auth is checked once at the top of `git_module.handle_command()` before any handler is called
- Unauthorized commands return a clear "Access denied" message with the caller's tier

### Dev Branch Model

All work happens on `dev`. Only devpulse has write access. Agents build and report; devpulse commits.

**Flow:** work on dev → stack changes → `drone @git dev-pr "desc"` → merge PR → `drone @git sync` (realigns dev from main)

**`pr` vs `dev-pr`:** `pr` works from any branch — on main it auto-creates a temp branch from the description slug (`main:<slug>`), on other branches it pushes directly. Does NOT use `-u` so main's upstream tracking stays on `origin/main`. `dev-pr` is specific to the dev→main workflow.

Enforcement layers:
- Git gate (PreToolUse hook) blocks ALL raw git/gh commands
- Drone tier system restricts write commands to the project's registry-declared owner
- Prompt instructions tell agents they have zero git access

---

## Interactive Commands

By default, drone captures subprocess output (`capture_output=True`) with a 30s timeout. This is safe for AI-to-AI routing but strips Rich colors, buffers progress bars, and kills long-running commands.

Commands in the interactive tuple bypass capture and inherit the terminal directly — enabling live Rich output, colors, and no timeout.

**Always interactive** — these presentational commands always inherit the terminal for Rich color on a TTY, plain when piped:

| Pattern        | Reason                                      |
|----------------|---------------------------------------------|
| `@branch`      | No-args introspection (branch overview)     |
| `@branch --help` | Help output with Rich formatting          |
| `@branch -h`   | Short help flag (same as --help)            |

**Per-command allowlist** (in `apps/drone.py`):

| Command      | Reason                                      |
|--------------|---------------------------------------------|
| `monitor`    | Prax real-time monitoring (live TUI)        |
| `audit`      | Seedgo audit (Rich progress bars)           |
| `watchdog`   | Devpulse watchdog (live monitoring)         |
| `status`     | Branch status with Rich formatted output    |

**Per-branch allowlist** — all commands from these branches get interactive mode:

| Branch   | Reason                                        |
|----------|-----------------------------------------------|
| `cli`    | User-facing CLI with Rich formatted output    |

To add: edit `INTERACTIVE_COMMANDS` or `INTERACTIVE_BRANCHES` in `apps/drone.py`.

---

## Plugin System

Plugins live in `apps/plugins/{name}/` — outside the 3-layer structure by design.

### devpulse_ops

Auth-gated operations for system administration. `auth.py` walks CWD for `.trinity/passport.json`, then earns owner tier from four facts in the caller's own project registry: `citizen_class: manager`, registry tenancy, an `owner: true` entry, and path-binding of the passport to the recorded home. No hardcoded caller list — the owner is devpulse in AIPass and whoever owns elsewhere.

| Plugin | Command | Purpose |
|--------|---------|---------|
| `pr_plugin` | `system-pr` | System-wide PR across all tracked changes |
| `merge_plugin` | `merge` | Straight-merge a PR and sync local main |
| `sync_plugin` | `smart-sync` | Fetch + detect divergence + rebase |
| `fix_plugin` | `fix` | Auto-fix stuck rebase / detached HEAD |

### hook_sounds (DISABLED)

Moved to hooks branch as `drone @hooks hooksound on/off`. Plugin file renamed to `.disabled`.

---

## External Project Support

Infrastructure modules (seedgo, cli, git, spawn) work from external AIPass projects without per-project registration.

**Dual registry lookup:** `registry_handler.py` merges local project registry with `AIPASS_HOME` registry. Local entries win on name collision.

**Module fallback:** When subprocess routing fails (branch not in local registry), drone falls back to module routing for registered modules. Graceful degradation: Rich output from AIPass, functional output from external projects.

**AIPASS_HOME hints:** When `AIPASS_HOME` is not set and the local registry lacks core branches, drone shows setup hints:
```
Tip: set AIPASS_HOME=/path/to/AIPass to access all branches
```

---

## Integration Points

### Depends On
- `AIPASS_REGISTRY.json` — Branch registry (read for resolution)
- `gh` CLI — GitHub operations (PR creation, merge)
- Python stdlib (`pathlib`, `sys`, `subprocess`, `json`, `threading`)

### Provides To
- All branches — command routing via `drone @target command`
- All branches — module/branch discovery via `drone systems`
- External modules — `generic_adapter.capture_main()` for subprocess-free routing
- `aipass.seedgo` — routed via `drone @seedgo`
- `aipass.cli` — routed via `drone @cli`
- `aipass.spawn` — routed via `drone @spawn`

---

## Testing

986 tests across 25 test files, covering all layers:

| Area | Files | Tests |
|------|-------|-------|
| Core routing | `test_resolver.py`, `test_router.py`, `test_activation.py` | ~128 |
| Git operations | `test_git_module.py`, `test_system_pr.py`, `test_devpulse_plugins.py`, `test_git_access.py`, `test_tag_handler.py` | ~170 |
| Handlers | `test_executor.py`, `test_registry_handler.py`, `test_discovery.py` | ~99 |
| Infrastructure | `test_generic_adapter.py`, `test_module_registry.py`, `test_config.py` | ~66 |
| Features | `test_commands.py`, `test_scan.py`, `test_json_handler.py`, `test_rm.py` | ~181 |
| Broker | `test_broker.py` | ~55 |
| Standards | `test_cli_routing.py`, `test_contracts.py`, `test_error_resilience.py`, `test_init_provisioning.py` | ~21 |

Run tests: `cd src/aipass/drone && python -m pytest tests/ -q`

---

## Known Issues

- `update_command()` and `command_exists()` in `ops.py` are tested CRUD API but unused from production
- `reset_identity_log_dedupe()` in `router_handler.py` has no production caller by design — it clears process-lifetime state for the test suite (an autouse conftest fixture) and for long-lived hosts embedding drone as a library. Not bypassed in seedgo: a file-level bypass would blind the detector to real findings in the same file
- Pyright warns about `json` package name shadowing stdlib — works at runtime
- Recurring sync errors when working tree is dirty — operational, not code bugs

---

**Seedgo:** 99% | **Tests:** 981 pass, 5 skip | **Last Updated:** 2026-08-08

---
[← Back to AIPass](../../../README.md)
