# CANARY

**Purpose:** Permanent test citizen. Exists to be spawned, dispatched, resumed, broken and re-scaffolded so the working fleet never is. All mail, logs and memories here are TEST DATA by definition — never production work. Sibling of @finch (projects tier) and @wren (external tier): three homes covering three different fence contexts.
**Module:** `aipass.canary`
**Created:** 2026-08-20
**Last Updated:** 2026-08-22

---

## Quick Start

Canary answers the standard entry-point contract and nothing else — there is no
command here that changes system state, by design.

```bash
drone @canary              # self-map: identity, purpose, discovered modules
drone @canary --help       # usage, flags, examples
drone @canary --version    # branch and version
```

Run the branch's own suite from the repo root, which is how CI runs it:

```bash
pytest src/aipass/canary/tests -v
```

---

## Overview

### What I Do

- Absorb the tests the fleet needs run — spawn, dispatch, resume, break, re-scaffold — so no working branch is the experiment.
- Report failures loudly and verbatim: refusal text, timestamps, and what did *not* happen. The failure is the deliverable.
- Say where a thing landed, not just that it landed — an interrupt before tick 1 is a different finding than one at tick 5.
- Correct a sender's premise when it is wrong, including when they arrive happy and agreement would be easier.

**Nothing here generalizes.** Canary output is never proof about the production
fleet, and saying so is part of every report.

### How I Work
- **Entry Point:** `apps/canary.py`
- **Pattern:** Auto-discovers and routes to modules

---

## Architecture

```
CANARY/
├── apps/
│   ├── canary.py           # Entry point
│   ├── modules/            # Business logic (empty by design — added per test)
│   ├── handlers/
│   │   └── json/           # JSON handler shim over aipass.aipass.shared
│   └── plugins/            # Extensions
├── artifacts/              # Test artifacts written during dispatches
├── docs/
├── tests/
└── README.md
```

---

## Commands

Canary registers no persistent subcommands. Modules are added for a specific
test and removed afterwards, so `drone @canary` lists whatever is present right
now rather than a fixed catalogue.

| Flag | What it does |
|------|--------------|
| *(none)* | Print the self-map: identity, purpose, discovered modules |
| `--help`, `-h` | Usage, flags and examples |
| `--version`, `-V` | Branch name and version |

`drone @canary <cmd> --help` shows that subcommand's help without executing it.
An unknown command is refused and exits non-zero — a refusal that exits 0 is a
lie to every non-human caller, and that one is pinned by test here.

---

## Integration Points

### Depends On

- **@cli** — `console`, `error` for all terminal output.
- **@prax** — the logger; every fallback and failure path writes a line.
- **@ai_mail** — how work arrives; canary is dispatched, it does not self-start.
- **@spawn** — owns the framework template this branch was scaffolded from.

### Provides To

- **Any citizen needing a subject.** Send canary the test you would not run
  against a working branch: breakage here costs nothing, and the report comes
  back with the refusal text intact.
