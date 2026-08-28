# apps/integrations/

Private integration space for `{{BRANCHNAME}}`.

**This folder is gitignored.** Only this README is tracked. Everything else you drop in here stays local and never appears in git, PRs, or the public repo. Safe by construction, not by discipline.

## What goes here

**Branch-specific wrappers** that consume external systems via the @api driver layer. Each wrapper handles how THIS branch uses an external system in its own domain.

```
apps/integrations/
└── {project}/
    ├── wrapper.py        # How this branch uses the driver
    ├── config.json       # Optional — local config
    └── tests/            # Private tests colocated
```

Wrappers should call into `@api`'s generic contracts (e.g. `api.memory_backend.query(...)`), never reference the private project by name in any tracked code. The private project name lives in the @api driver, not here.

## What does NOT go here

- **Driver code** — that belongs in `@api/apps/integrations/{project}/driver.py` (the connection layer).
- **Public business logic** — use `apps/modules/` or `apps/handlers/` for that.
- **Drone plugins** — use `apps/plugins/` for those.
- **Secrets** — they live in `~/.secrets/aipass/`, never in the repo.

## Architecture

The full design is in DPLAN-0133 (private integrations architecture). Three layers:

1. **@api driver layer** (`@api/apps/integrations/{project}/`) — owns the physical connection, auth, transport. Knows the private project name.
2. **Per-branch wrapper layer** (`{this_folder}/{project}/`) — owns how this branch consumes the driver's output in its domain. Calls generic contracts, never names private projects.
3. **Public drone commands** (`drone @api integrations list`, `drone @api integrations call <contract>`) — advertise the extension points without naming specifics. Fork-safe.

## Usage

```python
# Your public code (committed, in apps/modules/ or apps/handlers/)
from aipass.api import memory_backend

results = memory_backend.query("when did we ship watchdog?")
# memory_backend is a generic contract. In your local setup it routes to whatever
# driver you registered in @api/apps/integrations/. In a fresh clone with nothing
# registered, it returns NotConfigured gracefully.
```

```python
# Your private wrapper (in this folder, gitignored)
# apps/integrations/{project}/wrapper.py

from aipass.api import memory_backend

def domain_specific_query(context):
    """Branch-specific query pattern for domain needs."""
    hint = build_query_from_context(context)
    return memory_backend.query(hint, top_k=5, filter={"kind": "decision"})
```

The wrapper stays here, the call into the contract stays here, no private name leaks into tracked code.

---

See DPLAN-0133 for the full design rationale.
