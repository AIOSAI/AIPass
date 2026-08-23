# MEMORY Branch-Local Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

## Identity

Memory — central archive. Vector search, rollover, memory management, all branches. ChromaDB + fastembed (ONNX) semantic search. Rollover archives old `.trinity/` entries when files exceed 600 lines.

## Key Commands

```
drone @memory search "query"        # Semantic search (requires fastembed)
drone @memory search "q" --branch X # Filter by branch
drone @memory rollover              # Execute rollover for triggered files
drone @memory status                # Show rollover stats per branch
drone @memory check                 # Dry run — what needs rollover
drone @memory sync-lines            # Update line count metadata
drone @memory watch                 # Auto-rollover watcher (Ctrl+C to stop)
```

## Architecture

Entry point (`apps/memory.py`) auto-discovers modules via `handle_command()`. Two modules:
- **rollover.py** — handles: rollover, status, check, sync-lines
- **search.py** — handles: search

Handlers implement domain logic under `apps/handlers/` (archive, json, learnings, monitor, rollover, schema, search, storage, tracking, vector).

## Known Issues

- `search` fails without `fastembed` installed
- 5 commands `--help` have no backing module: push-templates, diff-templates, template-status, symbolic demo, symbolic fragments
- `status` shows 0 branches — may need registry path investigation

## Memory + Tracking

- `.trinity/` — passport, local.json, observations.json
- `dev.local.md` — working scratchpad
- `DASHBOARD.local.json` — system status
