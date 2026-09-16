# {{BRANCHNAME}}

**Purpose:** {{PURPOSE_BRIEF}}
**Module:** `aipass.{{MODULE}}`
**Class:** {{CITIZEN_CLASS}}

---

## What I Am

*One short paragraph for a stranger or another branch: what this branch owns, and
what it is for. A manager (a project's first citizen) also holds the project's
context and coordinates its work; a specialist owns one domain — write whichever
is true for you. Your class is in `.trinity/passport.json` under
`identity.citizen_class`.*

---

## How To Reach Me

```bash
drone @{{BRANCH}}                                     # live inventory — modules and commands, read from the code
drone @{{BRANCH}} --help                              # the full reference
drone @ai_mail dispatch @{{BRANCH}} "Subject" "Body"  # hand me work
```

The inventory is generated, so it is never stale. This README does not repeat it.

---

## Where The Depth Lives

| Layer | What it carries |
|-------|-----------------|
| `README.md` | this file — the face for strangers and other branches |
| `docs/` | the depth: one tracked file per module or handler group, indexed below |
| `.aipass/aipass_local_prompt.md` | breadcrumbs for the agent working here, injected every turn |
| `.trinity/` | identity, session history, what was learned |

*Index each `docs/` file here as you write it — one line on what it covers.*

---

## Integration

### Depends On

- **aipass.prax** — logging via `logger`
- **aipass.cli** — console output (`console`, `error`)

### Provides To

*List the branches that call this one, once there are any.*

---

*This file is measured against a cap by `drone @seedgo audit context @{{BRANCH}}` —
seedgo owns the number. Past it, move depth into `docs/`, never into the prompt.*
