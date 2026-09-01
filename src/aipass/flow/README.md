[← Back to AIPass](../../../README.md)

# Flow

**Purpose:** Unified plan lifecycle management for AIPass. Creates, tracks, closes, and archives numbered work plans across multiple plan types via a filesystem-driven template registry.
**Module:** `aipass.flow`
**Version:** 2.6.0
**Created:** 2025-11-15
**Last Updated:** 2026-08-31

---

## Overview

Flow is AIPass's plan management system. Every branch uses flow to create, track, close, and archive work plans. Plans are numbered markdown files (`FPLAN-0042_subject_2026-04-22.md`) organized by type, with per-type registries tracking status and metadata.

### What I Do
- Create numbered plans from type-specific templates
- Close plans with foreground archival, then hand vectorisation to a detached background runner
- List and filter plans across all registered types
- Reopen closed plans, pulling the file back from the
  `.backup/processed_plans/` archive when it is no longer at its registered
  location — which after a normal close it never is (see Known Issues)
- Manage plan types via filesystem-driven template registry
- Aggregate plans across branches for central reporting
- Self-heal registries (orphan detection, auto-close missing files, auto-register new template dirs)
- Preview close operations with `--dry-run`

---

## Quick Start

```bash
drone @flow create . "My task description"          # Create a plan in the current directory
drone @flow list open                                # See all open plans
drone @flow close FPLAN-0042                         # Close a completed plan
drone @flow create . "Design topic" dplan            # Create a design plan (DPLAN)
drone @flow templates                                # List available plan types
```

---

## Commands

```bash
# Create plans
drone @flow create . "Subject"                  # Create FPLAN (default)
drone @flow create . "Subject" master           # Create FPLAN master template
drone @flow create . "Design topic" dplan       # Create DPLAN
drone @flow create . "Field note" cplan         # Create CPLAN (any registered shorthand)

# Close plans
drone @flow close FPLAN-0042                    # Close specific plan
drone @flow close DPLAN-0005                    # Close a DPLAN
drone @flow close --all                         # Close every open plan in YOUR project
drone @flow close --all --dry-run               # Preview what would close
drone @flow close --all --exclude-type APLAN    # Hold a whole plan type back (repeatable)
drone @flow close --dry-run FPLAN-0042          # Preview single close

# List plans
drone @flow list open                           # List open plans (all types)
drone @flow list all                            # List all plans

# Template management
drone @flow templates                           # List registered types
drone @flow scan                                # Find unregistered directories
drone @flow register <dir> <PREFIX>             # Register new plan type
drone @flow unregister <dir>                    # Remove plan type

# Registry
drone @flow registry scan                       # Scan filesystem, detect mismatches
drone @flow registry status                     # Show registry health

# Other
drone @flow restore FPLAN-0042                  # Reopen a closed plan
drone @flow aggregate                           # Cross-branch plan aggregation
drone @flow post                                # Background post-close processing
drone @flow --help                              # Full help
drone @flow --version                           # Version string
```

**Use the short verb.** Only the short form executes: `list`, `close`, `create`,
`restore`, `registry`, `aggregate`, and — all four owned by `template_manager` —
`templates`, `scan`, `register`, `unregister`. The module's full name
(`list_plans`, `close_plan`, …) resolves for `--help` but is rejected by the
dispatcher — `post`/`post_close_runner` is the sole module accepting both. The
`--help` screen currently claims otherwise; see Known Issues.

**A bare number is not an identity.** Every per-type registry numbers from
`0001`, so `0012` names a row in each of them and a bare number resolves against
`fplan_registry.json` by default. Pass the typed ID (`close TDPLAN-0012`) when
the plan is not an FPLAN. The prefix is read by an **anchored** match
(`^([A-Z]+PLAN)-` in `apps/handlers/plan/registry_routing.py`), so `TDPLAN-0012`
resolves to `tdplan_registry.json` and never collides with `DPLAN-0012`. A row
whose `file_path` carries no prefix offers no type evidence at all; the bulk and
restore paths refuse such a row rather than guess.

---

## Architecture

