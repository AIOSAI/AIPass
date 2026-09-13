# CANARY

**Purpose:** Permanent test citizen. Exists to be spawned, dispatched, resumed, broken and re-scaffolded so the working fleet never is. All mail, logs and memories here are TEST DATA by definition — never production work. Sibling of @finch (projects tier) and @wren (external tier): three homes covering three different fence contexts.
**Module:** `aipass.canary`
**Created:** 2026-08-20
**Last Updated:** 2026-09-12

---

## Quick Start

Canary answers the standard entry-point contract plus whatever per-test module
is present. Today that is one: `note`, an append-only note store (added
2026-09-12, see **The note module**). Measured 2026-09-06: `apps/canary.py`
itself performs no filesystem write at all — the only state it touches is two
process-local `os.environ.setdefault` calls (`AIPASS_BRANCH_NAME`,
`PYTHONUTF8`). The `note` module writes its store under `docs.local/` and its
logs under `logs/` and `canary_json/`, all git-ignored.

```bash
drone @canary                          # self-map: identity, purpose, discovered modules
drone @canary --help                   # usage, flags, examples
drone @canary --version                # branch and version
drone @canary note add "some text"     # append one note
drone @canary note list                # print notes in order, with index and timestamp
```

Run the branch's own suite from the repo root:

```bash
pytest src/aipass/canary/tests -v          # 83 passed, measured 2026-09-12
```

The suite is 41 `def test_` functions across 3 files; parametrization expands
them to 83 collected cases. Both numbers are true of different things — the
tree below states the function count, which is what the standards audit
measures.

Was 33 across 3 files until 2026-09-07, when `tests/test_json_handler.py` moved
to `tests/.archive/deleted_2026-09-07_test_json_handler.py`. Its six tests all
pinned properties of the canonical json shim, and every one of them is now
carried once — parametrised over all 18 branches, canary included — by
`seedgo/tests/test_json_handler_contract.py`. Nothing about canary's shim went
unmeasured; the measurement moved to where the shim is actually one file.
Archived and counted by @seedgo under FPLAN-0491 (33 functions down to 27).
On 2026-09-12 `tests/test_note.py` (12 functions, 34 cases) and two exit-code
tests in `tests/test_canary_cli.py` brought it to 41 functions and 83 cases,
counted by pytest and by the seedgo audit the same day.

**What CI actually runs.** No workflow names canary. `.github/workflows/ci.yml`
runs the whole fleet in ONE process from the repo root, on a 3.10–3.13 matrix:

```bash
pytest -v --tb=short --rootdir=. --ignore=tests/e2e -n auto --dist loadscope
```

Canary is covered by that fleet-wide run, not by a canary-specific job.
**Unverified:** canary's behaviour inside that composed run has not been
reproduced locally — the full-fleet invocation was not run here tonight.

**Repo-root config form — now green.** This README previously documented
`pytest src/aipass/canary/tests -c pyproject.toml --rootdir=.` as red (61
errors, `AIPASS_TEST_LOG_DIR` unset at import — every branch conftest sets it
at import, and canary's set it only inside a fixture, too late for the
repo-root `conftest.py` guard). `tests/conftest.py` now sets the seam at
import time. Verified 2026-09-09, same invocation:

