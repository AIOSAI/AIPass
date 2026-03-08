# Naming Conventions
**Status:** Active v3
**Date:** 2026-03-08

---

## Core Principle: Path = Context, Name = Action

The path tells you where you are. The filename tells you what the file does. Don't repeat the path in the name.

**Bad:** `spawn/apps/handlers/json/spawn_json_ops.py`
**Good:** `spawn/apps/handlers/json/json_handler.py`

The path already says it's Spawn's JSON handler directory. The filename says what it does.

**Why this matters:**
- Clean, scannable names
- No lies when code moves between directories
- Shorter imports: `from aipass.spawn.apps.handlers.json.json_handler import JsonHandler`

---

## Entry Points

Every branch has a single entry point at `apps/{branch_name}.py`. This is the only rigid naming rule for entry points.

```
cli/apps/cli.py
drone/apps/drone.py
flow/apps/flow.py
spawn/apps/spawn.py
prax/apps/prax.py
seedgo/apps/seedgo.py
trigger/apps/trigger.py
memory/apps/memory.py
daemon/apps/daemon.py
api/apps/api.py
ai_mail/apps/ai_mail.py
backup/apps/backup.py
```

Never name an entry point `main.py`. The branch name is the entry point name.

---

## Module Files

Module files live under `apps/modules/` and are named for what they do. There is no rigid naming convention beyond clarity. Names are decided during planning based on the module's purpose.

**Real examples:**
```
spawn/apps/modules/core.py              # Core spawn logic
spawn/apps/modules/passport.py          # Passport operations
spawn/apps/modules/sync_templates.py    # Template syncing
flow/apps/modules/create_plan.py        # Plan creation
flow/apps/modules/close_plan.py         # Plan closing
drone/apps/modules/router.py            # Command routing
drone/apps/modules/registry.py          # Module registry
memory/apps/modules/rollover.py         # Memory rollover
trigger/apps/modules/medic.py           # Self-healing logic
api/apps/modules/openrouter_client.py   # OpenRouter API client
```

---

## Handler Files

### The Standard: `handlers/<domain>/<action>.py`

Handlers are the implementation layer. They live under domain-specific subdirectories.

### `json_handler.py` -- The Canonical JSON Handler

Every branch has `handlers/json/json_handler.py`. This is the standard name, not an exception. It exists in 11+ branches with a consistent API.

```
cli/apps/handlers/json/json_handler.py
prax/apps/handlers/json/json_handler.py
flow/apps/handlers/json/json_handler.py
spawn/apps/handlers/json/json_handler.py
trigger/apps/handlers/json/json_handler.py
memory/apps/handlers/json/json_handler.py
daemon/apps/handlers/json/json_handler.py
backup/apps/handlers/json/json_handler.py
api/apps/handlers/json/json_handler.py
ai_mail/apps/handlers/json/json_handler.py
seedgo/apps/standards/aipass/handlers/json/json_handler.py
```

When a branch needs JSON operations, create `handlers/json/json_handler.py`. Some branches also have supplementary files in the same directory (e.g., `load.py`, `save.py`, `initialize.py` in prax) for more granular operations.

### Other Handler Examples

**prax -- monitoring domain:**
```
prax/apps/handlers/monitoring/
    branch_detector.py
    log_watcher.py
    module_tracker.py
    event_queue.py
    unified_stream.py
    telegram_relay.py
```

**prax -- registry domain:**
```
prax/apps/handlers/registry/
    reader.py
    load.py
    save.py
    statistics.py
    meta_ops.py
```

**trigger -- events domain:**
```
trigger/apps/handlers/events/
    error_logged.py
    warning_logged.py
    memory_threshold_exceeded.py
    bulletin_created.py
    startup.py
```

**memory -- specialized domains:**
```
memory/apps/handlers/vector/embedder.py
memory/apps/handlers/rollover/extractor.py
memory/apps/handlers/tracking/line_counter.py
memory/apps/handlers/central_writer.py
```

---

## Why No Redundant Prefixes?

`spawn/apps/handlers/json/spawn_json_ops.py`

What breaks:
1. **Import bloat:** `from aipass.spawn.apps.handlers.json.spawn_json_ops import SpawnJsonOps`
2. **Name lies when code moves:** Rename the directory, the prefix is now wrong
3. **Search noise:** Grep for "spawn" returns every file in the branch
4. **Visual clutter:** Can't quickly scan a directory listing

Information should exist in one place. The path carries context; the filename carries action.

---

## Common Naming Patterns

These are patterns observed across the codebase. They are not prescriptive rules -- use whatever name best describes what the file does. But if your file does one of these things, these names are worth considering since other agents will recognize them:

- `delivery` -- delivering messages or payloads
- `detector` -- detecting conditions or changes
- `embedder` -- creating vector embeddings
- `extractor` -- extracting data from sources
- `indexer` -- indexing or cataloging
- `manager` -- managing lifecycle of a resource
- `watcher` -- watching for file or event changes
- `registry` -- maintaining a registry of items
- `validator` -- validating data or state
- `formatter` -- formatting output
- `cleanup` -- cleanup and maintenance operations
- `scanner` -- scanning directories or data
- `dispatcher` -- routing or dispatching work
- `collector` -- collecting data from multiple sources
- `client` -- API or service client

---

## Summary

1. **Path = Context, Name = Action** -- don't encode directory info in filenames
2. **Entry point is always `{branch_name}.py`** -- never `main.py`
3. **`json_handler.py` is the standard** -- every branch uses it at `handlers/json/json_handler.py`
4. **Module and handler names describe what they do** -- no rigid verb system, just clarity
5. **Short names win** -- less typing, easier scanning, cleaner imports