```
flow/
├── apps/
│   ├── flow.py                  # Entry point (auto-discovers modules)
│   ├── modules/                 # Thin orchestrators (8 modules)
│   │   ├── create_plan.py       # Plan creation with template support
│   │   ├── close_plan.py        # Closure: foreground archival, background vectorisation
│   │   ├── list_plans.py        # Plan listing and filtering
│   │   ├── restore_plan.py      # Reopen closed plans (+ backup recovery path)
│   │   ├── registry_monitor.py  # Registry scanning and auto-healing
│   │   ├── aggregate_central.py # Cross-branch plan aggregation
│   │   ├── post_close_runner.py # Background post-processing with lock management
│   │   └── template_manager.py  # Template registry management
│   └── handlers/                # Implementation details
│       ├── repo_root.py         # module_file / find_repo_root / exists_exactly — the one location answer
│       ├── plan/                # Lifecycle: create, close, list, restore, display, validation, project scope
│       ├── cli/                 # Shared --help flag detection (help_flags.py)
│       ├── registry/            # Load, save, auto-heal registries
│       ├── template/            # Plan type loader, template resolution, registry CRUD
│       ├── dashboard/           # Status push to local, central, branch dashboards
│       ├── mbank/               # Memory archival and plan processing
│       ├── runner/              # Lock file operations for background processes
│       ├── json/                # Auto-creating JSON handler
│       ├── json_templates/      # Seed JSON payloads for the auto-creating handler
│       ├── summary/             # EMPTY — only generate.py(disabled) remains
│       ├── config/              # EMPTY — package marker only, no code
│       └── events/              # EMPTY — package marker only, no code
├── templates/                   # Plan type plugins (data, not code)
│   ├── flow_plans/              # FPLAN templates (default, master)
│   ├── dev_plans/               # DPLAN templates (default)
│   ├── research_plans/          # RPLAN templates (default)
│   ├── team_dev_plans/          # TDPLAN templates (default)
│   ├── audit_plans/             # APLAN templates (default)
│   ├── playbook_plans/          # PPLAN templates (SOPs: merge, weekly_update, …)
│   └── capture_plans/           # CPLAN templates (default)
├── flow_json/                   # Per-type registries + template_registry.json
├── tests/                       # 1013 tests across 31 files
└── .archive/                    # Archived legacy code + orphaned registries
```

### Design Principles
- **Modules are thin orchestrators** — no business logic, route to handlers and display results
- **Handlers are stateless** — modules inject dependencies (registry loader, paths, config)
- **Plan types are filesystem-driven** — drop a template dir, register a prefix, done
- **Auto-discovery** — `flow.py` finds modules via `handle_command()` convention; `plan_type_loader.py` discovers types from `template_registry.json`

---

## Plan Types

| Type | Prefix | Registry | Templates |
|------|--------|----------|-----------|
| flow_plans | FPLAN | fplan_registry.json | default, master |
| dev_plans | DPLAN | dplan_registry.json | default |
| research_plans | RPLAN | rplan_registry.json | default |
| team_dev_plans | TDPLAN | tdplan_registry.json | default |
| audit_plans | APLAN | aplan_registry.json | default |
| playbook_plans | PPLAN | pplan_registry.json | default, merge, prompt_change, weekly_update |
| capture_plans | CPLAN | cplan_registry.json | default |

Plans follow the naming convention `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md` where NNNN auto-increments per type.

### Adding a New Plan Type
1. Create a directory in `templates/` with one or more `.md` template files
2. Run `drone @flow register <dirname> <PREFIX>` (or let auto-registration detect it on next command)
3. Use `drone @flow create . "Subject" <shorthand>` to create plans of the new type

### Auto-healing
- Template registry auto-prunes orphaned types (directory deleted → entry + plan registry JSON removed)
- Plan registries auto-close entries for missing files
- New template directories auto-register on next command

Auto-prune only fires while the type is **still registered** and its directory
has gone missing. `unregister <dir>` deliberately leaves the plan registry JSON
in place (see `remove_type()`), so unregistering *and then* deleting the
directory slips past the prune and strands a `<shorthand>_registry.json`
forever. `flow_json/pbplan_registry.json` is one such orphan.

### Ignored Folders

`IGNORE_FOLDERS` (`apps/handlers/registry/monitor_ops.py`) is the set of directory
names the registry scan never descends into — dev/VCS tooling, backups, archives,
and system paths that legitimately contain files matching the PLAN filename
pattern but should never be registered as live plans.

