[← Back to AIPass](../../../README.md)

# Skills

**Purpose:** Capability framework for AI agents in AIPass. Skills are discoverable, validatable, and executable units of capability that any AI agent can use.
**Module:** `skills`
**Created:** 2026-03-07
**Last Updated:** 2026-09-12

---

## Quick Start

```bash
# List all available skills
drone @skills list

# Get details about a skill
drone @skills info telegram

# Run a skill
drone @skills run inbox_check

# Create a new skill
drone @skills create my-skill --with-handler

# Check if a skill's requirements are met
drone @skills validate telegram
```

## Overview

## Three Tiers

### 1. Markdown Only
A `SKILL.md` file with instructions. The AI reads the instructions and follows them. No code required.
```
my-skill/
  SKILL.md
```

### 2. With Handler
A `SKILL.md` plus a `handler.py` that the system can execute programmatically.
```
my-skill/
  SKILL.md
  handler.py
```

### 3. Full 3-Layer
A `SKILL.md` plus a full AIPass 3-layer app structure for complex skills.
```
my-skill/
  SKILL.md
  handler.py
  apps/
    __init__.py
    modules/
      __init__.py
    handlers/
      __init__.py
```

Built-in examples: `drone_commands` and `telegram` are full-tier; `github` is
markdown-only; the rest carry a `handler.py`.

## Creating a Skill

```bash
# Markdown only (default)
drone @skills create my-skill

# With handler
drone @skills create my-skill --with-handler

# Full 3-layer
drone @skills create my-skill --full
```

Skills are created in `.aipass/skills/` in the current project directory.

## Running a Skill

```bash
# Run a handler-based skill
drone @skills run my-skill action-name key=value

# Run a markdown skill (displays instructions)
drone @skills run my-skill

# List all available skills
drone @skills list

# Get details about a skill
drone @skills info my-skill

# Check requirements
drone @skills validate my-skill
```

## The Off-Switch

A skill can be disconnected from AIPass and reconnected later. The setting
persists across restarts and reboots (`skills_json/switch_state.json`).

```bash
drone @skills off telegram "retired 2026-08-18"   # disconnect
drone @skills switch                              # who is on, who is off
drone @skills on telegram                         # reconnect
```

**OFF** means three things, not one:

1. Every systemd user unit the skill declares is **stopped**.
2. Those units are **disabled and masked**, so nothing can respawn them — not a
   manual `systemctl start`, not a dependency, not a script.
3. `drone @skills run <name>` **refuses**, before the skill's handler is
   imported. Stopping units only quiets the machine; this is what makes the
   skill dark.

**ON** reverses all three: unmask, enable, start. A unit that does not come back
is reported rather than assumed — the switch never prints "dark" over a live
process, or "running" over a dead one.

A skill declares what belongs to it in its own SKILL.md frontmatter:

```yaml
switch:
  systemd_user:
    - telegram-bot@base
```

A skill that declares nothing still toggles; it simply owns no processes to
stop. If `switch_state.json` is ever unreadable, skills **refuse to run** rather
than defaulting to on — defaulting to on would restart exactly what someone
deliberately switched off. Design record: `DPLAN-0306`.

## SKILL.md Format

```yaml
---
name: skill-name
description: One-line description
version: 1.0.0
tags: [category1, category2]
when_to_use:              # Trigger phrases — when an agent should reach for this
  - phrase
requires:
  pip: []        # Python packages needed
  bins: []       # CLI tools needed
  config: []     # Env vars / config keys needed
has_handler: false
switch:                   # Optional — what the off-switch owns (see above)
  systemd_user: []
---
# Skill Name

## What This Does
...

## Steps
...
```

## Search Paths

Skills are discovered in this order (first match wins for same name):

1. **Project**: `.aipass/skills/` in the current working directory
2. **Global**: `~/.aipass/skills/` in the user's home directory
3. **Built-in**: `src/aipass/skills/lib/` in the AIPass codebase

## Commands / Usage

