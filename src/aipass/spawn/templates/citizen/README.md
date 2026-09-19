# {{BRANCHNAME}}

**Purpose:** {{PURPOSE_BRIEF}}
**Module:** `aipass.{{MODULE}}`
**Class:** {{CITIZEN_CLASS}}

---

## Quick Start

```bash
drone @{{BRANCH}}           # what this branch can do, read from the code
drone @{{BRANCH}} --help    # the full reference
```

---

## What It Does

*A few lines for a stranger or another branch: what this branch owns and what it is for.
A manager (a project's first citizen) also holds the project's context and coordinates its
work; a specialist owns one domain. Your class is `identity.citizen_class` in
`.trinity/passport.json`.*

---

## Live Inventory

`drone @{{BRANCH}}` prints the self-map, every module with its one-line description, and
`drone @{{BRANCH}} --help` prints the command surface. Both are generated from the code on
every call, so this README never copies them.

---

## How To Reach Me

```bash
drone @ai_mail dispatch @{{BRANCH}} "Subject" "Body"   # hand me work, and wake me
drone @ai_mail email @{{BRANCH}} "Subject" "Body"      # tell me something, no wake
```

---

## Commands

`drone @{{BRANCH}} --help` is the source of truth. *Name here the few verbs worth knowing
before reading it, once there are any.*

---

## Architecture

`apps/{{BRANCH}}.py` is the entry point; `apps/modules/` holds one coordinator per verb and
`apps/handlers/` the implementation behind them. *Name the modules here as they land, and
the idea behind the layout.*

---

## Documentation

The depth lives in [docs/](docs/README.md), one page per module or handler group, each
indexed there on a line of its own. This README is measured against a cap by
`drone @seedgo audit context @{{BRANCH}}`; past it, depth moves into `docs/`, never into
the prompt.

---

## Integration Points

### Depends On

- **aipass.prax** — logging via `logger`
- **aipass.cli** — console output (`console`, `error`)

### Provides To

*List the branches that call this one, once there are any.*

---

**Last Updated:** {{DATE}}

---