**Exact-match only, never substring/pattern matching.** A folder name is skipped
only when it equals an entry in the set exactly. Substring matching was tried
historically and broke: a folder named `dev` would substring-match inside
`devpulse`, silently skipping the entire `devpulse/` tree from scanning (see
`key_learning #33`, `registry_monitor_runaway_log_fix`). Exact-match avoids that
trap entirely — adding `dropbox` only ever matches a folder literally named
`dropbox`, never `devpulse-dropbox-clone` or similar.

`dropbox` is in the set because every branch has one as its received-files
inbox — anything can land there, including old snapshot/backup copies of plan
files with real `PLAN-NNNN` filenames, so no live plan should ever be scanned
out of a `dropbox/` tree.

The current folder list lives in `monitor_ops.py` itself (`IGNORE_FOLDERS`) —
that file is the source of truth; this README doesn't duplicate the list to
avoid drift. Both `registry_monitor`'s scan pass and `heal_registry`'s doctrine
self-heal (collisions / unregistered files / wrong-prefix rows) import this
same set, so a folder added here is skipped by both in lockstep.

### Orphaned Locations Heal Themselves

Branches get tested, moved and re-seated constantly, so plan rows pointing at
stale paths are **expected debris, not an anomaly** (ruling 2026-08-16). Hand-
editing the JSON is the wrong fix: it does not stick while code elsewhere still
writes the stale value. `drone @flow registry scan` re-attributes them instead,
as part of a normal scan.

A row is orphaned when its `location` is not where its citizen lives — either
the path is gone from disk, or it exists but merely *contains* the seat (a
project root holding records that belong to the branch inside it). Detection is
deliberately those two signals only: a plan filed at the repo root or inside a
citizen's own subdirectory is a normal filing, and treating every non-seat path
as debris buried the real orphans under ~30 false positives when first tried.

Attribution runs on evidence, in order: a directory containing exactly one live
seat *is* that citizen's ground; failing that, exactly one live citizen sharing
the directory name **within the same repository**. A bare name match across
repositories is a coincidence, not an identity, and is refused.

Anything unattributable is **quarantined, never guessed and never dropped** —
the row stays untouched and `drone @flow registry status` lists it with the
reason, for a human ruling. Re-running the healer changes nothing the second
time.

---

## Location Discovery — `handlers/repo_root.py`

**Nothing in flow reads the process working directory to find itself.** One
module answers both location questions, and every caller routes through it.

| Function | Answers | Guard it carries |
|----------|---------|------------------|
| `module_file(__file__)` | where is *this module* | `.resolve()` attempted, falls back to the absolute spelling |
| `find_repo_root(start=None)` | which repo root is this | falls back to `SOURCE_ROOT`, **never** `Path.cwd()` |
| `exists_exactly(path)` | is this filename spelled exactly so | lists the parent; `exists()` alone folds case |
| `exactly_named(paths, suffix)` | post-filter for a cased glob | a glob is case-blind on Windows/macOS |

