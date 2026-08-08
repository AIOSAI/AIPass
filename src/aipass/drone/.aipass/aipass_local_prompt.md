# DRONE — Branch Prompt
<!-- File: src/aipass/drone/.aipass/aipass_local_prompt.md — Injected every prompt when in drone directory. -->

Command router and symbolic addressing for AIPass. Resolves `@branch` names to paths, routes commands to entry points, and owns all git operations behind a tier-based access system. The only git interface in the system — raw git/gh is blocked by hooks.

# Commands

```
drone @branch command args          # Route command to any branch
drone @branch                       # No-args introspection (what a branch IS)
drone @branch --help                # Full usage reference
drone systems                       # List all registered branches and modules
drone @git status / diff / log      # Read-only git (all branches)
drone @git commit / pr / sync       # Write git (devpulse only)
drone scan @branch                  # Discover available commands
drone activate @branch              # Register command shortcuts
```

Full command list: `drone --help` or README.

# Architecture

Three routing paths, checked in order:

 - Built-in commands: `systems`, `scan`, `activate`, `list`, `remove` — handled directly in `drone.py`.
 - `@target` routing: resolve via `AIPASS_REGISTRY.json` → subprocess dispatch. Interactive commands (monitor, audit, watchdog, status, bare introspection, --help) inherit the terminal for Rich output.
 - Module fallback: internal modules (`git`) via importlib, external modules (`seedgo`, `cli`, `spawn`) via `generic_adapter` and `routing_config.json`.

```
apps/
├── drone.py                # Core entry + CLI routing
├── modules/                # Orchestrators: resolver, router, git_module, commands, scan
├── handlers/               # Implementation: executor, registry, discovery, git/, broker/
└── plugins/devpulse_ops/   # Auth-gated write operations (PR, merge, sync, fix)
```

Full tree and details in README.

# Git Tier System

Auth checked once at top of `git_module.handle_command()` via `verify_git_access()`.

 - Global tier (all branches): `status`, `diff`, `log`, `lock`, `branches`, `tag --list`, `issue`, `run`, `workflow`.
 - Owner tier (devpulse only): `commit`, `pr`, `dev-pr`, `merge`, `checkout`, `sync`, `smart-sync`, `delete-branch`, `close-pr`, `unlock`, `fix`, `tag`.

Three enforcement layers: hooks block raw git/gh, drone tier restricts write commands, prompt instructions tell agents they have no git access.

# Critical Files

 - `apps/drone.py` — entry point, routing decision tree, interactive command lists.
 - `apps/modules/git_module.py` — git orchestrator, tier dispatch, adapter for `_MODULE_REGISTRY`.
 - `apps/plugins/devpulse_ops/auth.py` — passport-based identity gate. Owner tier is EARNED per-repo from four facts (manager class + registry tenancy + owner flag + passport path-binding), not a hardcoded name list.
 - `apps/handlers/registry_handler.py` — dual registry lookup (local project + `AIPASS_HOME` fallback).
 - `apps/handlers/executor.py` — safe subprocess execution (no shell, timeout, capture).

# Operational Rules

 - Module routing captures output (dicts). Branch routing can inherit TTY. Commands needing live terminal (Rich progress, TUI) must be in `INTERACTIVE_COMMANDS` or `INTERACTIVE_BRANCHES` — checked before `is_module()`.
 - Routed command output uses `sys.stdout.write()`, not `console.print()`. Rich wraps at 80 cols when piped.
 - Caller identity: `resolve_caller_identity()` prefers `AIPASS_BRANCH_NAME` (assigned at spawn) over the cwd passport (inferred from location) — an agent that cds is still itself. Disagreements are logged. Attribution only; git authority reads passports directly.
 - External project support: dual registry merges local + AIPASS_HOME registries. Local entries win on collision.

# Integration Points

 - Depends on: `AIPASS_REGISTRY.json` (branch resolution), `gh` CLI (GitHub ops), `.trinity/passport.json` (auth).
 - Provides to: every branch — command routing, module/branch discovery, git workflows.
 - Dev branch model: all work on `dev`, only devpulse commits. `dev-pr` pushes dev → PR to main.
