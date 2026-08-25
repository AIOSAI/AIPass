[← Back to AIPass](../../../README.md)

# Skills

**Purpose:** Capability framework for AI agents in AIPass. Skills are discoverable, validatable, and executable units of capability that any AI agent can use.
**Module:** `skills`
**Created:** 2026-03-07
**Last Updated:** 2026-08-25

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
```

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
      json/                # JSON handler (three-JSON pattern)
      discovery_handler.py # Search paths, SKILL.md scanning, frontmatter parsing
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
  tests/                   # Test suite (324 passing, 1 skipped)
```

---

## Integration Points

### Depends On
- Python stdlib (`pathlib`, `json`, `shutil`, `importlib`, `re`, `subprocess`)
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

*Last Updated: 2026-08-25*

---
[← Back to AIPass](../../../README.md)