```bash
drone @skills list                         # Show all discovered skills
drone @skills info <name>                  # Display SKILL.md contents
drone @skills run <name> [action] [args]   # Execute a skill's handler
drone @skills create <name>                # Scaffold new skill (markdown only)
drone @skills create <name> --with-handler # Scaffold with handler.py
drone @skills create <name> --full         # Scaffold with full 3-layer structure
drone @skills validate <name>              # Check if skill requirements are met
drone @skills on <name>                    # Reconnect a skill and start its processes
drone @skills off <name> [reason]          # Disconnect a skill and stop its processes
drone @skills switch [name]                # Show each skill's on/off state
drone @skills --help                       # Show help
drone @skills --version, -V                # Show version
```

Every command above was run against this branch on 2026-09-05 and matches
`drone @skills --help`.

---

## Directory Structure

```
src/aipass/skills/
  apps/
    skills.py              # Entry point (handle_command)
    modules/
      discovery.py         # Find skills across search paths
      loader.py            # Load SKILL.md + handlers
      runner.py            # Execute skills
      creator.py           # Scaffold new skills
      validator.py         # Check skill requirements
      switch.py            # Per-skill off-switch (on / off / switch)
    handlers/
      json/                # json_handler.py — the fleet shim (see The JSON Handler)
      discovery_handler.py # Search paths, SKILL.md scanning, frontmatter parsing
      module_paths.py      # Dead-cwd-safe module location (stdlib only)
      loader_handler.py    # Full SKILL.md parse, dynamic handler import
      runner_handler.py    # Handler dispatch + markdown-only output
      creator_handler.py   # Skill creation logic (name validation, orchestration)
      switch_handler.py    # Off-switch state, declaration parsing, systemd actuation
      registry.py          # Skill registry management
      validator.py         # Check requirements
      template.py          # Skill templates
    integrations/          # External integration point (empty)
    plugins/               # Plugin extensions (empty)
  lib/                     # Built-in skills (branch_health, drone_commands, github, inbox_check, screen_lock, system_status, telegram)
  templates/               # Skill creation templates (markdown_only, with_handler, full)
  skills_json/             # JSON tracking directory (incl. switch_state.json)
  dropbox/                 # External storage sync
  docs/                    # Branch documentation
  tools/                   # Branch tooling (verify_branch.py, suspend grants)
  artifacts/               # Birth certificate and branch artifacts
  logs/                    # prax log output
  .trinity/                # Branch identity and memory
  tests/                   # Branch suite: 297 test functions in 13 files
                           #   (pytest expands to 302 cases)
```

Counted 2026-09-12. That 297 is the branch suite alone — the figure the seedgo
readme rule checks, `def test_` under `tests/`.

Two skills carry suites of their own: `lib/telegram/tests/` is 28 files holding
1103 `def test_` functions expanding to 1114 cases, and `lib/screen_lock/tests/`
adds 22. All three together run 1438 passing, 0 skipped — the same number from
the branch root (`pytest .`) and from the repo root.

---

## The JSON Handler

`apps/handlers/json/json_handler.py` is **not an implementation**. Since
DPLAN-0325 (landed 2026-09-03) it is the fleet's canonical shim: 1724 bytes,
byte-identical in all eighteen branches, sha256
`3456b7660698fa9d2a1f9352523f3a0aa75c3d862bcf6222ce4be280513cf0b7`. seedgo
checks it by hash, so nothing branch-specific may be added to it.

It **binds** the one json service — `aipass.prax.json_handler`, owned by @prax —
and adds nothing. Binding rather than wrapping is load-bearing: the service
names the calling module from frame 2, so a wrapper would attribute every entry
this branch logs to the wrapper's own file.

```python
from aipass.skills.apps.handlers.json import json_handler

json_handler.log_operation("skill_executed", {"name": name})
```

Consequences worth knowing before you touch it:

- **There is no `SKILLS_JSON_DIR` and no `atomic_write_json`.** Both retired
  with the old handler. Code that needs this branch's json directory asks the
  service — `json_handler.get_json_path(module, json_type).parent` — which
  recomputes it per call rather than capturing it at import.
- **Tests redirect with `AIPASS_TEST_LOG_DIR`, never by patching an attribute.**
  The shim has no attributes to patch, and that is the point. Both conftests set
  the seam; the autouse `mock_infrastructure` fixture scopes it per test.