```bash
pytest src/aipass/canary/tests -c pyproject.toml --rootdir=. -v   # 83 passed (2026-09-12)
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
│   ├── modules/            # Business logic — added per test, removed after; today note.py
│   ├── handlers/
│   │   ├── __init__.py     # Caller-resolution guard for handler imports
│   │   ├── json/           # JSON handler shim — binds the fleet service (aipass.prax)
│   │   └── notes/          # store.py — append-only JSON Lines note store
│   ├── integrations/       # Scaffold, empty
│   └── plugins/            # Scaffold, empty
├── artifacts/              # Test artifacts written during dispatches
├── canary_json/            # Where the json shim writes — test data, nothing depends on it
├── tests/                  # 41 test functions in 3 files; 83 cases, all passing 2026-09-12
├── docs/
├── docs.local/             # git-ignored; holds notes.jsonl, the note store
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
`src/aipass/canary/canary_json/probe_<type>.json`. The first writes landed
2026-09-12: the note module's `log_operation` calls created the `note_*` and
`store_*` config/data/log triplets there on its first live run. `canary_json/`
is git-ignored (`git status --ignored` shows `!! canary_json/`).

### The note module

`apps/modules/note.py` routes `note add` and `note list`;
`apps/handlers/notes/store.py` does the reading and appending. Added
2026-09-12 in a @devpulse build round.

- **Store:** `docs.local/notes.jsonl`, inside this branch. `docs.local/` is in
  the repo-root `.gitignore`, pinned by
  `test_docs_local_is_ignored_by_the_repo_gitignore`.
- **Format:** UTF-8 JSON Lines. Each record is exactly
  `{"text": ..., "timestamp": ...}` (ISO-8601 local time with UTC offset),
  terminated by a newline.
- **Append-only:** `add` parses the whole store first, then opens the file in
  append mode. No code path truncates, resets or rewrites it.
- **Refusal:** a store that exists but will not parse — not UTF-8, a line that
  is not a record, a blank line, a final record with no terminator — is
  refused by file name with exit 2, bytes and mtime unchanged. Measured live
  2026-09-12 with one garbage line appended (path shortened here):

  ```
  ❌ note list refused: store will not parse:
  <repo>/src/aipass/canary/docs.local/notes.jsonl - line 3 is not JSON (Expecting value). Store left untouched.
     → Try: inspect or move the file by hand - canary never rewrites a store it cannot read
  ```

- **Not the fleet json service, on purpose:** its `ensure_json_exists`
  regenerates an unreadable document from the in-code default, and
  `load_json` runs that before every read — the exact reset this store must
  never perform. The module still uses `json_handler.log_operation` for its
  operation trail.
- **Pins measured:** 10 mutants against the note and entry-point tests, all
  red — including "refuses loudly AND truncates the store", which only the
  bytes/mtime assertion catches. The terminator guard went unmeasured on the
  first pass (the unterminated cases were refused anyway, because dropping
  their final byte breaks the JSON); a valid record plus a trailing space
  with no terminator now convicts it.

---

## Commands

Canary registers no persistent subcommands. Modules are added for a specific
test and removed afterwards, so `drone @canary` lists whatever is present right
now rather than a fixed catalogue. Rows run 2026-09-06; the self-map, version
and note rows re-run 2026-09-12.

| Flag | What it does | Measured |
|------|--------------|----------|
| *(none)* | Print the self-map: identity, purpose, discovered modules | `Discovered Modules: 1` (note), rc=0 |
| `--help`, `-h`, `help` | Usage, flags and examples | rc=0, all three forms |
| `--version`, `-V` | Branch name and version | `CANARY v2.1.0`, rc=0 |
| `note add TEXT` | Append one note | `Added note at <timestamp>`, rc=0; refusals rc=2 |
| `note list` | Print notes in order with index and timestamp | `1. [<timestamp>] <text>`, rc=0; unparseable store rc=2 |

An unknown command is refused and exits non-zero — a refusal that exits 0 is a
lie to every non-human caller. Measured: `drone @canary bogus` prints
`❌ Unknown command: bogus` and exits 1; pinned by
`test_unknown_command_exits_nonzero`.

`main()` also routes `<cmd> --help` to that subcommand's own help without
executing it, pinned against a stub module by
`test_subcommand_help_does_not_execute_the_command`. Reachable live since the
note module landed: `drone @canary note --help` prints the note help and exits
0 (measured 2026-09-12).

A routed command that refuses exits **2**. `handle_command` returning True
means "handled", not "worked": `main()` resets @cli's failure flag first and
returns `resolve_exit(True)`, so a refusal printed through `error()` becomes
exit 2. Before 2026-09-12 canary returned 0 for every routed command,
refusals included. Pinned by `test_routed_command_that_refuses_exits_two` and
`test_failure_flag_from_an_earlier_command_does_not_leak`.

---

## Status / Known issues

Measured 2026-09-06 unless marked otherwise.

- **Suite:** 83 passed from the repo root (`pytest src/aipass/canary/tests`), 2026-09-12.
- **`-c pyproject.toml --rootdir=.` is green.** Canary's `tests/conftest.py`
  now sets `AIPASS_TEST_LOG_DIR` at module import, matching the other 16
  branches and satisfying the repo-root guard. Verified 2026-09-09: 47 passed;
  re-run 2026-09-12: 83 passed, no errors.
- **Composed fleet run: unverified here.** Whether canary stays green inside
  CI's single-process `-n auto` fleet run was not reproduced locally tonight.
  In that shape a sibling conftest sets the env var first, so canary's missing
  import-time set is masked rather than cured.
- **Prax logs: the note module's only.** The note module logs its refusals
  and I/O failures; its first live corrupt-store run wrote two WARNING lines
  to `logs/note.log` (2026-09-12). The entry point's four `logger` call sites
  (import fallback, module load failure, a module raising mid-route,
  unhandled error in `main()`) have never fired: no `canary_canary.log`
  exists anywhere under the repo (re-measured 2026-09-12).
- **A module that raises is misreported.** `route_command` catches the
  exception, logs it and answers False, so `main()` prints
  `❌ Unknown command: <cmd>` and exits 1 for a command that exists. Read in
  source 2026-09-12, not fixed (outside the note build). The note module
  catches its own `StoreCorrupt` and `OSError`, so its refusals never take
  this path.
- **`canary_json/custom_config/`** is a leftover directory. The fleet service
  accepts only the json types `config`, `data`, `log`, so nothing routes there.
- **`logs/README.md`** still describes the directory as "Prax log output for
    for CANARY". The files in it are @ai_mail dispatch transcripts, plus
  `note.log` since 2026-09-12. Out of scope for
  this pass (README.md only); noted for the next one.
- **APLAN-0019** (branch audit) remains open by doctrine — APLANs stay open.

---

## Integration Points

### Depends On

- **@cli** — `console`, `error` for all terminal output; `reset_command_state`
  and `resolve_exit` turn a routed refusal into exit 2.
- **@prax** — the logger, and the one json service the handler shim binds.
  The entry point's logger is wired on four module-discovery paths: import
  fallback, module load failure, a module raising mid-route, and an unhandled
  error in `main()`; none has fired (see Status above). The note module logs
  its own refusals to `logs/note.log`. The unknown-command refusal goes
  through @cli's `error()`, which marks the command failed but writes no prax
  line.
- **@ai_mail** — how work arrives; canary is dispatched, it does not self-start.
- **@spawn** — owns the framework template this branch was scaffolded from.

### Provides To

- **Any citizen needing a subject.** Send canary the test you would not run
  against a working branch: breakage here costs nothing, and the report comes
  back with the refusal text intact.