Built 2026-08-31 (Windows round 4, @memory's finding via @devpulse).
`ntpath.realpath` reads `os.getcwd()` **unconditionally** — before it checks
whether the path is even absolute, where `posixpath` only reads it for a
relative one — and `Path.resolve()` routes through it. So on Windows every
module-level `Path(__file__).resolve()` is an import-time working-directory
dependency: a process whose cwd is gone cannot import the module. Guarding
inside the module's functions changes nothing, because the import died before
any of them existed.

Measured red-first, in a subprocess, before any cure: **61 of 61 flow modules
died on import** in both injected worlds. The count only became true as cures
landed, because the first crash line masks everything under it — 61 → 43 after
the guard, → 0 after the 29 module-level sites. Flow carried:

- **29** `_PKG_ROOT = Path(__file__).resolve().parents[N]` sites — every module,
  nearly every handler
- **7** private `_find_repo_root` copies, each ending `return Path.cwd()`, **6
  of them called at module level**
- **2** `inspect.stack()` calls — the import guard, and `log_operation`'s
  caller detection (which no import probe reaches; it runs at write time)

The `Path.cwd()` fallback carried two defects, and only the loud one was a
crash. The quiet one: cwd is a *guess*. Four of those seven callers are
**writers** — `push_central`/`aggregate_central` build
`.ai_central/PLANS.central.json`, `close_helpers` and `restore_ops` build the
`.backup/processed_plans` path — and on a registry-less checkout (the core
registry is gitignored, so every clean clone and CI runner qualifies) each one
resolved against whatever directory the caller's shell happened to be in. A
`try`/`except` would have fixed the traceback and kept the wrong answer.

**Two `Path.cwd()` reads remain, and both are correct.**
`project_scope.caller_cwd()` and `resolve_location._get_caller_cwd()` ask
*where did the caller stand* — a location, observed — and fall back to the
process directory only when `AIPASS_CALLER_CWD` is absent. They are named in
`tests/test_import_dead_cwd.py` so the ban can never delete a right answer, and
the exemption is keyed on **(file, function)**, not on the name alone.

Enforced by `tests/test_import_dead_cwd.py`: two injected worlds with their own
liveness controls, an AST ban, **and** a behavioural sibling that reaches the
caller-is-None branch by calling the guard directly from a `python -c` child
under a realpath denial. Both instruments are kept: regrowing the deleted walk
kills both, and each catches what the other cannot — the ban names the offending
line anywhere in the tree with no subprocess, the behavioural pin proves the cure
in the world it was built for. (The round-4 guidance said only an AST ban could
watch that branch; @spawn measured the correction — it is unreachable from
*import-shaped* pins, not unreachable.)

### The bare-checkout world is a tested world

`AIPASS_REGISTRY.json` is **gitignored and machine-local**, so a dev box and a CI
runner disagree about whether `find_repo_root` takes its fallback. That is not a
detail — it is a whole second world flow's tests must pass in, and it is where
round 5's CI red came from.

The fallback logs `repo_root_fallback` through `json_handler.log_operation`, and
six modules take the walk while **loading**. On a bare checkout that import-time
diagnostic lands inside whichever test window triggers the first import, where
the autouse `mock_json_handler` counts it — so a test pinning
`assert_called_once` breaks on CI and passes everywhere else.

`tests/conftest.py` therefore **pre-imports all six module-level callers**,
settling the walk before any test window exists on every machine. The list is
guarded by `TestThePreImportListIsComplete`, which measures the callers off the
tree by parse and compares them against what conftest actually imports — neither
side hand-copied, because a hand-written list is exactly where an undercount
hides.

Measured, not assumed: with the marker denied and every count-asserting test run
in **full isolation**, **2 of 10** failed. CI had named one.

### An instrument must not import behaviour it is not testing

Round 7's Windows red, and it is the sharper half of the lesson above. The
accessor probes captured the live `os.path.realpath`, then asked *"did a later
patch reach it?"* by denying `os.getcwd` and reading raise/no-raise. That
discriminates on posix, where the captured function ignores the cwd for an
absolute path — so a raise can only mean the patch landed. On nt `os.path` **is**
`ntpath`, and `ntpath.realpath` reads `os.getcwd` unconditionally, so the
**original** raises too and *raised* stops meaning *reached*.

Three rules came out of it (@memory measured the same species on four of their
own reds; each is verified here rather than imported on their word):

1. **Emulate both platforms or neither.** A table with one emulated row and one
   bare row is host-dependent in the half nobody thought about — "no emulation"
   reads as posix only while the host is posix.
2. **Build an emulation from the dialect module by name** (`posixpath`,
   `ntpath`), never from `os.path`, which *is* the host.
3. **When a probe asks "did my patch reach X", let X have captured a sentinel.**
   Otherwise the original's own platform behaviour answers the question.

The litmus that finds all three: run each probe under the *opposite* platform's
emulation and require the verdict not to move. `TestTheWorldArmsOnAPreCapturedAccessor`
runs it on every direction, with a control pinning that the two emulated hosts
are genuinely different worlds — two identical hosts would pass the litmus for
free.

### An instrument's INPUTS are behaviour too

Round 8's Windows red, and it is the round-7 rule one level along. The
emulations were built from `posixpath`/`ntpath` by name and were correct — but
the probe *path* was still built from `os.sep` and `pathlib.__file__`, which are
the **runner's**. On the Windows runner that yields `\definitely\not\here`,
which `posixpath` reads as **relative**; `posixpath.realpath` reads the cwd for a
relative path on every platform, so the posix row convicted for the path's shape
and announced *"the posix emulation is not posix-shaped"* about an emulation that
was doing its job.

Each host now publishes its own dialect-absolute literal, pinned with `isabs`
from the dialect module by name. **The table is not symmetric**, and saying so
matters: `posixpath` refuses an nt literal, while `ntpath` *accepts* a posix one
and treats it as drive-relative — so an nt probe path must carry a drive, and
`isabs` alone is not enough.

The missing instrument was a second dimension. Round 7's litmus varied the
emulated **host**; nothing varied the **runner**. `WINDOWS_RUNNER` fakes exactly
what a probe can read to construct a path — `os.sep`, `os.path`,
`pathlib.__file__` — and every direction must return the same verdict with and
without it. Reverting the dialect-absolute literals reds it on Linux, which is
the point: the failure was otherwise only observable on hardware nobody here has.

### Host == faked is one layer

Round 9, named by @seedgo. Round 8 shipped `WINDOWS_RUNNER`, a fake of everything
a probe can read to build a path. It works on Linux — and it is **dark on the
runner it was written for**. On a Windows host the fake installs Windows-shaped
values over Windows-shaped values, so the faked and unfaked runs are
byte-identical and the control that requires them to *differ* can never arm. A
single fake cannot arm on the host it imitates, for the same reason a
`nt`-emulating world proves nothing on `nt`.

What the campaign reported was that control going dark. The bigger hole was
behind it: the **litmus** was dark too. Round 8's check varied the emulated host
only, so on Windows it measured nothing at all — *a one-dimension litmus is blind
on the host that already IS that dimension.*

The cure is a **set**, not a fake: `RUNNERS` carries a posix-shaped and a
windows-shaped runner, every direction runs under both, and the verdict must not
move. Whichever one matches the host is inert there — and it says so, in
@spawn's three-state shape: **CHANGED / ALREADY-with-the-reason /
UNAVAILABLE-with-the-child's-own-reason.** A row that cannot arm here reports
*why*; it never passes quietly and never fails on someone else's platform. One
pin then simulates *both kinds of host* so the Windows leg is falsifiable from
Linux, forever.

Two rules ride along. Each fake must override **every** host read a probe makes,
pinned per attribute — a partial fake (`os.sep` without `os.path`) survived
otherwise. And the probe path itself must be a **published literal**: anything
computed from the running host — `os.sep`, `sys.executable`, `__file__` — is the
round-8 defect returning under a new spelling, so the source is parsed and a
non-`Constant` right-hand side is refused by name (@trigger's shape, and their
own round-8 red).

### A sentinel cannot arm, so it takes the eagerness pin dark

@trigger's correction, adopted. A sentinel is stale-proof by construction, so a
lazy wrapper *around* the sentinel returns exactly what an eager capture of it
returns — and the behavioural eagerness pin answered the same either way
(measured: that mutation left it green). An identity check cannot be satisfied by
accident, but it **can go dark when the thing whose identity you are checking
stops being able to differ.**

The durable form is a difference you *construct*: two distinguishable sentinels
and a source name rebound after the class body runs. An eager capture answers
`CAPTURED`, a lazy one follows the name and answers `MOVED` — return-value, with
no filesystem, cwd or path dialect anywhere in the question.

### An injected world has to ARM, and the arming is version-shaped

The dead-cwd pins install their world by patching `os.path.realpath` in a
subprocess. On **Python 3.10 that patch reaches nothing**: `pathlib` still has
`_NormalAccessor`, whose `realpath = staticmethod(os.path.realpath)`
(`Lib/pathlib.py:358`) takes its copy when `pathlib` is first imported, and
`Path.resolve` reads it as `self._accessor.realpath(self, strict=strict)`
(`:1077`). Patching the module attribute afterwards rebinds a name nothing will
read again. 3.11 removed the accessor and calls `os.path.realpath` at use —
which is why one CI leg reddened and three stayed green.

Both worlds therefore end in `_ACCESSOR_CURE`, which patches the accessor as a
`staticmethod` behind a `hasattr` — order-independent on 3.10, inert on 3.11+.
A plain function would arrive **bound** and eat the path into `self`.

Because only 3.12 exists on a dev box, that cure would otherwise be a row nobody
here could contradict. So `TestTheWorldArmsOnAPreCapturedAccessor` **rebuilds
3.10's construction locally** and pins both directions — bare module patch →
`ACCESSOR_DIES: NO` (CI's failure, reproduced), plus the cure →
`ACCESSOR_DIES: YES` — with the three traps that make the shape vacuously green
(lazy capture, class-level read, relative probe path) pinned as their own
controls.

---

## Close Pipeline

On `drone @flow close` — the console prints five numbered steps, with vector
intake fired unlabelled between steps 3 and 4:

1. **`[1/5]` Template check** — *reports only, never deletes.* An empty
   template gets the warning "looks like an empty template — closing and
   archiving normally" and then flows through the identical pipeline. The old
   fast-delete branch was removed deliberately: `is_template_content()` is a
   heuristic, and its false positives permanently destroyed FPLAN-0370 and
   FPLAN-0371.
2. **`[2/5]` Mark closed** — sets `status` and the `closed` timestamp, saves the
   type's registry. **Close always succeeds from this point;** every later step
   is non-blocking.
3. **`[3/5]` Archive** — move to `.backup/processed_plans/` (foreground; sets
   `processed`/`processed_date`/`cleanup_completed`/`cleanup_date` and saves in
   one write)
4. *(unlabelled)* **Vector intake** — spawns `apps/modules/post_close_runner.py`
   detached; console shows only "Vectorizing in background"
5. **`[4/5]` Dashboard updates** — local, central, and branch dashboards
6. **`[5/5]` Finalizing** — append to `CLOSED_PLANS.local.json`, fire the
   `plan_closed` trigger event

**Close does not verify vectorisation, and cannot report it.** The runner is
launched with `subprocess.Popen(..., stdout=DEVNULL, stderr=DEVNULL,
start_new_session=True)` (`_spawn_background_runner`, `close_helpers.py`), so
its result is unreadable by the closing process by construction — a failed
vectorisation is silent. Nothing in flow calls `is_plan_vectorized()`; that
function lives in `@memory` and is reached only by the separate
`drone @memory verify <label>` command, which is where a real answer comes from.

Closed plans are archived to `<repo-root>/.backup/processed_plans/`, a shared runtime namespace managed by `@backup` (see `src/aipass/backup/README.md`) and consumed by `@memory` for vectorization.

---

## Dashboard Writes — quick_status Is Shared Ground

`DASHBOARD.local.json` has one `quick_status` block and more than one writer.
`@prax`'s dashboard refresh contributes `todo_count` (read straight from
`.trinity/local.json`); Flow's plan push contributes `active_plans` and
`commons_mentions`. Whole-block replacement means last-writer-wins silently
deletes the other's fields — a plan close used to zero the todo count on every
branch card until the next prax refresh.

Flow's push therefore **merges** (`_calculate_quick_status` in
`apps/handlers/dashboard/push_branch_dashboard.py`):

