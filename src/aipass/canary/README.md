# CANARY

**Purpose:** Permanent test citizen. Exists to be spawned, dispatched, resumed, broken and re-scaffolded so the working fleet never is. All mail, logs and memories here are TEST DATA by definition — never production work. Sibling of @finch (projects tier) and @wren (external tier): three homes covering three different fence contexts.
**Module:** `aipass.canary`
**Created:** 2026-08-20
**Last Updated:** 2026-09-06

---

## Quick Start

Canary answers the standard entry-point contract and nothing else. Measured
2026-09-06: `apps/canary.py` performs no filesystem write at all — the only
state it touches is two process-local `os.environ.setdefault` calls
(`AIPASS_BRANCH_NAME`, `PYTHONUTF8`).

```bash
drone @canary              # self-map: identity, purpose, discovered modules
drone @canary --help       # usage, flags, examples
drone @canary --version    # branch and version
```

Run the branch's own suite from the repo root:

```bash
pytest src/aipass/canary/tests -v          # 61 passed, measured 2026-09-06
```

The suite is 33 `def test_` functions across 3 files; parametrization expands
them to 61 collected cases. Both numbers are true of different things — the
tree below states the function count, which is what the standards audit
measures.

**What CI actually runs.** No workflow names canary. `.github/workflows/ci.yml`
runs the whole fleet in ONE process from the repo root, on a 3.10–3.13 matrix:

```bash
pytest -v --tb=short --rootdir=. --ignore=tests/e2e -n auto --dist loadscope
```

Canary is covered by that fleet-wide run, not by a canary-specific job.
**Unverified:** canary's behaviour inside that composed run has not been
reproduced locally — the full-fleet invocation was not run here tonight.

**Known red — the repo-root config form.** This README previously documented
`pytest src/aipass/canary/tests -c pyproject.toml --rootdir=.` as a shape that
must pass. Measured 2026-09-06, it does not:

```
61 errors in 0.66s
RuntimeError: aipass.canary.apps.handlers.json.json_handler binds the fleet
json service but AIPASS_TEST_LOG_DIR is not set — every branch conftest sets
it at import
```

`-c pyproject.toml` puts the rootdir at the repo root, which loads the
repo-root `conftest.py` guard; canary's `tests/conftest.py` sets
`AIPASS_TEST_LOG_DIR` only inside a fixture, too late for that guard. Either
form below passes (61 passed, both measured 2026-09-06):

```bash
pytest src/aipass/canary/tests --rootdir=. -v
AIPASS_TEST_LOG_DIR=$(mktemp -d) pytest src/aipass/canary/tests -c pyproject.toml --rootdir=. -v
```

