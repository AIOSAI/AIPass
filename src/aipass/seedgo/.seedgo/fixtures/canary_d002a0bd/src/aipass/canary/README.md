[<- Back to AIPass](../../../README.md)

# CANARY

**Purpose:** The permanent test citizen — spawned, dispatched, resumed, broken
and re-scaffolded so no working branch has to be the experiment.
**Module:** `aipass.canary`
**Version:** 2.5.0
**Created:** 2026-08-20

Everything here is test data by definition: the mail, the logs, the artifacts,
the memories. Nothing this branch produces is evidence about the working system,
and saying so is part of every report it sends.

## Quick Start

```bash
drone @canary                                  # what is present right now
drone @canary --help                           # the reference
drone @canary note add "check the interrupt"   # append one note
drone @canary note list                        # read them back
drone @canary span "2d 4h"                     # a written duration in seconds
drone @canary top 3 scores.txt                 # the three highest counts in a tally
drone @canary align table.txt                  # a text table with its columns lined up
pytest src/aipass/canary/tests -v              # the suite, from the repo root
```

## What It Does

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

## Live Inventory

The list of modules, verbs and flags is generated from the code that runs them,
so it is never typed on this page and cannot go stale here:

- `drone @canary` — the self-map: identity, and every module discovered right
  now with its one-line description.
- `drone @canary --help` — the reference: every verb, the flags, the exit-code
  contract and examples.
- `drone @canary <command> --help` — that command's own page, without running
  it: `drone @canary top --help`.

The first two answer different questions. The self-map lists modules and never
lists verbs; the reference lists verbs and never names a module. Ask the first
what exists today, the second how to call it.

## How To Reach Me

Work arrives here by mail. This branch does not self-start, and nothing it
sends back is evidence about the production fleet.

- `drone @ai_mail dispatch @canary "Subject" "Body"` — send the test and wake
  this branch. Use this when you need something run or checked.
- `drone @ai_mail email @canary "Subject" "Body"` — FYI, no wake.

The reply comes back with the refusal text verbatim, the exit code, and where
the thing landed — not a summary of it.

## Commands

Four verbs are routed today — `note`, `span`, `top` and `align` — and not one
of them is permanent. Modules are added here for a specific test and removed after it,
so the forms above are the reference and this page names no more than the verbs.

What the help pages cannot tell you about themselves — why a refusal exits 2
rather than 0, which forms reach a module's own help, what a raising module
reports — is in [docs/command_surface.md](docs/command_surface.md).

## Architecture

`apps/canary.py` is the entry point and holds no business logic: it discovers
modules, routes to them, and turns their answer into an exit code. Modules live
in `apps/modules/`, which is empty by design between tests; today it holds
`note`, an append-only note store, `span`, a duration parser, `top`, a
leaderboard reader, and `align`, a column aligner. Handlers sit under
`apps/handlers/`: the `notes` handler does the store's reading and appending,
the `duration` handler parses a written duration and owns every one of that
command's refusals, the `leaderboard` handler reads a name/count tally and owns
every one of `top`'s refusals, the `table` handler reads a whitespace-separated
table and owns every one of `align`'s refusals, the
`json` handler is the byte-identical fleet shim over the shared json service,
and `apps/handlers/__init__.py` carries the guard that refuses a cross-branch
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
| [docs/span_module.md](docs/span_module.md) | The duration parser: the grammar, every refusal and why stdout stays empty, the JSON form, what its tests and mutants measure |
| [docs/top_module.md](docs/top_module.md) | The leaderboard reader: the file shape, the tie-break and why it is not insertion order, every refusal, what its tests measure |
| [docs/align_module.md](docs/align_module.md) | The column aligner: the layout, the four rulings the contract left open, every refusal, what its tests and mutants measure |
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

---

**Last Updated:** 2026-09-20

---

[<- Back to AIPass](../../../README.md)
