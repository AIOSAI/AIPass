# SKILLS — Branch Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/skills/.aipass/aipass_local_prompt.md — Injected on every prompt when in skills directory. -->

Capability framework for AI agents. Discoverable, validatable, executable skill units across three tiers: markdown-only, with handler, full 3-layer.

## Commands

```
drone @skills list                         # Show all discovered skills
drone @skills info <name>                  # Display SKILL.md contents
drone @skills run <name> [action] [args]   # Execute a skill's handler
drone @skills create <name>                # Scaffold new skill (markdown only)
drone @skills create <name> --with-handler # Scaffold with handler.py
drone @skills create <name> --full         # Scaffold with full 3-layer structure
drone @skills validate <name>              # Check if skill requirements are met
drone @skills --help                       # Show help
```

## Apps Layout

```
apps/
├── skills.py              # Entry point — command routing
├── modules/
│   ├── discovery.py       # Orchestration: discover_all (thin, delegates to handler)
│   ├── loader.py          # Orchestration: load_skill (thin, delegates to handler)
│   ├── runner.py          # Execute skills (handler-based or markdown-only)
│   ├── creator.py         # Scaffold new skills from templates
│   └── validator.py       # Check skill requirements
├── handlers/
│   ├── discovery_handler.py  # Core: search paths, SKILL.md scanning, frontmatter parsing
│   ├── loader_handler.py     # Core: parse full SKILL.md, dynamic handler import
│   ├── registry.py           # Build deduplicated skill registry
│   ├── validator.py          # Requirement checking (pip, bins, config)
│   └── template.py           # Template resolution and copying
├── plugins/               # Extension point (empty)
lib/                       # Built-in skills: branch_health, drone_commands, github, inbox_check, screen_lock, system_status, telegram
templates/                 # Skill creation templates (markdown_only, with_handler, full)
```

## Search Paths (first match wins)

1. `.aipass/skills/` — Project-local skills
2. `~/.aipass/skills/` — Global user skills
3. `src/aipass/skills/lib/` — Built-in skills

## Three Skill Tiers

- **Markdown only**: SKILL.md with instructions (AI reads and follows)
- **With handler**: SKILL.md + handler.py (programmatic execution)
- **Full 3-layer**: SKILL.md + apps/ structure (complex skills)

## Memory & Tracking

- `.trinity/passport.json` — identity
- `.trinity/local.json` — session history
- `.trinity/observations.json` — collaboration patterns
- `dev.local.md` — scratchpad for issues, todos, notes
