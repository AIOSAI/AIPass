[<- Back to the README](../README.md)

# Routing and resolution

**Branch** drone · **Code** `apps/drone.py`, `apps/modules/` (resolver, router, config, registry,
discovery, module_registry, commands, scan), `apps/handlers/executor.py`,
`apps/handlers/router_handler.py`, `apps/handlers/registry_handler.py`,
`apps/handlers/generic_adapter.py`, `apps/handlers/help_flags.py`

How an argument list becomes a running command. The verbs themselves are in `drone --help`;
the bare `drone @drone` prints the live module inventory.

---

## The routing decision tree

1. **CLI input** → `drone.py:main()`
2. **Built-in commands** checked first: `systems`, `scan`, `activate`, `list`, `remove`, `rm`
3. **`@target` routing** → branch resolution via `AIPASS_REGISTRY.json` → subprocess dispatch
4. **Module routing** → a registered module that is not a branch here is routed internally,
   **decided before any branch call** (`branch_exists()`), never discovered by failing one
5. **Bare module names** → auto-discovered from `apps/modules/*.py`, routed via `importlib`
6. **Custom commands** → greedy multi-word matching against `drone_command_registry.json`

The `@target` lane has **no module fallback on the error path.** A `BranchNotFoundError` from a
branch the registry *does* list is a real fault and fails loud — `resolve_branch()` also refuses a
registry path that escapes the project root, and a fallback would answer that security refusal by
quietly running the module instead.

One fallback deliberately survives, and only in the **custom-command** lane
(`_handle_custom_command()` in `apps/drone.py`): a registered shortcut whose target is a module but
not a branch here falls back to module routing, logged at INFO. That lane resolves its target from
`drone_command_registry.json` rather than from the argv, so the look-before-route check the
`@target` lane uses does not apply to it. Whether it fires on a happy path is unmeasured.

---

## Two kinds of module

| Type | Modules | Routing |
|------|---------|---------|
| Internal | `git` | `importlib` import → `handle_command()` |
| External | `seedgo`, `cli`, `spawn` | `generic_adapter.capture_main()` via `routing_config.json` |

External modules are declared in `apps/handlers/routing_config.json` with entry points,
descriptions and versions.

---

## Interactive commands — who inherits the terminal

By default drone captures subprocess output (both pipes, drained concurrently) with the resolved
timeout (see [subprocess_timeouts.md](subprocess_timeouts.md)). That is safe for AI-to-AI routing
but strips Rich colors, buffers progress bars, and kills long-running commands. Commands in the
interactive tuple bypass capture and inherit the terminal directly — live Rich output, colors, no
timeout.

**Interactive mode is a property of BRANCH (subprocess) routing only.** It means "inherit the
terminal instead of capturing the subprocess", and `_handle_module()` runs in-process and takes no
interactive parameter — so a module target never receives it and never could. `@seedgo`, `@cli` and
`@spawn` are both module and branch, so an interactive command against them takes the subprocess
lane and renders live.

`git` is a module and **never** a branch, so the target is checked for a branch before the
interactive lane is taken: `drone @git status` matches the interactive tuple and still takes the
module lane. There is no fallback: an intended action that fails, fails loud. A fallback firing on
the **happy path** is worse than one firing on failure, because it trains everyone to ignore the
channel it fires on.

**Always interactive** — presentational shapes that inherit the terminal for Rich color on a TTY,
plain when piped: bare `@branch` (no-args introspection), `@branch --help`, `@branch -h`.

**Per-command allowlist** (`INTERACTIVE_COMMANDS` in `apps/drone.py`): `monitor` (prax live TUI),
`audit` (seedgo progress bars), `watchdog` (devpulse live monitoring), `status` (Rich formatting).

**Per-branch allowlist** (`INTERACTIVE_BRANCHES`): `cli` (user-facing Rich output) and `backup`
(snapshot/restore progress needs a live terminal). To add one, edit either tuple in `apps/drone.py`.

---

## Help flags — explain, never execute

A help flag **anywhere** in a command means explain, never execute. Every
module's `handle_command()` calls `wants_help()` from `apps/handlers/help_flags.py` before
dispatching:

- `--help` / `-h` — exact match, honoured in **any** position, including the subcommand slot
- bare `help` — position 0 only, since later positions are legitimate values (a path to delete, a
  branch to look up)

Modules that own `help` as a real verb pass `bare_help=False`; `discovery` does, so
`drone @discovery help @seedgo` keeps working while `... help @seedgo --help` still explains.

The check lives **inside** each `handle_command()`, not in the router, because every module also
has a standalone `__main__` path that takes raw argv and never touches the router. One predicate,
many call sites: copies of the same two lines drift together. A gate that read only `command` or
`args[0]` would let `drone rm notes.md --help` delete `notes.md`.
`tests/test_help_flag_safety.py` mocks every dispatch target and asserts it was never called — no
live verb is fired to prove the trap.