- The retired handler is kept at `apps/handlers/json/.archive/` as the record.
  Nothing imports out of `.archive/`.

## Running Where The Working Directory Is Gone

Every skills module imports without a readable current directory.

`ntpath.realpath` calls `os.getcwd()` on its first lines **unconditionally** —
before it checks whether the path is even relative. `posixpath.realpath` reads
the cwd only for relative paths, which is why this stayed invisible on Linux.
`Path.resolve()` routes through realpath, so on Windows any
`Path(__file__).resolve()` *reached at import* is an import-time crash for a
process whose directory was deleted or whose network share dropped. Not
"degrades" — cannot import.

This matters more here than in most branches: skill units run in host processes
nobody in this branch chose — the telegram relay, cron-fired lanes, hook
subprocesses — and those are exactly the processes likely to hold a dead or
foreign working directory.

Every module-level location goes through one helper:

```python
from aipass.skills.apps.handlers.module_paths import module_file

_BRANCH_ROOT = module_file(__file__).parents[3]
```

`module_file()` is **stdlib-only on purpose**: importing prax would put the
logger's own construction — which reads the cwd — onto the very path the helper
protects. When resolve fails it reports once per path on stderr and returns the
unresolved absolute spelling, which loses symlink normalisation and nothing
else.

Two sites guard themselves inline instead, because they run where the helper
cannot be imported: `apps/skills.py` (the block runs *before* any aipass import
by design, removing the shadowing path that would resolve `aipass`) and
`tools/verify_branch.py` (ships inside spawn's agent template, where `aipass`
is not importable at all).

The handlers guard walks frames with `sys._getframe` rather than
`inspect.stack()`. inspect materialises a FrameInfo per frame, and
`getmodule()` calls `os.path.realpath` at `inspect.py:1009` outside any try —
so the guard needed a readable cwd before a single line of its own code ran,
and every module in this branch imports through it.

The worlds themselves are defined once, in `tests/dead_cwd_world.py`. They
patch pathlib's pre-3.11 `_NormalAccessor` as well as the module name: that
accessor **captured** its copies of `os.getcwd` and `os.path.realpath` when
pathlib was first imported, so on Python 3.10 a bare module rebind patches a
name nothing reads again and the world never arms. Two of these pins were
vacuously green on the 3.10 CI leg for exactly that reason. There is no 3.10 on
this machine, so the capture is rebuilt locally on whatever interpreter is
running and the discrimination is falsifiable here rather than derived.

That rebuilt accessor captures a **sentinel** for realpath, not the host's.
An instrument must not import behaviour it is not testing: the question it
asks is "did the patch reach the captured attribute", and a live capture makes
the answer depend on the dialect — on nt the accessor reads the cwd on its own
account, so a world that reached nothing still answers *raised* and the probe
convicts the host. The same file carries `posixpath`- and `ntpath`-shaped
realpaths written **by name and by behaviour**, never by aliasing the dialect's
own `realpath` (off Windows `ntpath.realpath` is a wrapper around `abspath` and
leaves an absolute path alone, so an nt world built by aliasing never arms).
Every accessor pin runs under both dialects and must return the same verdict;
one shape that is *supposed* to differ is held alongside them, so a litmus that
reached nothing cannot pass quietly. Where a claim really is per-platform — a
relative arming path raises in both dialects, an absolute one only on nt — it
is written as a two-row table with both rows measured here and a pin requiring
the live host to agree with its own row.

Pinned by `tests/test_dead_cwd_imports.py`, which imports every skills module
in a child process under two denial worlds (deny `getcwd`; deny `realpath`),
plus a healthy baseline. Both worlds carry a control proving the world is live,
and a control proving that control can say no.

Two runtime paths are covered there too, because skill units resolve them in
those same host processes: skill **discovery** drops the project search path
when there is no current directory and keeps serving global and builtin skills,
while skill **creation** refuses outright — it writes, and a target that cannot
be computed must not be guessed at.

---

## The system_status Skill Off Linux

