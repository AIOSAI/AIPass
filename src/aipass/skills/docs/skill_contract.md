[← Back to the skills README](../README.md)

# The Skill Contract

What a skill is, how one is written, where they are found, and how one is created. The runner and the off-switch have their own pages.

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

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