---

## The Python API

```python
from aipass.drone import resolve_branch, list_branches, route_command

path = resolve_branch("@seedgo")

active = list_branches()                      # status defaults to "active" — the default IS a filter
by_type = list_branches(branch_type="core")   # empty: no row carries a type — see below

result = route_command("@seedgo", "audit", args=["aipass", "@drone"])
print(result.stdout)
print(result.exit_code)
```

`list_branches()` returns more rows than `AIPASS_REGISTRY.json` holds: `get_all_branches()` merges
the primary registry with the external tier declared in `AIPASS_ROOTS.json`. `list_branches(
branch_type=...)` is a live parameter with nothing to match — no row carries a type field, so the
type filter always returns `[]`, and any status but `active` returns `[]` too. The filter reads the
row key `type` (`branch.get("type")`), which no registry row carries.

### Registry path resolution

```python
from aipass.drone import set_registry_path, get_registry_path, reset_registry_path

set_registry_path("/path/to/AIPASS_REGISTRY.json")
reset_registry_path()
```

Order (`get_registry_path()` → `find_registry()`): explicit `set_registry_path()` →
**`AIPASS_REGISTRY`** env var → walk up from cwd, skipping any registry whose `metadata.id`
conflicts with the nearest passport's `citizenship.registry_id` → the AIPass home (below) → walk up
from the drone package → package-relative default. The env var is `AIPASS_REGISTRY`;
`AIPASS_REGISTRY_PATH` is read by no code.

### Error handling

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

The hierarchy lives in `apps/handlers/exceptions.py`.

---

## External projects

Infrastructure modules (`seedgo`, `cli`, `git`, `spawn`) work from external AIPass projects without
per-project registration.

- **Dual registry lookup.** `registry_handler.py` merges the local project registry with the AIPass
  home's registry. Local entries win on a name collision.
- **The AIPass home, without `AIPASS_HOME`.** `resolve_aipass_home()` is the one answer every
  reader asks, first answer wins:
  1. `AIPASS_HOME` set: used as given, because an explicit setting beats a guess.
  2. The interpreter's own install: `Path(sys.prefix).parent`, when it holds an
     `AIPASS_REGISTRY.json`. The installed `drone` runs on `<home>/.venv/bin/python3`, so this
     answers for every setup.sh or `aipass install` install. A system Python or a tool venv fails
     the check and falls through.
  3. The homes enrolled in `~/.aipass/trusted_projects.json`: only projects holding an
     `AIPASS_REGISTRY.json` count, and the newest `enrolled` wins.

  So a terminal opened before setup.sh wrote `AIPASS_HOME` into the shell rc still finds the home.
  Pinned by `TestAipassHomeResolution` in `tests/test_registry_handler.py`.
- **The home's own interpreter.** `branch_interpreter(branch_path)` answers which python runs a
  branch app. Every launch site asks it: `router_handler.execute_branch_command`, and the `--help`
  runs in `discovery_handler` (`discover_modules`, `get_help`) and `scanning/scanner`.
  - A branch outside the resolved home, or no home at all: `sys.executable`.
  - The home is `Path(sys.prefix).parent`, so this drone is the home's: `sys.executable`.
  - Otherwise, the home's `.venv/bin/python` (`.venv/Scripts/python.exe` on Windows), logged
    INFO once per home.
  - No venv there: `sys.executable`, with one WARNING naming the half-installed home.

  A machine can hold aipass twice. The uv tool venv's `drone` comes first on PATH, and the home's
  apps, run on that venv's python, would import their handlers from the tool's site-packages. The
  handlers fence would refuse them. Pinned by
  `TestBranchInterpreter`, and at the launch sites in `test_router.py`, `test_discovery.py` and
  `test_scan.py`.
- **Module routing, not a fallback.** An external seat reaches those modules because `is_module()`
  is checked *before* any branch call — the module lane is chosen, not discovered by failing the
  branch lane. Rich output from AIPass, functional output from external projects.
- **The home tip.** It fires under "Branch not found" only when all three sources failed, and it
  names what was tried, so a person can act on it: the unset variable, the interpreter's directory
  with no registry, and the enrolment file (missing, unreadable, or enrolling no home). `drone
  systems` keeps its `export AIPASS_HOME` hint on the same condition.

---

## Related

- [caller_identity.md](caller_identity.md) — who a routed command is attributed to
- [subprocess_timeouts.md](subprocess_timeouts.md) — the executor's deadline ladder
- [git_access.md](git_access.md) — the tier gate every git verb passes