See **Status / Known issues**.

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
│   │   ├── __init__.py     # Caller-resolution guard for handler imports
│   │   └── json/           # JSON handler shim — binds the fleet service (aipass.prax)
│   ├── integrations/       # Scaffold, empty
│   └── plugins/            # Scaffold, empty
├── artifacts/              # Test artifacts written during dispatches
├── canary_json/            # Where the json shim writes — test data, nothing depends on it
├── tests/                  # 33 test functions in 3 files; 61 cases, all passing 2026-09-06
├── docs/
└── README.md
```

`apps/handlers/.archive/` and `apps/handlers/json/.archive/` hold the
pre-sweep `paths.py` and the retired local json handler. Archive directories
are untracked by doctrine — present on disk, absent from git.

The branch also carries the standard spawn scaffold — `.trinity/`,
`.aipass/`, `.ai_mail.local/`, `.archive/`, `.seedgo/`, `.spawn/`,
`docs.local/`, `dropbox/`, `logs/`, `templates/`, `tools/` — README-only
placeholders except where a service writes into them. `logs/` holds dispatch
transcripts written by @ai_mail (`dispatch_stdout.log`, `dispatch_stderr.log`,
`dispatch_wake.log`), not output from canary's own code.

### The json handler

`apps/handlers/json/json_handler.py` is the byte-identical fleet shim
(sha256 `3456b766…513cf0b7`), which seedgo checks by hash. It imports exactly
one thing — `aipass.prax.json_handler` — and binds its public names to a
per-branch handle. It imports nothing from `aipass/shared`: that handler was
retired to `shared/.archive/` in FPLAN-0489, and this branch's dead-cwd pins
dropped their preload of it in the same sweep.

Path resolution measured 2026-09-06 with the test seam unset:
`get_json_path('probe', 'config'|'data'|'log')` resolves to
`src/aipass/canary/canary_json/probe_<type>.json`. Nothing has been written
there yet — `canary_json/` holds only placeholder READMEs.

---

## Commands

Canary registers no persistent subcommands. Modules are added for a specific
test and removed afterwards, so `drone @canary` lists whatever is present right
now rather than a fixed catalogue. Every row below was run 2026-09-06.

| Flag | What it does | Measured |
|------|--------------|----------|
| *(none)* | Print the self-map: identity, purpose, discovered modules | `Discovered Modules: 0`, rc=0 |
| `--help`, `-h`, `help` | Usage, flags and examples | rc=0, all three forms |
| `--version`, `-V` | Branch name and version | `CANARY v2.0.0`, rc=0 |

An unknown command is refused and exits non-zero — a refusal that exits 0 is a
lie to every non-human caller. Measured: `drone @canary bogus` prints
`❌ Unknown command: bogus` and exits 1; pinned by
`test_unknown_command_exits_nonzero`.

`main()` also routes `<cmd> --help` to that subcommand's own help without
executing it, pinned against a stub module by
`test_subcommand_help_does_not_execute_the_command`. It cannot be reached from
a live `drone @canary` today: with no modules registered, every subcommand is
unknown, so `drone @canary bogus --help` prints `❌ Unknown command: bogus` and
exits 1 (measured). Documented as code that exists, not as behaviour you can
observe here.

---

## Status / Known issues

Measured 2026-09-06 unless marked otherwise.

- **Suite:** 61 passed from the repo root (`pytest src/aipass/canary/tests`).
- **`-c pyproject.toml --rootdir=.` is red — canary's own defect, not the
  invocation's.** Canary's `tests/conftest.py` sets `AIPASS_TEST_LOG_DIR` only
  inside a fixture; 16 of the 18 branch conftests set it at module import, as
  the repo-root guard's message requires. Controls run tonight with the same
  flags: @cli 186 passed, @daemon 495 passed, @aipass 1081 errors with the
  identical `RuntimeError`. Canary and @aipass are exactly the two branches
  without the import-time set. Reported, not fixed — the round that found it
  was docs-only.
- **Composed fleet run: unverified here.** Whether canary stays green inside
  CI's single-process `-n auto` fleet run was not reproduced locally tonight.
  In that shape a sibling conftest sets the env var first, so canary's missing
  import-time set is masked rather than cured.
- **No prax log of canary's own.** The four `logger` call sites
  (`apps/canary.py` lines 68, 94, 195, 263 — import fallback, module load
  failure, a module raising mid-route, unhandled error in `main()`) are all
  dead while `modules/` is empty. Measured: no `canary_canary.log` exists
  anywhere on this disk; `prax/system_logs/` holds only `prax_dashboard.log`.
- **`canary_json/custom_config/`** is a leftover directory. The fleet service
  accepts only the json types `config`, `data`, `log`, so nothing routes there.
- **`logs/README.md`** still describes the directory as "Prax log output for
  CANARY". The files in it are @ai_mail dispatch transcripts. Out of scope for
  this pass (README.md only); noted for the next one.
- **APLAN-0019** (branch audit) remains open by doctrine — APLANs stay open.

---

## Integration Points

### Depends On

- **@cli** — `console`, `error` for all terminal output.
- **@prax** — the logger, and the one json service the handler shim binds.
  The logger is wired on four module-discovery paths: import fallback, module
  load failure, a module raising mid-route, and an unhandled error in
  `main()`. All four are dead while `modules/` is empty, so canary has written
  no prax log of its own (measured — see Status above). The one failure path
  that *does* fire today, the unknown-command refusal, goes through @cli's
  `error()`, which marks the command failed but writes no prax line.
- **@ai_mail** — how work arrives; canary is dispatched, it does not self-start.
- **@spawn** — owns the framework template this branch was scaffolded from.

### Provides To

- **Any citizen needing a subject.** Send canary the test you would not run
  against a working branch: breakage here costs nothing, and the report comes
  back with the refusal text intact.
