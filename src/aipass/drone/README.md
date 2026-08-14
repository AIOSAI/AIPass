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
drone @git show <ref>            # Show a commit
drone @git show <ref> <path>     # Read a file's contents AT that commit
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
drone @git prune-temp            # Delete merged citizen/* temp branches
drone @git unlock --force        # Force-release the PR lock
drone @git tag v2.6.1            # Create + push annotated release tag (see Tag lanes)
drone @git fix                   # Auto-fix stuck rebase / detached HEAD
drone @git fix --dry-run         # Detect issues without fixing

# Command discovery
drone scan @branch               # Discover available commands in a branch
drone activate @branch           # Scan + register all commands as shortcuts
drone list                       # List registered custom command shortcuts
drone remove <name>              # Remove a custom command shortcut

# Utilities
drone rm <path> [<path>...]      # Contained safe-delete (project + tmp only)
drone @flow list --drone-timeout 90   # Override subprocess timeout (default 60s)
                                      # Must come AFTER @target — anywhere after it works
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
│   │   ├── git_module.py          # Git workflow (tier-based access, 22 commands)
│   │   ├── scan.py                # Branch command scanning
│   │   ├── rm.py                  # Contained safe-delete orchestrator
│   │   └── broker.py             # Broker daemon orchestrator (sandbox delete)
│   ├── handlers/                  # Implementation details
│   │   ├── executor.py            # Safe subprocess execution (timeout, no shell)
│   │   ├── exceptions.py          # Exception hierarchy (10 exception types)
│   │   ├── router_handler.py      # Routing implementation + caller identity resolution
│   │   ├── registry_handler.py    # Registry file ops + dual registry lookup
│   │   ├── discovery_handler.py   # Discovery implementation + help parsing
│   │   ├── module_registry_handler.py  # Module loading (internal + external)
│   │   ├── generic_adapter.py     # StringIO capture for external modules
│   │   ├── help_flags.py          # wants_help() — whole-sequence help detection (rule E)
│   │   ├── rm_handler.py          # Path containment checks + deletion
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
│   │       ├── lock_handler.py              # Atomic lockfile (O_CREAT|O_EXCL)
│   │       ├── pr_handler.py                # ORPHANED — superseded by dev_pr_handler, no production caller
│   │       ├── diff_handler.py              # Scoped git diff (--staged support)
│   │       ├── log_handler.py               # Scoped git log (configurable count)
│   │       ├── show_handler.py              # Read history at a commit (repo-wide, NOT branch-scoped)
│   │       ├── commit_handler.py            # Commit changes (--all, selective files, or pre-staged)
│   │       ├── checkout_handler.py          # Branch switching (main/dev guard)
│   │       ├── dev_pr_handler.py            # Push dev and create PR to main
│   │       ├── branches_handler.py          # List remote branches
│   │       ├── delete_branch_handler.py     # Delete remote branch (main/dev protected)
│   │       ├── close_pr_handler.py          # Close PR by number (gh pr close)
│   │       ├── status_handler.py            # Scoped git status (subprocess)
│   │       ├── sync_handler.py              # Safe main sync (--autostash support)
│   │       ├── repo_context.py              # Which repo is underfoot — AIPass's own or external
│   │       └── tag_handler.py               # Release tagging (two lanes: AIPass main, external HEAD)
│   └── plugins/
│       ├── devpulse_ops/          # Privileged git operations (auth-gated)
│       │   ├── auth.py            # Passport-based identity gate (owner tier earned per-repo)
│       │   ├── merge_plugin.py    # PR merge (--merge) + local sync
│       │   ├── sync_plugin.py     # Smart sync (fetch, divergence detect, rebase)
│       │   └── fix_plugin.py      # Auto-fix stuck rebase / detached HEAD
│       └── hook_sounds/                   # DISABLED — moved to hooks branch (drone @hooks hooksound on/off)
│           ├── __init__.py.disabled
│           └── hook_sounds_plugin.py.disabled
├── docs/                          # Public documentation
├── docs.local/                    # Investigation reports and policies
├── artifacts/                     # Live acceptance test scripts
└── tests/                         # 1019 tests across 25 test files
```

### Routing Flow

1. **CLI input** → `drone.py:main()`
2. **Built-in commands** checked first: `systems`, `scan`, `activate`, `list`, `remove`, `rm`
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

There is no public reset for the dedupe set: production never needs to forget what it has already logged. The test suite clears `_LOGGED_IDENTITY_SIGNATURES` directly from an autouse fixture in `tests/conftest.py`.

### Git Access Tiers

Auth centralized via `verify_git_access()` in `apps/plugins/devpulse_ops/auth.py`. Two tiers:

| Tier | Who | Commands |
|------|-----|----------|
| **Global** | All branches | `status`, `diff`, `log`, `show`, `lock`, `branches`, `tag --list`, `issue`, `run`, `workflow` |
| **Owner** | The project's registry-declared owner — **earned, never hardcoded** (devpulse in AIPass) | `pr`, `commit`, `checkout`, `dev-pr`, `delete-branch`, `prune-temp`, `close-pr`, `sync`, `unlock`, `merge`, `smart-sync`, `fix`, `tag` |

- Auth is checked once at the top of `git_module.handle_command()` before any handler is called
- Unauthorized commands are refused with a message naming the caller, its `citizen_class`, and the tier required
- **A command in neither tier is unreachable, not merely ungated** — `verify_git_access()` refuses anything it cannot find in a tier as `Unknown git command`, so registering a verb in `_COMMANDS` and wiring it to a handler does not make it callable. `prune-temp` shipped that way and no caller could reach it (found in the APLAN-0003 audit, tier ruled by @devpulse). `test_every_registered_command_holds_a_tier` now asserts the rule rather than the instance

### Subprocess timeouts

Routed commands run with a timeout resolved in this order — **explicit flag > per-command policy > default**:

| Layer | Value | Where |
|-------|-------|-------|
| Default | **60s** | `DEFAULT_TIMEOUT` in `apps/handlers/executor.py` |
| Per-command policy | e.g. `memory process-plans` 120s, `memory rollover` 100s, `flow close` 90s | `TIMEOUT_OVERRIDES` in the same file |
| Explicit | whatever you pass | `--drone-timeout <n>` |

The default was raised 30 → 60 on 2026-08-13 (Patrick's ruling): two known runners finish around 31s and were tripping the old default. A per-command policy is a decision, not a floor — it wins even if it is *lower* than the default.

The signature defaults of `execute_command()` and `execute_branch_command()` reference `DEFAULT_TIMEOUT` rather than restating the number, so the layers cannot silently disagree. `tests/test_executor.py::TestDefaultTimeoutValue` pins the number itself and asserts all three layers agree.

**Where `--drone-timeout` goes:** anywhere **after** the `@target`, including after the routed command and its arguments. It is stripped from the argument list before routing, so the target branch never sees it.

```bash
drone @flow list --drone-timeout 90     # ✅ after the command
drone @flow --drone-timeout 90 list     # ✅ between target and command
drone --drone-timeout 90 @flow list     # ❌ before the target — drone: unknown command '--drone-timeout'
```

### Help flags — explain, never execute

A help flag **anywhere** in a command means explain, never execute (DPLAN-0291 rule E). Every module's `handle_command()` calls `wants_help()` from `apps/handlers/help_flags.py` before dispatching:

- `--help` / `-h` — exact match, honoured in **any** position, including the subcommand slot
- bare `help` — position 0 only, since later positions are legitimate values (a path to delete, a branch to look up)

Modules that own `help` as a real verb pass `bare_help=False`; `discovery` does, so `drone @discovery help @seedgo` keeps working while `... help @seedgo --help` still explains.

The check lives **inside** each `handle_command()`, not in the router, because every module also has a standalone `__main__` path that takes raw argv and never touches the router. One predicate, ten call sites — the gate previously existed as ten copies of the same two lines, which is how ten modules drifted into the same bug at once.

Why it mattered: the old gate read only `command` or `args[0]`, so `drone rm notes.md --help` **deleted notes.md** and then tried to delete a file named `--help`. `tests/test_help_flag_safety.py` mocks every dispatch target and asserts it was never called — no live verb is fired to prove the trap.

### Reading history — `show`

`show` sits at global tier because reading history is not a write. It is deliberately **not** scoped to the caller's branch directory the way `status`, `diff` and `log` are: those scope for convenience, hiding other branches' noise, whereas scoping `show` would refuse the case it exists for — one citizen auditing another's past. Auditing a deletion means reading what was deleted, and the present-tense verbs cannot.

Both the ref and the optional path are refused before any argv is built if git would read them as a flag (empty or leading `-`), the same guard the tag lanes use.

### Deleting — every delete leaves a record

`drone rm` is the fleet's only sanctioned delete path (raw recursive `rm` is gate-blocked), which makes it the choke point where the record belongs. Patrick's ruling: *"if something deletes, there should be a record of it."*

Two channels, written by `handlers/deletion_log.py`:

| Channel | Where | What it is for |
|---|---|---|
| JSONL store | `<project>/.ai_central/deletions.jsonl` | machine-readable, findable months later |
| prax line | normal logs, **INFO** | flows through observability without knowing this file exists |

The prax line is emitted **first**. If the store write fails it is reported at ERROR and the delete still proceeds — losing the log must not turn into losing the delete, and the event has already reached the logs either way.

A record carries: `timestamp`, `lane`, `outcome`, `caller`, `cwd`, `requested` (what was typed), `path` (resolved), `reason`, `kind`, `size_bytes`, `entry_count`, `measured`.

Four things worth knowing:

 - **Refusals are records too.** A blocked delete leaves no other trace of what was attempted, which is exactly what makes it worth finding later. Refused paths are deliberately *not* measured — the guard just said that tree is off-limits, so nothing goes and reads inside it.
 - **Measurement happens before the delete.** After `rmtree` there is nothing left to ask how big it was. Directory walks stop at `_MEASURE_ENTRY_CAP` and say so via `measured: "capped"` rather than paying an unbounded walk.
 - **Severity is INFO on both channels** (compass #273). A deletion through the sanctioned path is chosen behaviour, not a fault. The guards keep their own WARNING when they refuse — that is the guard speaking, and it is a separate line from the record.
 - **Identity is resolved, never guessed.** `resolve_caller_identity()` — the same passport/registry resolver routing and git attribution use, not a fifth one and not path-shape matching. Unresolvable callers are recorded as `unknown`; a wrong-but-plausible name on a deletion record is worse than an honest gap.

Both of drone's delete lanes feed it: `rm` (`handlers/rm_handler.py`) and `broker` (`handlers/broker/daemon.py`, which deletes on behalf of an HMAC-authenticated requester and therefore passes that identity in rather than reading its own cwd). The broker's protocol audit log is unchanged — that records requests and error codes; this records deletions.

`AIPASS_DELETION_LOG` relocates the store (tests, containers). It cannot silence the prax line.

Bounded at 2 MB with one rotation, because a delete log that grows forever becomes the runaway log the monitoring lane exists to catch.

### Sibling-branch guard — outermost `.trinity` wins

The guard refuses deletes inside another citizen's tree, and it finds the owning citizen by walking up for `.trinity/`. It takes the **outermost** hit within the project, not the innermost, because `.trinity/` is not proof of a citizen: @spawn ships a complete branch skeleton under `templates/`, passport and all.

Innermost-wins produced two bugs from one mimicry — refusals named `aipass_framework`, which is a template with no mailbox to appeal to, and @spawn was locked out of its own `templates/` because a skeleton's name never matches the branch you are standing in. Same mimicry sent the commit gate running pytest inside the template; outermost-citizen-wins is the mapping that fixed it there (`e934099f`), applied here.

Safe because nothing above a branch carries `.trinity/` — not the project root, not `src/`, not `src/aipass/` — so the outermost hit inside the project *is* the citizen. The walk stops at the project boundary.

### Tag lanes — AIPass vs an external repo

`tag` is one verb with two release lanes, chosen by the repo the command will actually run in (`repo_context.is_aipass_repo()` — the root holds `AIPASS_REGISTRY.json` or it doesn't). The gate that used to refuse `tag` from a `projects/*` seat is gone: it now translates.

| | AIPass repo | External project seat |
|---|---|---|
| What gets tagged | `origin/main` | that repo's current **HEAD**, any branch |
| Version guard | `pyproject.toml` + `src/aipass/__init__.py` on origin/main must both match | **none** — manifests and cadence belong to the repo owner |
| Name rule | `vX.Y.Z` | anything `git check-ref-format` accepts (`v0.1.0-rc1`, `2026.08.1`, …) |
| Duplicate guard | refuses if the tag exists locally or on the remote | same, and the remote check's exit code is verified — an unreachable remote refuses instead of tagging blind |
| Push | `git push origin <tag>` | same, to that repo's own origin |

Both lanes create **annotated** tags. Names that git would read as a flag (empty, leading `-`) are refused before any argv is built.

Why no version guard outside AIPass: an external repo has its own manifests (baud carries three) and its own release lane. Reading ours out of someone else's tree would be an invented rule, so version discipline stays with the repo owner (DPLAN-0290 item 1, Patrick's ruling).

Both lanes are covered by `tests/test_tag_handler.py`, where `TestAipassSeatUnchanged` pins the AIPass lane argv-for-argv so translation elsewhere cannot move it. The external lane was additionally proven end to end against a throwaway repo with a real bare origin — real tag, real push, both duplicate halves — by a local acceptance script in `artifacts/` (that directory is git-ignored, so it is not in a clone).

### gh Passthrough Rendering

`issue`, `run`, and `workflow` pass straight through to the `gh` CLI. One exception: `issue view <n>`.

gh's default view is a GraphQL query that requests `repository.issue.projectCards` — a Projects-classic field GitHub now rejects outright. The call returned the deprecation notice and **no issue at all** (exit 1), and `--comments` failed the same way.

`_rewrite_issue_view()` in `git_module.py` renders the same view from pinned `--json` fields plus a `--template`, so the dead field is never requested. `--comments` becomes a requested field rather than a flag (it conflicts with `--json`). Callers who already chose a rendering — `--json`, `--jq`, `--template`, `--web` — keep their own invocation untouched; unrelated flags like `--repo` are preserved. No other issue subcommand is rewritten.

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
| `backup` | Snapshot/restore progress needs a live terminal |

To add: edit `INTERACTIVE_COMMANDS` or `INTERACTIVE_BRANCHES` in `apps/drone.py`.

---

## Plugin System

Plugins live in `apps/plugins/{name}/` — outside the 3-layer structure by design.

### devpulse_ops

Auth-gated operations for system administration. `auth.py` walks CWD for `.trinity/passport.json`, then earns owner tier from four facts in the caller's own project registry: `citizen_class: manager`, registry tenancy, an `owner: true` entry, and path-binding of the passport to the recorded home. No hardcoded caller list — the owner is devpulse in AIPass and whoever owns elsewhere.

| Plugin | Command | Purpose |
|--------|---------|---------|
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

1123 tests collected across 28 test files (1118 pass, 5 skip), covering all layers. Counts below are pytest-collected, verified 2026-08-14:

| Area | Files | Tests |
|------|-------|-------|
| Core routing | `test_resolver.py`, `test_router.py`, `test_activation.py`, `test_registry.py` | 183 |
| Git operations | `test_git_access.py`, `test_git_module.py`, `test_tag_handler.py`, `test_devpulse_plugins.py`, `test_system_pr.py` | 335 |
| Handlers | `test_registry_handler.py`, `test_discovery.py`, `test_executor.py` | 125 |
| Commit gate | `test_commit_gate_branch_mapping.py` | 3 |
| Infrastructure | `test_module_registry.py`, `test_config.py`, `test_generic_adapter.py` | 77 |
| Features | `test_json_handler.py`, `test_rm.py`, `test_commands.py`, `test_scan.py` | 185 |
| Deletion record | `test_deletion_log.py` | 26 |
| Broker | `test_broker.py` | 60 |
| Standards | `test_cli_routing.py`, `test_contracts.py`, `test_error_resilience.py`, `test_init_provisioning.py`, `test_scaffold.py` | 93 |
| Help-flag safety | `test_help_flag_safety.py` | 36 |

Run tests: `cd src/aipass/drone && python -m pytest tests/ -q`

---

## Known Issues

- `pr_handler.py` is orphaned — `create_pr()` has no production caller (superseded by `dev_pr_handler.create_branch_pr()`); its 7 callers are all in `tests/test_git_module.py`
- `update_command()` and `command_exists()` in `ops.py` are tested CRUD API but unused from production
- Piping drone output into a truncating reader (`| head`) yields inconsistent exit codes (0, 1, or 243) — no BrokenPipe handling anywhere in the tree. Cosmetic, but blocks `drone ... | head` inside `set -e` scripts
- Several bypass rules in `.seedgo/bypass.json` are **line-scoped** and drift whenever code above them moves — adding a function to `drone.py` this session pushed four write sites down and dropped the audit to 99% until the rule was refreshed. The drift is a feature in one respect: it proves the rule is still load-bearing
- Pyright warns about `json` package name shadowing stdlib — works at runtime
- Recurring sync errors when working tree is dirty — operational, not code bugs

---

**Seedgo:** 100% | **Tests:** 1118 pass, 5 skip | **Last Updated:** 2026-08-14

---
[← Back to AIPass](../../../README.md)
