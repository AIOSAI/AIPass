[<- Back to AIPass](../../../README.md)

# CANARY

**Purpose:** The permanent test citizen — spawned, dispatched, resumed, broken
and re-scaffolded so no working branch has to be the experiment.
**Module:** `aipass.canary`
**Version:** 2.2.0
**Created:** 2026-08-20
**Last Updated:** 2026-09-15

Everything here is test data by definition: the mail, the logs, the artifacts,
the memories. Nothing this branch produces is evidence about the working system,
and saying so is part of every report it sends.

## Quick Start

```bash
drone @canary                                  # what is present right now
drone @canary --help                           # the reference
drone @canary note add "check the interrupt"   # append one note
drone @canary note list                        # read them back
pytest src/aipass/canary/tests -v              # the suite, from the repo root
```

## What I Do

Absorb the tests the fleet needs run, especially the ones nobody wants aimed at
a working branch. Breakage here costs nothing, so this is where a destructive
experiment belongs.

The failure is the deliverable. A clean run teaches nobody anything; the refusal
text, the exit code, the timestamp and the tick that never fired are the
product. Reports say *where* a thing landed, because an interrupt before the
first tick and one at the fifth are different findings. And a sender's premise
gets corrected even when agreeing would be easier — especially then.

What this branch will not do: report a window it did not hold, call something
green when the output showed red, treat an absence as a defect before checking
its own memory for the gap, or take on production work.

## How To Reach Me

The inventory is generated from the code that runs it, so it is never typed on
this page and never stale:

- `drone @canary` — the self-map: identity, and every module discovered right
  now with its one-line description.
- `drone @canary --help` — the reference: every verb, the flags, the exit-code
  contract and examples.

The two answer different questions. The self-map lists modules and never lists
verbs; the reference lists verbs and never names a module. Ask the first what
exists today, the second how to call it.

## Commands

No command list lives here, deliberately. This branch registers nothing
permanent: modules are added for one specific test and removed afterwards, so
any list typed on this page would be wrong within the week. The help page is
generated from what is actually routed, and it is the reference.

What the help page cannot tell you about itself — why a refusal exits 2 rather
than 0, which forms reach a module's own help, what a raising module reports —
is in [docs/command_surface.md](docs/command_surface.md).

## Architecture

`apps/canary.py` is the entry point and holds no business logic: it discovers
modules, routes to them, and turns their answer into an exit code. Modules live
in `apps/modules/`, which is empty by design between tests; today it holds
`note`, an append-only note store. Handlers sit under `apps/handlers/`: the
`notes` handler does the store's reading and appending, the `json` handler is
the byte-identical fleet shim over the shared json service, and
`apps/handlers/__init__.py` carries the guard that refuses a cross-branch
handler import.

A routed command that refuses exits 2, an unknown command exits 1, and refusal
text goes to stderr. That contract is the part worth knowing before calling
anything here.

The directory tree and the working gotchas live in this branch's own prompt,
`.aipass/aipass_local_prompt.md`, so they cannot disagree with themselves.

## Documentation

Depth lives in [docs/](docs/), one page per subject:

| Page | What it covers |
|------|----------------|
| [docs/command_surface.md](docs/command_surface.md) | Every routed form, the exit-code contract, subcommand help, and the forms the help pages had been missing |
| [docs/note_module.md](docs/note_module.md) | The note store: format, the parse refusal, why it avoids the fleet json service, what its tests measure |
| [docs/testing.md](docs/testing.md) | Running the suite, the conftest seam, and what continuous integration actually runs |
| [docs/branch_data.md](docs/branch_data.md) | Everything written to disk here: the json shim, `canary_json/`, `docs.local/`, `logs/`, the archives |

## Integration Points

### Depends On

- **@cli** — `console` and `error` for all terminal output, and the failure flag
  that turns a routed refusal into exit 2.
- **@prax** — the logger, and the one json service the handler shim binds.
- **@ai_mail** — how work arrives. This branch is dispatched; it does not
  self-start.
- **@spawn** — owns the framework template this branch was scaffolded from.

### Provides To

- **Any citizen needing a subject.** Send the test you would not run against a
  working branch: breakage here costs nothing, and the report comes back with
  the refusal text intact.

[<- Back to AIPass](../../../README.md)
