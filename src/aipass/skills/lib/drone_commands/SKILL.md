---
name: drone_commands
description: Execute drone commands -- the AIPass CLI interface for all module operations
version: 1.1.0
tags: [system, cli, drone, aipass]
requires:
  pip: []
  bins: []
  config: []
has_handler: true
---

# Drone Commands Skill

Execute drone commands programmatically. Drone is the AIPass CLI router that dispatches commands to system modules.

## Available Actions

| Action   | Description                                         |
|----------|-----------------------------------------------------|
| `run`    | Execute an arbitrary drone command string            |
| `list`   | List all available drone modules (`drone systems`)   |
| `help`   | Get help for a specific module (`drone @module --help`) |

## Usage

```bash
drone @skills run drone_commands run 'command=@ai_mail inbox'
drone @skills run drone_commands list
drone @skills run drone_commands help module=ai_mail
```

## How Drone Routing Works

Drone uses `@module` syntax to route commands to the correct system module:

```
drone @ai_mail inbox          -> routes to ai_mail module
drone @skills list             -> routes to skills module
drone @devpulse dashboard      -> routes to devpulse module
drone commons feed             -> special case (no @ prefix)
drone systems                  -> lists all registered modules
```

## Architecture

This skill follows the AIPass 3-layer pattern:

```
drone_commands/
  SKILL.md              # This file
  handler.py            # Top-level handler (delegates to apps/)
  apps/
    modules/
      command_runner.py  # Orchestrates drone command execution
    handlers/
      executor.py       # Runs commands via subprocess
      parser.py         # Parses drone output
```

## Output Format

All actions return structured dicts:

```python
{"success": True, "output": "...", "error": None}
```

The `run` action returns the full stdout/stderr from the drone command.

## Notes

- The program is always `drone`: the command is split into arguments and run without a shell, so `;`, `&&` and `|` reach drone as plain arguments
- Commands run in the caller's working directory, which drone reads as the caller's identity
- Timeout defaults to 30 seconds (`timeout=<seconds>`)
- All output is captured, never printed directly
