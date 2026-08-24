# {{BRANCHNAME}}

**Purpose:** {{PURPOSE_BRIEF}}
**Module:** `aipass.{{MODULE}}`
**Created:** {{DATE}}

---

## Overview

### What I Do
{{KEY_CAPABILITIES}}

### How I Work
- **Entry Point:** `apps/{{MODULE}}.py`
- **Pattern:** Auto-discovers and routes to modules

---

## Quick Start

```bash
# See what this branch is and which modules it has discovered
drone @{{BRANCH}}

# Full help - usage, commands, flags, examples
drone @{{BRANCH}} --help

# Version
drone @{{BRANCH}} --version
```

---

## Architecture

```
{{BRANCHNAME}}/
├── apps/
│   ├── {{MODULE}}.py       # Entry point
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
{{DEPENDS_ON}}

### Provides To
{{PROVIDES_TO}}

---

*Last Updated: {{DATE}}*