| Keys | Behaviour |
|------|-----------|
| `active_plans`, `commons_mentions` | recomputed — Flow is the authority |
| `new_mail`, `opened_mail` | preserved if already set, seeded only when absent (@prax reads `inbox.json` first-hand; we only see the possibly-stale `ai_mail` section) |
| `action_required`, `summary` | recomputed over every counter present, foreign ones included |
| anything else | carried through untouched |

A foreign key named `*_count` holding an integer is additionally read as a
counter, so it still reaches `action_required` and the summary line
(`todo_count: 9` → `"9 todos"`). Every other foreign key is passed through
without interpretation.

### The `flow` Section Shape

Every branch's `DASHBOARD.local.json` carries a `flow` section, `managed_by`
flow, written by `push_flow_to_branch_dashboard()`:

| Field | Shape | Meaning |
|-------|-------|---------|
| `active_plans` | **int** | count of *all* open plans for this branch |
| `open_recent` | list of `{plan_id, subject, created}` | the **5 newest open plans** by created date, newest first |
| `recently_closed` | list of `{id, subject, closed}` | last 5 closed within 7 days |
| `total_plans` | int | every plan ever filed for this branch |

`open_recent` is the bounded reading window: agents get their bearings from 5
named plans plus a total, never from a wall of rows. **The cap is enforced in
the renderer** (`_build_open_recent`, `OPEN_RECENT_LIMIT = 5`), not in the
consumer — a reader that has to remember to slice will eventually forget. The
full list lives behind `drone @flow list open`, on request.

