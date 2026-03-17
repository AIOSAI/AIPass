# Skills

**Purpose:** Capability framework for AI agents in AIPass. Skills are discoverable, validatable, and executable units of capability that any AI agent can use.
**Module:** `skills`
**Created:** 2026-03-07
**Last Updated:** 2026-03-17

---

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
  apps/
    __init__.py
    modules/
      __init__.py
    handlers/
      __init__.py
```

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

## SKILL.md Format

```yaml
---
name: skill-name
description: One-line description
version: 1.0.0
tags: [category1, category2]
requires:
  pip: []        # Python packages needed
  bins: []       # CLI tools needed
  config: []     # Env vars / config keys needed
has_handler: false
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
3. **Built-in**: `src/skills/catalog/` in the AIPass codebase

## Commands / Usage

```bash
drone @skills list                         # Show all discovered skills
drone @skills info <name>                  # Display SKILL.md contents
drone @skills run <name> [action] [args]   # Execute a skill's handler
drone @skills create <name>                # Scaffold new skill (markdown only)
drone @skills create <name> --with-handler # Scaffold with handler.py
drone @skills create <name> --full         # Scaffold with full 3-layer structure
drone @skills validate <name>              # Check if skill requirements are met
drone @skills --help                       # Show help
```

---

## Directory Structure

```
src/skills/
  apps/
    skills.py              # Entry point (handle_command)
    modules/
      discovery.py         # Find skills across search paths
      loader.py            # Load SKILL.md + handlers
      runner.py            # Execute skills
      creator.py           # Scaffold new skills
      validator.py         # Check skill requirements
    handlers/
      json/                # JSON handler (three-JSON pattern)
      registry.py          # Skill registry management
      validator.py         # Check requirements
      template.py          # Skill templates
    json_templates/        # JSON auto-creation templates
    plugins/               # Plugin extensions
  catalog/                 # Built-in skills
  templates/               # Skill creation templates
  skills_json/             # JSON tracking directory
  dropbox/                 # External storage sync
  .trinity/                # Branch identity and memory
  tests/                   # Test suite
```

---

## Integration Points

### Depends On
- Python stdlib (`pathlib`, `json`, `shutil`, `importlib`, `re`, `yaml`)
- Filesystem: reads SKILL.md files from project, global, and built-in search paths

### Provides To
- All modules — skill discovery, loading, validation, and execution
- AI agents — discoverable capability units via `drone @skills`
- Projects — local skill scaffolding via `drone @skills create`

---

*Last Updated: 2026-03-17*