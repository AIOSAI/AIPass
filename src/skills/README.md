# Skills

Capability framework for AI agents in AIPass. Skills are discoverable, validatable, and executable units of capability that any AI agent can use.

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
    handlers/
      registry.py          # Skill registry management
      validator.py         # Check requirements
      template.py          # Skill templates
  catalog/                 # Built-in skills
  templates/               # Skill creation templates
  .trinity/                # Branch identity and memory
  tests/                   # Test suite
```