**`active_plans` is a count, not a list** — ruling of 2026-08-16 (Patrick, via
`@devpulse`). Flow's push used to publish every open-plan row here; on a branch
with 23 open plans that was 6,096 of the section's 8,552 bytes, and it was the
unbounded context the ruling exists to kill. The list left the section
entirely, and `active_count` collapsed into this one name. The int also matches
what `@prax`'s refresh already writes, so the field means the same thing no
matter which writer built the section.

Card values are written per-branch on plan events, so a change to this contract
only reaches a branch that files a plan afterwards — a quiet branch keeps the
old shape indefinitely. `push_flow_to_all_branch_dashboards()` sweeps every
branch Flow holds plans for and is how a contract change lands fleet-wide.
Paths without a dashboard are skipped, never created.

> **Two writers, one section.** `@prax`'s dashboard refresh also builds this
> section, wholesale (`recently_closed` as `{plan_id, subject}`, and no
> `open_recent` / `total_plans`). Whichever writer ran last wins the whole
> section — the per-key merge above protects `quick_status` only, not section
> level. `active_plans` now agrees across both writers; `open_recent` should
> still be read as present-or-absent until `@prax`'s side is aligned.

---

## Integration Points

### Depends On
- `aipass.cli` — Rich terminal formatting (`console`, `header`, `success`, `error`, `warning`)
- `aipass.prax` — Structured logging via `system_logger`
- `aipass.memory` — Vector intake on plan close
- `aipass.trigger` — Error reporting (optional)

