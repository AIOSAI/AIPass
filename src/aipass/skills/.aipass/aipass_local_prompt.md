# SKILLS — Branch Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/skills/.aipass/aipass_local_prompt.md — Injected on every prompt when in skills directory. -->

Capability framework: discoverable, validatable, executable skill units in three tiers — markdown only, markdown plus `handler.py`, or a full three-layer app. The face for strangers is `README.md`; depth lives in `docs/`.

# Reaching the branch

 - `drone @skills` — live self-map of the modules wired to the entry point.
 - `drone @skills --help` — the reference: every verb and flag, search paths, examples. Never retype it into a page.
 - Verbs: `list`, `info`, `run`, `create`, `validate`, `on`, `off`, `switch`.

# Tree

```
apps/
  skills.py                entry point, routes a verb to a module
  modules/                 discovery loader runner creator validator switch
  handlers/                discovery_handler loader_handler runner_handler creator_handler
                           switch_handler registry template validator
                           module_paths (dead-cwd-safe location, stdlib only)
                           json/ (the fleet shim, binds prax's json service)
  integrations/            empty
  plugins/                 empty
  .archive/                retired code, imported by nothing
lib/                       built-in skills, one directory each:
                           branch_health drone_commands github inbox_check
                           screen_lock system_status telegram
templates/                 markdown_only with_handler full
tests/                     branch suite, plus dead_cwd_world.py (the denial worlds)
docs/                      tracked pages, every one linked from README.md
tools/                     verify_branch.py, suspend/
skills_json/               switch_state.json and per-module operation logs
.aipass/skills/            project-local skills for THIS project
.seedgo/bypass.json        one carried waiver, measured in docs/known_issues.md
```

Two skills carry their own suites: `lib/telegram/tests/` and `lib/screen_lock/tests/`.

# Search paths

First match for a name wins, so a project shadows a built-in without editing it.

 - `.aipass/skills/` — project-local, resolved against the current directory.
 - `~/.aipass/skills/` — the user's global skills.
 - `lib/` — the built-ins that ship with AIPass.

# Gotchas

 - Counting the suite: bare `pytest` here collects `tests/` only. The skill suites join under `pytest .` or from the repo root — that is the figure to quote.
 - Telegram is retired: switched off, left in place, every test under `lib/telegram/tests/` skipped at collection and never fixed. A failing telegram test gets disabled, not repaired. See `docs/telegram.md`.
 - The off-switch gates the runner, not an import. Any function published for in-process use must consult the switch itself — `machine_vitals()` does, and the telegram notifier does now because it was still sending after the skill went dark.
 - No module-level `Path(__file__).resolve()`. Use `module_paths.module_file()`: on Windows `realpath` reads the working directory unconditionally, so a dead cwd is an import-time crash. See `docs/dead_cwd.md`.
 - `apps/handlers/json/json_handler.py` is a hash-checked fleet shim. Add nothing to it; ask the service for a path instead of capturing one at import.
 - Tests redirect json and log output with `AIPASS_TEST_LOG_DIR`, never by patching a shim attribute.
 - `host_portability` is the one audit rule whose corpus includes `lib/`; the per-file rows still read `apps/` only, so a green audit is not a sweep of the skills.
 - A skill that declares systemd units owns them through `switch`; stopping units without recording the switch leaves the runner willing to start the skill in-process.

# Memory

 - `.trinity/passport.json` — identity.
 - `.trinity/local.json` — sessions, key learnings, todo pad.
 - `.trinity/observations.json` — how the user works.
