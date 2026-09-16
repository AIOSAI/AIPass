# Routing and resolution

**Branch** drone · **Code** `apps/drone.py`, `apps/modules/` (resolver, router, config, registry,
discovery, module_registry, commands, scan), `apps/handlers/executor.py`,
`apps/handlers/router_handler.py`, `apps/handlers/registry_handler.py`,
`apps/handlers/generic_adapter.py`, `apps/handlers/help_flags.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

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
registry path that escapes the project root, and the old fallback answered that security refusal by
quietly running the module instead.

One fallback deliberately survives, and only in the **custom-command** lane
(`_handle_custom_command()` in `apps/drone.py`): a registered shortcut whose target is a module but
not a branch here falls back to module routing, logged at INFO. That lane resolves its target from
`drone_command_registry.json` rather than from the argv, so the look-before-route check the
`@target` lane uses does not apply to it. Unverified whether it should — it has never been measured
for happy-path firing the way `@git status` was.

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

`git` is a module and **never** a branch. `drone @git status` matched the interactive tuple,
skipped the module fast path, and raised `BranchNotFoundError` on every call by design — a fallback
firing on the **happy path**, which is worse than one firing on failure because it trains everyone
to ignore the channel it fires on. It dominated `system_logs/drone_drone.log`, burying the one real
WARNING in there (DPLAN-0315, the owner's ruling: *"there should be no fallback full stop... if our
intended action or process fail, it fail loud"*). The target is now checked for a branch before the
interactive lane is taken, and the cure held on re-measurement.

**Always interactive** — presentational shapes that inherit the terminal for Rich color on a TTY,
plain when piped: bare `@branch` (no-args introspection), `@branch --help`, `@branch -h`.

**Per-command allowlist** (`INTERACTIVE_COMMANDS` in `apps/drone.py`): `monitor` (prax live TUI),
`audit` (seedgo progress bars), `watchdog` (devpulse live monitoring), `status` (Rich formatting).

**Per-branch allowlist** (`INTERACTIVE_BRANCHES`): `cli` (user-facing Rich output) and `backup`
(snapshot/restore progress needs a live terminal). To add one, edit either tuple in `apps/drone.py`.

---

## Help flags — explain, never execute

A help flag **anywhere** in a command means explain, never execute (DPLAN-0291 rule E). Every
module's `handle_command()` calls `wants_help()` from `apps/handlers/help_flags.py` before
dispatching:

- `--help` / `-h` — exact match, honoured in **any** position, including the subcommand slot
- bare `help` — position 0 only, since later positions are legitimate values (a path to delete, a
  branch to look up)

Modules that own `help` as a real verb pass `bare_help=False`; `discovery` does, so
`drone @discovery help @seedgo` keeps working while `... help @seedgo --help` still explains.

The check lives **inside** each `handle_command()`, not in the router, because every module also
has a standalone `__main__` path that takes raw argv and never touches the router. One predicate,
many call sites — the gate previously existed as copies of the same two lines, which is how a group
of modules drifted into the same bug at once.

Why it mattered: the old gate read only `command` or `args[0]`, so `drone rm notes.md --help`
**deleted notes.md** and then tried to delete a file named `--help`.
`tests/test_help_flag_safety.py` mocks every dispatch target and asserts it was never called — no
live verb is fired to prove the trap.

---

## The Python API

```python
from aipass.drone import resolve_branch, list_branches, route_command

path = resolve_branch("@seedgo")

active = list_branches()                      # status defaults to "active" — the default IS a filter
by_type = list_branches(branch_type="core")   # empty today — see below

result = route_command("@seedgo", "audit", args=["aipass", "@drone"])
print(result.stdout)
print(result.exit_code)
```

`list_branches()` returns more rows than `AIPASS_REGISTRY.json` holds: `get_all_branches()` merges
the primary registry with the external tier declared in `AIPASS_ROOTS.json`. `list_branches(
branch_type=...)` is a live parameter with nothing to match — no row carries a type field, so the
type filter always returns `[]`, and any status but `active` returns `[]` too. One precision the
earlier wording missed: the filter reads `branch.get("type")`, not `branch_type`, so it names a key
no code reads. Documented as it behaves, not as it reads.

### Registry path resolution

```python
from aipass.drone import set_registry_path, get_registry_path, reset_registry_path

set_registry_path("/path/to/AIPASS_REGISTRY.json")
reset_registry_path()
```

Order (`get_registry_path()` → `find_registry()`): explicit `set_registry_path()` →
**`AIPASS_REGISTRY`** env var → walk up from cwd, skipping any registry whose `metadata.id`
conflicts with the nearest passport's `citizenship.registry_id` → `AIPASS_HOME` → walk up from the
drone package → package-relative default. The env var is `AIPASS_REGISTRY`, not
`AIPASS_REGISTRY_PATH` — the latter name appeared in the README until 2026-08-25 and was never read
by any code.

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

- **Dual registry lookup.** `registry_handler.py` merges the local project registry with the
  `AIPASS_HOME` registry. Local entries win on a name collision.
- **Module routing, not a fallback.** An external seat reaches those modules because `is_module()`
  is checked *before* any branch call — the module lane is chosen, not discovered by failing the
  branch lane. Rich output from AIPass, functional output from external projects.
- **`AIPASS_HOME` hints.** When it is not set and the local registry lacks core branches, drone
  prints a one-line tip naming the variable.

---

## Related

- [caller_identity.md](caller_identity.md) — who a routed command is attributed to
- [subprocess_timeouts.md](subprocess_timeouts.md) — the executor's deadline ladder
- [git_access.md](git_access.md) — the tier gate every git verb passes