`lib/system_status/handler.py` asked `/proc` three times — `meminfo`, `uptime`
and the process table — so on the macOS runner `memory`, `uptime` and
`processes` each answered `success: False` every run, and `summary` reported
`success: True` over a disk line plus an Errors trailer (FPLAN-0554, runs
34704362515 and 34707099650). The four cases in `tests/test_runner.py` carried
`skipif(sys.platform == "win32")`, a guard that named the one platform that was
never the problem.

All three now ask **psutil** — `virtual_memory()`, `boot_time()`, `pids()` —
which is a declared dependency of this project (`psutil>=5.9`) and answers on
Linux, macOS and Windows. Disk was always portable (`shutil.disk_usage`) and is
untouched. Two things that are not obvious:

- **`summary` fails when a section fails.** It returns `success: False` with
  `error` naming the missing sections, and still hands back the sections that
  did answer. The old shape put the failures in an `Errors:` trailer inside
  `output` and kept `success: True`, which is a caller reading a disk line as a
  system report.
- **No psutil means a refusal, not a partial.** The three actions return
  `success: False` naming the install recipe; `disk` still answers.

The macOS half is manufactured on this Linux box in `tests/test_runner.py`, and
the psutil stand-in is part of the world rather than a shortcut around it:
psutil's *Linux* backend reads `/proc` through plain `open()`, so denying
`/proc` with the real psutil in place would have manufactured a failure no Mac
can have — there psutil answers from the kernel. The world is
`sys.platform == "darwin"` + every `/proc` read refused + a stand-in shaped like
macOS's `virtual_memory` (no `buffers`, no `cached`), with three controls: the
denial is live, the denial can still say yes, and the process table is gone too.
Against the pre-cure handler 11 of these cases go red on behaviour; 8 mutants
were killed.

**Why the audit read 100 over it.** At the time the audit corpus was `apps/`
(plus `tests/` for the branch-level arms) and never entered `lib/`, where all
seven built-in skills live — so `Host_Portability` read **100** while the skill
was red on every macOS run. Reported the same morning; @seedgo ruled that `lib/`
joins the corpus **for `host_portability` only** (the per-file audit stays
`apps/`, so tier-2 `handler.py` files are not scored for architecture). The
widened rule scored this branch 97 — see the next section.

## The Telegram Skill On A Host Without tmux Or systemd

When `host_portability` started reading `lib/` it found 12 calls in the telegram
skill running `tmux` or `systemctl` with no probe and no `FileNotFoundError`
handler (`base_bot.py` 7, `bot_factory.py` 3, `tmux_manager.py` 2). A missing
binary raises out of exec, before there is a return code to check. One of them
was a real escape, not a technicality: `tmux_manager.session_exists` is called
**above** the `try` in `send_message`, `kill_session` and `get_session_pane`, so
their own `except Exception` never saw it and all three raised on a host without
tmux.

Every call site now catches the exec failure where it sits and returns a
verdict:

- `session_exists` answers False, so `kill_session` has nothing to kill,
  `get_session_pane` is None and `send_message` is False. `_send_rename` logs.
- `inject_message` and `_kill_tmux_session` return False.
- `/start` and `/kill` reply `tmux not found on this machine.` — the same words
  the has-session probe above them already used.
- `launch_mirror_session` returns False when tmux is gone at `new-session` or at
  either `send-keys`. A session nobody typed into is not a mirror session, and
  the old code would have returned True over it.
- `/suspend` on a host with no `systemctl` disarms the alarm it armed and says
  `systemctl is not installed on this host.` The polkit advice cannot work
  there. A suspend that systemd *refused* still gets the polkit text,
  byte-identical.

No `shutil.which` probe was added. Every unit that exercises these functions
mocks `subprocess.run`; a probe beside the call would make those units measure
the runner's package list, which is the defect @api cured in `3ef3d571`.
Catching at the call is driven by the same mock the units already hold.

Pinned by 13 cases across five existing telegram test files. All 13 fail against
the pre-cure handlers, and 11 mutants — one per clause, plus the mirror session
claiming success and the suspend message reverting to polkit — all go red.

The skill is still switched **OFF** (since 2026-08-18), so nothing live changed.
Its three `/proc` reads in `base_bot.py` are not scored: each sits inside
`except OSError` and degrades honestly. One is still worth knowing as behaviour —
the bot-lock check guards its `/proc/<pid>/cmdline` read with
`sys.platform != "win32"`, so on macOS the PID-reuse verification is silently
skipped and the lock trusts liveness alone. That waits for a switch-on plan.