### Provides To
- All branches — plan creation, tracking, closure, and archival
- `aipass.devpulse` — plan status aggregation for system dashboards
- Central reporting — `PLANS.central.json` with per-branch plan sections (all branches, not just flow)

In `PLANS.central.json`, `statistics.total_closed` is a **real count of every
plan a branch has ever closed**, not the size of the `recently_closed` window
beside it. The two are different numbers and only coincide on branches with
five or fewer closures. `recently_closed` is capped at 5; `total_closed` is
measured by `push_central` from the full registry and carried through
aggregation untouched, plus anything auto-closed during the run.

---

## Quality

- **Seedgo:** 100% (46 standards, no type errors)
- **Tests:** 1013 tests in 31 files — 1042 cases collected after parametrisation, 1041 pass / 1 skip, from BOTH rootdirs (branch `pytest.ini` and `-c pyproject.toml --rootdir=.`) AND in both marker worlds (registry present, and a bare checkout like CI's). 101/102 public functions tested (`drone @seedgo test_map @flow`)
- **Source files:** 45 tracked by seedgo (62 `.py` files under `apps/` in total; seedgo excludes `__init__.py` markers)
- **Bypass rules:** 59 (74 before the 2026-08-13 audit — 15 dead + 1 false-reason removed)
- **Registries:** 7 registered plan types + 1 orphan; **820 plans on disk, 24 open, 796 closed**
- **Dead-cwd:** 0 of 62 modules die on import with no readable working directory, in both injected worlds (`tests/test_import_dead_cwd.py`)
- **Last audit:** 2026-08-31 (every figure on this list re-measured, not carried forward)

### Known Issues
- **315 of 775 closed plans have no archived copy and cannot be restored.**
  Fixed 2026-08-22: `restore` now falls back to `.backup/processed_plans/` when
  the file is **not at** the registered `file_path`. Note the correction — the
  row's `file_path` is *not* emptied by close; it is left pointing at where the
  file used to be. Measured 2026-08-25: all 775 closed rows carry a
  `file_path`, and **0 of 775** have a file there. Before that fix restore
  failed for every closed plan while the archive sat intact beside it.
  Coverage by close month: 2026-03 (198 rows) and 04 (97) are **0%**, 05 is
  89%, 06 is 100%, 07 is 94%, 08 is 98%. The 295 pre-May rows have no artifact
  to recover — that is a gap in the archive, not in restore, and it is not
  recoverable by code. A second, narrower refusal also applies: restore copies
  the archived file back to its *registered* directory, so a row whose original
  directory no longer exists is refused by name rather than re-homed.
- **`--help` advertises full module names that the dispatcher rejects.** It
  prints "Commands can be called by short name or full name", but 7 of 8
  modules match only their short verb. It also lists `template`, which no
  module accepts — the working verb is `templates`, absent from that list.
- **`registry status` counts only FPLAN.** It reports the default registry's
  totals under a system-wide label — measured 2026-08-25 it prints
  **401 total / 4 open**, which is `fplan_registry.json` exactly, where the true
  figures across every registry on disk are **798 / 23**. Cause:
  `get_status_impl` calls a bare `load_registry()`. Its quarantine list and
  `Ignored folders: 33` are branch-wide and correct; only the two totals are
  scoped to one type.
- **The cross-branch handler fence never arms.** `apps/__init__.py` is
  `from . import handlers`, so importing *anything* under `aipass.flow.apps`
  loads the handlers package first, and at that moment the nearest real-file
  frame is `apps/__init__.py` itself — which lives under `/flow/` and is
  therefore allowed. An external branch reaching for a flow handler passes the
  guard every time. Reported, deliberately NOT fixed: Patrick's fleet ruling
  (2026-08-31) is that this is one change made everywhere at once, not
  per-branch. Flow has exactly ONE such pre-import door — `flow/__init__.py` is
  a bare docstring and there is no public API surface re-exporting handlers.
- **The fence's branch check is a substring, not a path segment.** `MY_BRANCH`
  is `"flow"` and the test is `"/flow/" in caller_file`, so any caller whose
  path contains a directory named `flow` — in any repo, at any depth — reads as
  local. @spawn's cured guard uses the full dotted package (`aipass.spawn` →
  `/aipass/spawn/`). Out of scope for the round-4 dispatch (which is about the
  cwd defect, not the matching rule) and reported rather than changed, because
  narrowing it is a fence behaviour change that deserves its own red-first pin.
