# DRONE — Branch Prompt
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/drone/.aipass/aipass_local_prompt.md — Injected every prompt when in drone directory. Cap: 9,000 chars (hooks BRANCH_CHAR_BUDGET), measured by `drone @seedgo audit context @drone`. -->

Command router and symbolic addressing for AIPass. Resolves `@branch` names to paths, routes commands to entry points, and owns all git operations behind a tier-based access gate. The only git interface in the system — raw git and gh are blocked by a hook.

# Where things are

Inventory is generated, never written down: `drone @drone` for the module self-map, `drone @drone --help` for the routing surface, `drone @git --help` for every git verb and refusal, `drone rm --help` for the delete rules. Depth is in `docs/`, indexed from `README.md`.

```
apps/
├── drone.py                     # Entry point, routing decision tree, interactive lists
├── modules/                     # One orchestrator per concern
│   ├── resolver.py              # @name → path
│   ├── config.py                # Registry path resolution
│   ├── router.py                # Dispatch (subprocess or in-process)
│   ├── registry.py              # Registry queries
│   ├── module_registry.py       # Internal module routing
│   ├── discovery.py             # What a branch can do
│   ├── scan.py                  # Branch command scanning
│   ├── commands.py              # Custom command shortcuts
│   ├── git_module.py            # The whole git surface
│   ├── rm.py                    # Contained safe-delete
│   └── broker.py                # Broker daemon orchestrator
├── handlers/
│   ├── executor.py              # Subprocess execution: no shell, timeout, capture
│   ├── router_handler.py        # Routing + caller identity resolution
│   ├── registry_handler.py      # Registry file ops + dual registry lookup
│   ├── discovery_handler.py     # Discovery + help parsing
│   ├── module_registry_handler.py  # Module loading (internal + external)
│   ├── generic_adapter.py       # StringIO capture for external modules
│   ├── help_flags.py            # wants_help() — help anywhere means explain
│   ├── json_flags.py            # wants_json() / strip_json_flag() — --json in any slot
│   ├── module_root.py           # Resolve __file__ without an import-time cwd read
│   ├── rm_handler.py            # Containment guards, delete, stale sweep
│   ├── deletion_log.py          # Deletion + door ledgers in .ai_central/
│   ├── exceptions.py            # Exception hierarchy
│   ├── routing_config.json      # External module declarations
│   ├── git/                     # One handler per verb, plus repo_door.py and repo_context.py
│   ├── broker/                  # daemon, client, protocol, path_resolver
│   ├── scanning/                # scanner, formatters
│   ├── command_registry/        # ops, lookup, formatters
│   └── json/                    # json_handler.py — the fleet shim, bound to prax
└── plugins/devpulse_ops/        # auth.py + merge, sync and fix plugins
```

# Routing

Three paths, checked in order. The lane is decided before the call, never discovered by failing one.

 - Built-ins first: `systems`, `scan`, `activate`, `list`, `remove`, `rm` — handled in `drone.py`.
 - `@target`: resolve via `AIPASS_REGISTRY.json`, dispatch as a subprocess. No module fallback on the error path — a `BranchNotFoundError` from a listed branch is a real fault and fails loud.
 - Module lane: internal (`git`) via importlib, external (`seedgo`, `cli`, `spawn`) via `generic_adapter` and `routing_config.json`.

One fallback survives, in the custom-command lane only, logged at INFO. It resolves its target from `drone_command_registry.json` rather than from argv, so the look-before-route check does not reach it.

# Git tiers

Auth is checked once, at the top of `git_module.handle_command()`, via `verify_git_access()`.

 - Global tier, every branch: the read doors and the gh passthroughs.
 - Owner tier, the project's registry-declared owner: everything that writes.
 - Owner tier is earned per repo from four facts — manager class, registry tenancy, an `owner: true` entry, passport path-binding. There is no caller allowlist anywhere in the branch.
 - A verb in neither tier is unreachable, not merely ungated: `verify_git_access()` refuses what it cannot find in a tier.
 - Refusals come in two species and they are not interchangeable: not authorized is about who you are, cannot run here is about which repository you are in. Only the first is lifted by `AIPASS_GIT_AUTH_MODE=warn`.

# Gotchas

 - A routed command runs in the target's directory (`cwd=branch_path`). A module walking up for a project lands on the target's tree; the caller's own directory travels as `AIPASS_CALLER_CWD`.
 - A module routed in-process has no caller stamp. `@git` runs inside drone, so `AIPASS_CALLER_*` is unset unless the lane stamps it itself — the external-repo door does, and restores it after.
 - Module routing captures output as dicts; branch routing can inherit the TTY. A command needing a live terminal must be in `INTERACTIVE_COMMANDS` or `INTERACTIVE_BRANCHES`, and the target is checked for a branch before the interactive lane is taken.
 - Routed output uses `sys.stdout.write()`, not `console.print()`. Rich wraps at 80 columns when piped.
 - Caller identity prefers `AIPASS_BRANCH_NAME` (assigned) over the cwd passport (inferred). Attribution only — git authority reads passports directly. The provenance travels as `AIPASS_CALLER_IDENTITY_SOURCE`; a consumer that decides on identity takes the signal, not the bare name.
 - A help flag anywhere means explain, never execute. The check lives inside each `handle_command()`, because every module also has a standalone `__main__` path the router never touches.
 - A new flag can eat a passthrough's own flag: `--repo` had to be excluded from `issue`, `run` and `workflow`, where it is gh's own.
 - Commit subjects are capped at prax's `SUBJECT_CAP`, imported from `aipass.prax.apps.modules.dashboard`. Read the cap, never copy the number.
 - Interned small ints make an identity pin scenery: prove a constant is imported by reading the import line, not by comparing values.
 - Dual registry: local project plus `AIPASS_HOME`. Local entries win on a name collision.

# Rules of this seat

 - Never edit another branch's files. Mail the owner.
 - No git writes from here: this branch owns the interface, not the authority. Report, and @devpulse commits.
 - New test files are gated by policy. Edit an existing file, or ask @devpulse for the new one.
 - Every delete goes through `drone rm`, which records it. Nothing is deleted by hand.
 - Prove a fix with a mutant: apply it, run the targeted tests, expect red, restore.

# Integration points

 - Depends on: `AIPASS_REGISTRY.json` and `AIPASS_ROOTS.json` (resolution), `.trinity/passport.json` (authority), the `gh` CLI, prax (logging and the json service), cli (Rich).
 - Provides to: every branch — routing, discovery, the git interface, the sanctioned delete path and its audit trail.
 - Dev branch model: all work on `dev`, only @devpulse commits, `dev-pr` pushes dev and opens the PR to main.