---

## Integration Points

### Depends On
- **@prax** — a hard dependency, two ways: `from aipass.prax import logger` is
  the only logging system, and the json shim binds `aipass.prax.json_handler`
  (see The JSON Handler). Both are reached through prax's entry point, never
  through its internals.
- Python stdlib, as imported across `apps/` on 2026-09-05: `datetime`,
  `importlib`, `json`, `linecache`, `os`, `pathlib`, `shutil`, `subprocess`,
  `sys`, `tempfile`, `time`, `typing`
- PyYAML — **optional**. Frontmatter is parsed with `yaml` when importable;
  otherwise a built-in fallback parser handles it (`discovery_handler.py`)
- `systemctl --user` — only for the off-switch, and only for skills that
  declare units
- Filesystem: reads SKILL.md files from project, global, and built-in search paths

### Provides To
- All modules — skill discovery, loading, validation, and execution
- AI agents — discoverable capability units via `drone @skills`
- Projects — local skill scaffolding via `drone @skills create`

---

## Status / Known issues

Everything below was measured on this branch on 2026-09-07. Anything this
branch could not exercise is marked unverified rather than left standing green.

**Working, exercised tonight:** `list`, `info`, `validate`, `switch`, `run`,
`--help`, `--version`. The off-switch's three doors were exercised, not just
read: `drone @skills run telegram` refuses with the OFF message while the units
stay masked. Suite 1438 passing, 0 skipped, identical from the branch root and
the repo root. seedgo audit 100 on every CI-scored category.

**Unverified — the telegram skill's runtime.** The skill is discovered, listed
and gated correctly, and its own 1114-case suite passes. Its *live* behaviour
was not exercised: it has been switched OFF since 2026-08-18 (Patrick's ruling,
DPLAN-0305 — five bots leaked ~2.3GB each), and `drone @skills validate
telegram` reports its `telethon` dependency missing on this machine. Nothing in
this README claims its runtime works today.

**Known issue — one bypass carried, not a clean 100.**
`.seedgo/bypass.json` waives `json_structure` for
`apps/handlers/module_paths.py`. That helper is stdlib-only on purpose and must
never import the json seam; seedgo's `_is_prelogging_bootstrap` used to exempt
it automatically, because the exemption is granted to whatever the logging
substrate imports and the *old* json_handler imported it. The canonical shim
imports nothing branch-local, so the chain now stops at the shim and the
exemption lapsed. skills is the only branch in the fleet carrying a
`module_paths.py`, so no other branch is affected. The bypass carries the full
measurement and comes out when seedgo's clause learns a module-scope importer.

**Closed 2026-09-06 — the CI hang.** On 2026-09-04 the Linux 3.10 leg stalled
inside `lib/telegram/tests/test_suspend.py` and was cancelled at the 30-minute
cap; the same leg had passed in 8 minutes an hour earlier. Cause: those tests
patched `base_bot.time.time`, and because `base_bot.time` *is* the stdlib
`time` module, the fake clock was process-global. It returns epoch 1000.0, so
any deadline another thread captured beforehand read ~56 years away and that
thread waited forever. Cured with a seam — `from time import time as _now` —
and all 32 wall-clock reads in `base_bot.py` moved onto it, so the 23 test
patch sites now reach one module and nothing else.

**Known issue — five deployed bots still keep config in the secret store.**
Since 2026-09-07 only the token is written there (`config.SECRET_FIELDS`), but
the bots created before that carry all ten keys in their secret document. They
load and run, and warn by name on every load. `drone @skills run telegram
migrate-config` reports what would move — measured 2026-09-07: api 6 keys, base
6, devpulse 7, prax_monitor 5, scheduler 6, and `telethon_config` correctly
untouched because api_id/api_hash are real secrets. `--apply` splits them for
real. Not run here: rewriting a live credential store is Patrick's call, not a
headless session's.

---

*Last Updated: 2026-09-12*

---
[← Back to AIPass](../../../README.md)