- **`flow_json/PLAN_REGISTRY.json` is legacy and no longer read.** @trigger
  retired their `plan_file.py` handler on 2026-08-31 after measuring it
  themselves: their regex matched **1** of the 366 FPLAN files on disk, so it
  had been inert for essentially every plan since the naming convention took a
  slug. The handler and its 16 tests are archived and the three `trigger.on()`
  registrations are removed, with a comment naming the events as deliberately
  unwired. The paragraph below records the state that preceded that.
- **`flow_json/PLAN_REGISTRY.json` was legacy but NOT unread.** No flow code
  touches it, but `@trigger`'s `apps/handlers/events/plan_file.py` both reads
  and writes it (`_load_registry`/`_save_registry`), and the file's own contents
  are the evidence — 1 plan row against `next_number: 402`, last written
  2026-07-27. An earlier edition of this README claimed "zero readers anywhere
  in the tree"; that was wrong. Whether @trigger's handler should be pointed at
  the typed registries is a question for @trigger, not a flow-side fix.
- `flow_json/pbplan_registry.json` is an orphaned type registry (see Auto-healing)
- Registry scan fires trigger events that are never handled — and as of
  2026-08-31 that is a **decision, not an accident**. @trigger removed the three
  registrations deliberately when they retired `plan_file.py`, and their
  `registry.py` comment says so. An earlier edition of this README called it
  "by design" while the handlers were in fact registered; the sentence is true
  again, for a different reason.
- Dashboard push warns on some closes
- `mbank/process.py` at 718 lines (over the 700 limit)
- **`CLOSED_PLANS.local.json` carries foreign keys on every branch that has
  one.** Measured 2026-08-25: 16 of the 18 core citizens hold the file, and
  **all 16** carry a `document_metadata` block whose `document_type` is
  `session_history` — `local.json`'s schema, not this file's — plus an empty
  `key_learnings` and `todos`. `append_to_closed_plans()` only ever appends to
  the `closed_plans` list; it round-trips foreign keys but never creates them,
  and no other writer exists in `src/aipass/`. @devpulse's DPLAN-0318 brief
  attributes it to a past push from `@memory`'s pusher — *stated there, not
  verifiable from flow's side.* Known and deliberately NOT cleaned: a rebuild
  is scoped in DPLAN-0318.
- `close_ops.py` was split into `close_ops.py` + `close_helpers.py` (257 lines),
  but `close_ops.py` has since grown back to **848 lines** — over the 700 limit,
  and now the longest file in the branch (`mbank/process.py` is 718)
- `push_central.py` comprehensive rewrite (2026-06-02): now pushes all branches' plans, not just flow's — fixed dashboard refresh zeroing other branches' plan counts

---

*Last Updated: 2026-08-31*

---
[← Back to AIPass](../../../README.md)
