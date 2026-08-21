# CANARY

**Purpose:** Permanent test citizen. Exists to be spawned, dispatched, resumed, broken and re-scaffolded so the working fleet never is. All mail, logs and memories here are TEST DATA by definition — never production work. Sibling of @finch (projects tier) and @wren (external tier): three homes covering three different fence contexts.
**Module:** `aipass.canary`
**Created:** 2026-08-20

---

## Overview

### What I Do


### How I Work
- **Entry Point:** `apps/canary.py`
- **Pattern:** Auto-discovers and routes to modules

---

## Architecture

```
CANARY/
├── apps/
│   ├── canary.py       # Entry point
│   ├── modules/            # Business logic
│   ├── handlers/           # Implementation
│   └── plugins/            # Extensions
├── docs/
├── tests/
├── passport.json           # Identity
├── local.json              # Session history
├── observations.json       # Collaboration patterns
└── README.md
```

---

## Commands

*Configure after initialization*

---

## Integration Points

### Depends On


### Provides To

