[← Back to AIPass](../../../README.md)

# SKILLS

**Purpose:** Capability framework for AI agents. A skill is a self-contained unit of capability — instructions an agent reads, and optionally code it can execute — discovered, validated and run the same way wherever it lives.
**Module:** `skills`
**Created:** 2026-03-07

---

## Quick Start

```bash
drone @skills list                        # every skill this machine can see
drone @skills info system_status          # what a skill is, and how to call it
drone @skills run system_status summary   # run one
drone @skills create my-skill --full      # scaffold your own
```

## What It Does

A skill comes in one of three tiers, and the tier is simply how much of it is
code. The smallest is a `SKILL.md` file alone: frontmatter describing the skill
and a body of instructions an agent reads and follows. Add a `handler.py` and
the same skill becomes executable — the runner imports it and dispatches an
action. Add a full three-layer app beside it and a skill is an application in
its own right, which is what the shipped Telegram bridge is.

Skills are found by scanning three search paths in order — the project's own
`.aipass/skills/`, the user's global `~/.aipass/skills/`, then the built-ins
under `lib/` — and the first match for a name wins, so a project can shadow a
built-in without editing it. Before running anything, a skill can be asked
whether its requirements are actually met on this machine: Python packages,
binaries on PATH, config keys. Each skill also has an off-switch that survives a
reboot; switching one off stops the processes it declares, blocks their respawn,
and makes the runner refuse to start it.

The skills that ship with AIPass live in `lib/`: branch health, drone command
reference, GitHub, inbox check, screen lock, system status and the retired
Telegram bridge.

## Live Inventory

`drone @skills` prints the live self-map — the modules wired to the entry point.
`drone @skills --help` is the reference: every verb and flag, the search paths,
and worked examples. Both are produced by the code itself, so neither can drift
from what the branch actually does.

## How To Reach Me

- Mail: `drone @ai_mail email @skills "Subject" "Body"` for a question, `drone @ai_mail dispatch @skills "Subject" "Body"` when the branch must act. A sleeping agent never reads plain mail.
- **A skill that reports its requirements met but fails to run, or an off-switch that does not stop what it declares, is a defect here, not a fault in your branch.** Say which skill, which tier, and which search path it was found under.
- Owner rulings and architecture questions go to @devpulse, not here.

## Commands

The verb list is deliberately not copied into this file. A hand-typed list rots
the day a flag changes, and this branch already prints an authoritative one — see
Live Inventory above, and ask the branch itself.

## Architecture

The entry point `apps/skills.py` does nothing but route: it hands a verb to one
of six thin modules under `apps/modules/` — discovery, loader, runner, creator,
validator and switch — and each of those delegates the real work to a handler
under `apps/handlers/`. Discovery scans the search paths and parses frontmatter;
the loader parses a full `SKILL.md` and imports a handler dynamically; the runner
dispatches an action or renders a markdown-only skill; the creator stamps a new
skill from a template; the validator checks requirements; the switch owns the
on/off state and its systemd actuation. Two handlers are infrastructure rather
than a verb: `module_paths.py`, which locates a module without ever reading the
working directory, and the `json/` shim, which binds the fleet's one JSON
service.

Built-in skills live under `lib/`, one directory each, and the templates the
creator stamps live under `templates/`. The directory tree is not drawn here:
it lives in the branch prompt, `.aipass/aipass_local_prompt.md`, where it is
re-derived from the real tree and read on every prompt.

## Documentation

| Page | What is in it |
|------|---------------|
| [docs/skill_contract.md](docs/skill_contract.md) | The three tiers, the `SKILL.md` format, the search paths, creating a skill |
| [docs/off_switch.md](docs/off_switch.md) | What OFF means, what it stops, how it fails closed |
| [docs/runner_notes.md](docs/runner_notes.md) | How a skill is executed, and the doors that bypass the runner |
| [docs/system_status.md](docs/system_status.md) | The system_status skill and `machine_vitals()`, the published read |
| [docs/telegram.md](docs/telegram.md) | The retired Telegram bridge: what retirement means here |
| [docs/dead_cwd.md](docs/dead_cwd.md) | Importing without a readable working directory |
| [docs/json_handler.md](docs/json_handler.md) | Why the JSON handler is a shim, and what may not be added to it |

The same index, with the pages beside each other, is in [docs/](docs/).

## Integration Points

### Depends On

- **@prax** — a hard dependency, two ways: it is the only logging system, and
  the JSON shim binds prax's json service. Both through its entry point, never
  its internals.
- **@cli** — terminal rendering for every line this branch prints.
- Python stdlib, plus **PyYAML** as an optional accelerator: frontmatter is
  parsed with `yaml` when it is importable and by a built-in fallback parser
  when it is not.
- `systemctl --user` — only for the off-switch, and only for a skill that
  declares units.

### Provides To

- **Agents** — discoverable capability units, through `drone`.
- **Projects** — local skill scaffolding, written into the project's own
  `.aipass/skills/`.
- **@api** — `machine_vitals()` from the system_status skill, relayed on the
  host API's machine route and drawn by the phone monitor; and `lock_state()`
  from the screen_lock skill, beside the lock verb. Both are imported
  in-process, so both consult the off-switch themselves.

---

**Last Updated:** 2026-09-15

---
[← Back to AIPass](../../../README.md)
