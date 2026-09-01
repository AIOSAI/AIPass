# CANARY

**Purpose:** Permanent test citizen. Exists to be spawned, dispatched, resumed, broken and re-scaffolded so the working fleet never is. All mail, logs and memories here are TEST DATA by definition — never production work. Sibling of @finch (projects tier) and @wren (external tier): three homes covering three different fence contexts.
**Module:** `aipass.canary`
**Created:** 2026-08-20
**Last Updated:** 2026-08-31

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

Several of those functions are parametrized, so pytest collects and passes
more cases than there are `def test_` lines — 52 functions collect as 82 cases
today. Both counts are true of different things; the tree below states the
function count, which is what the standards audit measures.

The suite must also pass from the repo root, which is the shape CI actually
runs and a different universe from the branch rootdir:

```bash
pytest src/aipass/canary/tests -c pyproject.toml --rootdir=.
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
│   ├── modules/            # Business logic — no .py here by design, added per test
│   ├── handlers/
│   │   ├── paths.py        # Dead-cwd-safe resolve for module-level constants
│   │   └── json/           # JSON handler shim over aipass.aipass.shared
│   ├── integrations/       # Scaffold, empty
│   └── plugins/            # Scaffold, empty
├── artifacts/              # Test artifacts written during dispatches
├── canary_json/            # Where the json shim writes — test data, nothing depends on it
├── tests/                  # 52 test functions, all passing as of 2026-08-31
├── docs/
└── README.md
```

The branch also carries the standard spawn scaffold — `.trinity/`,
`.aipass/`, `.ai_mail.local/`, `.archive/`, `.seedgo/`, `.spawn/`,
`docs.local/`, `dropbox/`, `logs/`, `templates/`, `tools/` — README-only
placeholders except where a service writes into them. `logs/` holds dispatch
transcripts written by @ai_mail, not output from canary's own code.

---

## Commands

Canary registers no persistent subcommands. Modules are added for a specific
test and removed afterwards, so `drone @canary` lists whatever is present right
now rather than a fixed catalogue.

| Flag | What it does |
|------|--------------|
| *(none)* | Print the self-map: identity, purpose, discovered modules |
| `--help`, `-h`, `help` | Usage, flags and examples |
| `--version`, `-V` | Branch name and version (`CANARY v2.0.0`) |

An unknown command is refused and exits non-zero — a refusal that exits 0 is a
lie to every non-human caller, and that one is pinned by test here
(`test_unknown_command_exits_nonzero`).

`main()` also routes `<cmd> --help` to that subcommand's own help without
executing it, and a test pins it against a stub module. It cannot be reached
from a live `drone @canary` today: with no modules registered, every subcommand
is unknown, so `drone @canary <anything> --help` prints `❌ Unknown command` and
exits 1. Documented as code that exists, not as behaviour you can observe here.

---

## Integration Points

### Depends On

- **@cli** — `console`, `error` for all terminal output.
- **@prax** — the logger. Wired on the module-discovery paths: import fallback,
  module load failure, a module raising mid-route, and an unhandled error in
  `main()`. All four are dead while `modules/` is empty, so canary has written
  no prax log of its own — there is no `canary_canary.log` in `system_logs/`.
  The one failure path that *does* fire today, the unknown-command refusal,
  goes through @cli's `error()`, which marks the command failed but writes no
  prax line.
- **@ai_mail** — how work arrives; canary is dispatched, it does not self-start.
- **@spawn** — owns the framework template this branch was scaffolded from.

### Provides To

- **Any citizen needing a subject.** Send canary the test you would not run
  against a working branch: breakage here costs nothing, and the report comes
  back with the refusal text intact.
