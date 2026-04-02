# MEMORY

**Purpose:** Central memory archive with semantic search, rollover, and archival across all AIPass branches.
**Module:** `aipass.memory`
**Created:** 2026-03-07
**Last Updated:** 2026-04-01
**Citizen Class:** builder

---

## Overview

Memory is the central memory archive system that:
- Provides semantic search across all branch memories
- Archives memories when branches hit rollover limits (600 lines)
- Extracts symbolic dimensions from conversations
- Manages template distribution and line-count tracking across branches

---

## Commands / Usage

**Via Drone (recommended):**
```bash
drone @memory search "error handling"       # Semantic search across all branch memories
drone @memory search "query" --branch SEEDGO  # Filter search by branch
drone @memory search "query" --n 10         # Limit number of results
drone @memory rollover                      # Execute memory rollover for files over 600 lines
drone @memory status                        # Show rollover statistics for all branches
drone @memory check                         # Dry run — check which files need rollover
drone @memory watch                         # Start auto-rollover watcher (Ctrl+C to stop)
drone @memory sync-lines                    # Update line count metadata for all branches
drone @memory push-templates                # Push template updates to all branches
drone @memory push-templates --dry-run      # Preview template changes without writing
drone @memory diff-templates                # Show template differences per branch
drone @memory template-status               # Show template version and push status
drone @memory symbolic demo                 # Run fragmented memory demonstration
drone @memory symbolic fragments "query"    # Search symbolic fragments
```

**Direct execution:**
```bash
python3 -m aipass.memory.apps.memory search "query"
python3 -m aipass.memory.apps.memory rollover
```

---

## Architecture

```
memory/
├── __init__.py              # Package init
├── README.md                # This file
├── DASHBOARD.local.json     # System status dashboard
├── pytest.ini               # Test configuration
├── apps/
│   ├── __init__.py
│   ├── memory.py            # Entry point (CLI) — auto-discovers modules
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── rollover.py      # Rollover orchestrator — line checks, archival triggers
│   │   ├── search.py        # Search orchestrator — semantic query routing
│   │   └── verify.py        # Plan verification — check vectorized plan status
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── central_writer.py    # Central memory write operations
│   │   ├── dashboard_push.py    # Dashboard status push
│   │   ├── archive/             # Memory archival indexing
│   │   ├── json/                # JSON handler operations
│   │   ├── learnings/           # Learning extraction
│   │   ├── monitor/             # File watcher for auto-rollover
│   │   ├── rollover/            # Rollover implementation logic
│   │   ├── schema/              # Memory schema definitions
│   │   ├── search/              # Search implementation (vector/semantic)
│   │   ├── storage/             # Storage backend operations
│   │   ├── tracking/            # Line count and metadata tracking
│   │   ├── symbolic/             # Symbolic dimension extraction
│   │   ├── templates/            # Template management
│   │   └── vector/              # Vector DB (ChromaDB) operations
│   ├── extensions/          # Extension plugins
│   └── plugins/             # Plugin system
├── artifacts/               # Build/output artifacts
├── docs/                    # Documentation
├── memory_json/             # Memory JSON data store
├── tests/                   # Test suite
└── tools/                   # Utility scripts
```

---

## Integration Points

### Depends On
- `rich` — Console output, panels, and tables
- Python stdlib (`sys`, `time`, `signal`, `logging`, `pathlib`, `importlib`)

### Provides To
- All branches — memory rollover, archival, and retrieval services
- All branches — semantic search across branch memories
- All branches — template distribution via `push-templates`
- All branches — line count metadata via `sync-lines`

---

## Key Modules

### rollover
The rollover module monitors memory files across all branches registered in `AIPASS_REGISTRY.json`. When files exceed 600 lines, it triggers archival — splitting the file, preserving recent context, and indexing the archived portion. The `watch` command runs a persistent file watcher that auto-triggers rollover on changes.

---

## Identity

- **Passport:** `.trinity/passport.json`
- **Session History:** `.trinity/local.json`
- **Observations:** `.trinity/observations.json`
- **Branch Prompt:** `.aipass/branch_system_prompt.md`

---

*Last Updated: 2026-04-01*
