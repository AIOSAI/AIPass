# APLAN-0004: Branch audit - flow

Tag: audit, branch-audit, flow

> Branch audit @flow -- living document tracking health, issues, improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- track ongoing health, issues, improvements for specific branch. Unlike DPLANs (capture moment thinking) or FPLANs (track build), APLANs persist across sessions + grow as branch evolves.

**This IS for:**
- Recording branch health status + key metrics
- Tracking bugs, issues, improvement opportunities as discovered
- Logging what's been dispatched + results
- Maintaining clear picture: open vs resolved
- Serving as working memory next time we touch this branch

**This is NOT for:**
- Building code -- that's FPLAN
- One-off design thinking -- that's DPLAN
- Quick fixes -- just do those directly

**APLANs never trimmed, rarely closed.** They accumulate history. When branch gets major overhaul, start fresh APLAN + archive old one.

**Keep items current.** Check boxes when work done. Add ! issues as found. Update metrics when you verify. Document should always reflect reality.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | YELLOW |
| **Last verified** | 2026-08-13 (S52) |
| **Open items** | 10 open + 2 tracked elsewhere (3 functional bugs, 3 stale artefacts, 4 cosmetic/dead) |
| **Tests** | 827 pass, 0 fail, 1 skip (was 787 — +40 help-flag canaries) |
| **Seedgo** | 100% (45 standards, 43 files, no type errors) |
| **help_flag_safety** | 100% (was 37% — 8 modules fixed, S52) |
| **Bypass entries** | 59 (74 → 58 dead removed in S51, +1 shared-predicate rule in S52) |
| **CLI score** | cli 100%, cli_flags 100%, cli_ux 100% |
| **Live command sweep** | 24 invocations S51 + 11 help probes S52, 0 tracebacks |

**Why YELLOW and not GREEN:** every headline number is green, and the plan
lifecycle a caller uses daily (create → list → close) works end to end. But
four advertised behaviours do not do what they say, and one of them —
`restore` — is the branch's own named recovery feature failing on the only
path that matters. Green would be a soft number.

## Current State

### Summary
- Plan lifecycle for all of AIPass: create, list, close, restore, archive across 6 registered plan types. Every branch depends on this.
- v2.2.1, now consistent between `apps/flow.py:156` and `README.md:7` (README claimed 2.2.2 all session — corrected *down* to the running version, since code is truth and no 2.2.2 was ever released).
- 705 plans across 7 registry files; 27 open fleet-wide at audit time.
- Last build: the `quick_status` merge fix (FPLAN-0405, 2026-08-12) — verified still holding in this audit.

### Architecture
`flow.py` auto-discovers modules in `apps/modules/` by the `handle_command()`
convention, then offers each module the command in turn until one returns True.
Modules are thin orchestrators; `apps/handlers/` holds stateless
implementation grouped by domain (`plan/`, `registry/`, `template/`,
`dashboard/`, `mbank/`, `runner/`, `json/`). Plan types are data, not code — a
directory of `.md` templates in `templates/` plus a row in
`flow_json/template_registry.json`.

### What Works Well
- **The daily path is solid.** create (default / master / dplan), list open, list all, close, close --dry-run, close --all --dry-run, templates, scan, registry scan, register, unregister — all exercised live, all correct.
- **Type-aware routing holds.** Plans of 6 types coexist on overlapping numbers with no collisions; the S33 registry-routing fix is still doing its job.
- **Close pipeline is honest end to end.** All 5 stages report; the file really lands in `.backup/processed_plans/`; the registry row gets closure metadata; dashboards update.
- **Error paths are clean.** Unknown plan, unknown command, missing register args all return readable errors. Zero Python tracebacks across the entire sweep.
- **Seedgo 100% is now real.** It was previously propped up by a wildcard bypass on `test_quality` (see Resolved) — the score survives without it.
- **Test suite is fast and honest** — 787 green in ~10s, and the single skip states a real reason.

## Issues Found

### Open

- [ ] **`restore` cannot reach the backup archive on the normal close path** — close *moves* the plan file to `.backup/processed_plans/`. `restore` then walks to step 5 (`restore_ops.py:310`), finds no file at the registered location, and hard-fails `"file not found at registered location - move file back first"`. Backup recovery (`recover_plan_from_backup`, `restore_ops.py:63`) is correct and works, but is only attempted at step 3 — when the plan is missing from the **registry** entirely. A normally-closed plan is always *in* the registry, so recovery is never reached. **Every normally-closed plan is affected.** Proven live twice: FPLAN-0406 (in `/tmp`) and FPLAN-0408 (inside the repo), each with the archived copy sitting in `.backup/processed_plans/` the whole time. **The suite locks the bug in:** `TestRestoreFileMissing.test_file_not_at_location` (`tests/test_restore_ops.py:289`) sets up a *closed* plan with a missing file — the exact post-close state — and asserts `success is False` with `error_type == "file_missing"`. So the failing path is encoded as the contract, and all three `restore_plan_impl` tests inject a mocked `recover_plan_from_backup_fn`, meaning no test ever runs real recovery through `restore`. That is why 787 green never caught this. Fixing it means rewriting that test, not just the handler. **Not fixed today on purpose:** the one-line-ish fix (attempt recovery at step 5 before failing) changes what `restore` means — either the code should pull from the archive, or the README should stop promising it. That is an owner's call, and it deserves red-first tests rather than an audit-day edit.
- [ ] **`--help` advertises full module names the dispatcher rejects** — `flow.py:235` prints "Commands can be called by short name (e.g., 'create') or full name (e.g., 'create_plan')" and `flow.py:240-253` renders 8 `short, full` pairs. But each module's `handle_command()` matches only its short verb (`list_plans.py:188` `if command != "list"`, and the same shape in registry_monitor, aggregate_central, close_plan, create_plan, restore_plan). **7 of 8 full names fail**; only `post_close_runner` accepts both (`post_close_runner.py:61`). Proven: `drone @flow list_plans open` → `Unknown command: list_plans`, while `drone @flow list open` works. The `--help` *route* resolves full names via a separate interception, so the names look alive until you pass real arguments.
- [ ] **`template` is advertised but does not exist; `templates` works and is never listed** — the short name is derived mechanically as `module_name.split("_")[0]` (`flow.py:242`), yielding `template` for `template_manager`. No module accepts either form (`template_manager.py:204` matches `templates`, `register`, `unregister`, `scan`). So the command list names two dead verbs for this module and omits the live one, which appears only in the EXAMPLES block. Same root cause as the item above: **the help screen renders names it derives instead of names modules declare.** (This is key_learning #46 biting a second time, in my own CLI.)
- [ ] **`registry status` reports FPLAN-only totals under a system-wide label** — `get_status_impl` (`monitor_ops.py:302`) calls a bare `load_registry()`, which defaults to `fplan_registry.json`. Live output reads `Total plans: 354, Open plans: 1`; the true figures across all 7 registries are **705 total, 27 open**. `list_ops.py:132` already merges every registry before calling the same statistics handler, so the correct pattern exists one file away. Same type-blind class as the S33 `restore` bug — it survived in the health command.
- [ ] **`create` with no subject silently creates an unnamed plan** — `drone @flow create .` returned `Created FPLAN-0409` with `subject: ""` and no slug in the filename (`FPLAN-0409_2026-08-13.md`). It should refuse. Directly contradicts the branch's own standing rule — "if i type patrick and get a default, thats a silent fail, no thanks" (observation #7). Artefact closed and cleaned; the gap remains.
- [ ] **`unregister` + directory deletion strands a registry JSON forever** — `remove_type()` (`registry_ops.py:434`) deliberately leaves the plan registry file. Auto-prune (`_prune_orphaned_types`, `registry_ops.py:161`) *does* unlink it (line 180) but only matches types **still registered** whose directory went missing. Unregister first and the type row is already gone, so prune never sees it. Reproduced live: registering then unregistering `audit_test_plans` left `atplan_registry.json` behind. This is almost certainly how `flow_json/pbplan_registry.json` (1 closed plan, 2026-06-07) survived.
- [ ] **`flow_json/pbplan_registry.json` is an orphan** — PBPLAN is in no template registry. Holds one closed plan from a 2026-06-07 playbook test, before the prefix settled on PPLAN. Left in place (it is history, and house rule is never delete) but it should be archived, not sitting among live registries.
- [ ] **`flow_json/PLAN_REGISTRY.json` is legacy with zero readers** — `grep -rn "PLAN_REGISTRY.json" apps/ tests/` returns nothing. Holds 1 plan, no `last_updated`. Pre-dates the per-type registry split.
- [ ] **`close --all --dry-run` runs location and subject together** — output reads `.../src/aipass/devpulseBAUD is the face of AIPass`, with no separator between the location column and the subject. Cosmetic only; the non-dry-run path formats correctly.
- [ ] **`unregister --help` is treated as a type name, not a flag** — `drone @flow unregister --help` returns `Failed to unregister '--help'` instead of usage. `register --help` handles it correctly, so the two are inconsistent. Harmless (it failed safely) but wrong.
- [ ] **Three handler packages are empty** — `apps/handlers/config/`, `events/`, and `summary/` contain only `__init__.py` (`summary/` also has `generate.py(disabled)`). The README described `config/` as "Configuration loading" and `summary/` as vestigial; both now say EMPTY. A dead bypass rule for `config/load_config.py` was still defending one of them — deleted this session.

### Resolved

- [x] **A help flag after the first argument executed the verb instead of explaining it** (S52) — `drone @flow close FPLAN-0042 --help` did not print help, it **closed FPLAN-0042**. Every module gated help at `args[0]` only, so a flag typed later was invisible. seedgo's new `help_flag_safety` standard (DPLAN-0291 rule E) scored the branch **37%** and named 5 modules; a whole-sequence sweep found **3 more with the identical gate** that the standard did not flag — and two of those mutate: `registry scan --help` reached `scan_plan_files()` (writes the registry) and `post --help` reached the archive/vectorise runner. Fixed all 8 behind one shared predicate, `apps/handlers/cli/help_flags.py::wants_help()` — the copy-paste was the defect, so five copies were not replaced with eight. Gate sits **after** each module's ownership check, never top-of-function, so no module hijacks another's `--help` (the router tries modules in turn). Bare `help` counts at position 0 only, because flow's later slots are free text — proven live: `create . "Fix the help system onboarding"` still creates that plan. 40 red-first canaries, each asserting help printed **and** the destructive target never called. 37% → 100%, suite 787 → 827.
- [x] **A wildcard bypass hid `test_quality` for every file in the branch, with a false reason** (S51) — the rule was `{"file": "*", "standard": "test_quality", "reason": "test infrastructure not yet in place for flow branch"}`. Flow has 784 tests across 24 files and 88/88 public functions covered; the reason had been false for months. Removed it and re-audited: **`test_quality` scores 100% on its own** — it was suppressing nothing while telling every reader the branch was untested. This is the drone S50 lesson landing on my own file: a dead rule wastes space, but a rule with a false reason reads as settled and stops anyone asking.
- [x] **15 more dead bypass rules deleted** (S51) — 11 pointed at files that do not exist (`plan/create.py`, `plan/validate.py`, `mbank/restore_ops.py`, `summary/summary_ops.py`, `config/load_config.py`, `modules/dplan_post_close_runner.py` — mostly renames the bypass file never followed), and 4 were per-file duplicates of the `tests/*` wildcard that seedgo itself flagged. Proven dead the S47 way: deleted, then re-audited — still 100%, and the "suppresses nothing" notice is gone entirely. 74 → 58.
- [x] **README version drift closed** (S51) — README said 2.2.2, `drone @flow --version` said 2.2.1. Corrected the README *down*: no 2.2.2 was ever cut, and the version a user is shown is the one that runs. Long-standing item on the board, now off it.
- [x] **README truth pass, 9 corrections** (S51) — see Notes.

## What Needs Doing

### @flow to handle (dispatch)
- [ ] Wire backup recovery into `restore`'s step-5 file-missing branch (red-first), **or** strip the recovery promise from the docs — pending the ruling below.
- [ ] Make the `--help` command list render names modules **declare** rather than names derived from the module filename; add `templates` and drop `template`.
- [ ] Point `get_status_impl` at the merged registry set, reusing `list_ops`'s merge.
- [ ] Reject `create` with an empty subject.
- [ ] Have `remove_type()` archive the orphaned plan registry (or make prune sweep registry files with no owning type).
- [ ] Move `pbplan_registry.json` and `PLAN_REGISTRY.json` to `.archive/orphaned_registries/`.
- [ ] Fix the `close --all --dry-run` column separator; make `unregister` honour `--help`.

### devpulse to handle
- [x] **RULED 2026-08-13: option A, provisionally** — restore pulls the file back from `.backup/processed_plans/`. Patrick keeps a veto window; the build is red-first future work, and when it lands `TestRestoreFileMissing` gets rewritten to pin the new contract plus one real end-to-end companion, so the mock seam that hid this cannot re-form. **The ruling got independent corroboration the same day:** @devpulse had to restore @api's mistakenly-closed APLAN by *moving the file back by hand and then* running restore — the exact workaround my finding predicted. And the APLAN template now tells every branch "if you find a closed one in `.backup/processed_plans/`, restore it instead of recreating" — an instruction the tool cannot currently carry out. 374 archived plans are unreachable through the front door.
- [ ] **Original question, kept for the record: what `restore` is supposed to mean.** Option A: restore pulls the file back out of `.backup/processed_plans/` automatically — matches every doc we publish and makes the existing recovery code reachable. Option B: restore stays conservative (never resurrects archived content silently) and the README stops advertising backup recovery. Recommendation is **A**: the recovery function already exists, is tested, and correctly scopes by plan type — it is simply unreachable. This is a semantics call on other branches' archived work, so it should not be mine alone.

### Tracked elsewhere
- [ ] `quick_status` single-calculator seam with @prax (import a shared calculator instead of maintaining flow's copy) — **known morning discussion with Patrick in the loop**, ruled by @devpulse on 2026-08-13 to land as one conversation alongside the flow-SECTION schema question. Not built today, deliberately. Carried on the `.trinity` board.
  **Measured today, for that conversation:** the schema disagreement is not just in `quick_status`, it is in flow's *own* section. After Flow's plan push, `sections.flow.active_plans` is a **list of plan objects** (`[{id, subject, created, location}]`); after `drone @prax dashboard refresh @flow`, the same key in the same `managed_by: flow` section is an **int** (`1`). Both writers are self-consistent and neither is wrong on its own terms — but a consumer cannot type the field. `quick_status.active_plans` stayed `1` throughout, so the merge fix from FPLAN-0405 is holding; this is strictly the section-level schema.
- [ ] FPLAN 341-371 cluster reconstruction sweep — awaiting scheduled dispatch from @devpulse; agreed not to start unprompted.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fix round to 100 — help_flag_safety (dispatch 73f9956a) | Complete — 37% → 100%, overall 98% → 100%. 8 modules fixed (5 named + 3 found), one shared predicate, 40 red-first canaries, 787 → 827 green |
| 2026-08-13 | Fleet audit round DPLAN-0291, wave 2 (dispatch 340e547c) | Complete — YELLOW, 4 functional bugs found (restore, help names, registry status, empty subject), 16 bypasses removed incl. one false-reason wildcard, 9 README drifts fixed. restore ruled option A provisionally |
| 2026-08-13 | DPLAN-0290 item 4 — quick_status clobber | Accepted by @devpulse; single-calculator seam deferred to a morning discussion |
| 2026-08-12 | FPLAN-0405 — dashboard push merges instead of replacing | Shipped; re-verified live in this audit |

## Relationships
- **Related DPLANs:** DPLAN-0291 (this fleet audit round), DPLAN-0290 (night shift, quick_status)
- **Related FPLANs:** FPLAN-0405 (quick_status merge)
- **Owner branch:** @flow
- **Seedgo:** `drone @seedgo audit aipass @flow`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S51 (2026-08-13):** First full-branch audit. Method borrowed from @drone's
wave-1 APLAN: run everything, never trust a help screen.

*The live sweep* — 24 invocations covering the whole lifecycle (create ×3
templates, close, close --dry-run, close --all --dry-run, restore, list ×2,
templates, scan, registry scan/status, aggregate, post, register/unregister
round trip) plus 4 error paths. Scratch plans were created in `/tmp` and in a
throwaway subdirectory, then closed and removed; 4 registry numbers
(FPLAN-0406/0407/0408/0409, DPLAN-0292) were consumed by the sweep and are
closed, not dangling.

*The one that matters* — `restore` came out of doing the obvious thing: close a
plan, then try to get it back. The refusal message ("move file back first") is
polite enough to read like a designed constraint, which is presumably why it
has survived. It is not: the recovery function exists, is tested, handles
type-prefix scoping correctly, and sits one branch away from being called. The
close pipeline *moves* rather than copies, so the file is always exactly where
recovery would look. A recovery feature that is fully built, fully tested, and
never reached on the only path users take.

*Help screens lie in a specific way* — three separate findings (full names,
`template` vs `templates`, and the missing live verb) collapse into one root
cause: `flow.py` **derives** the command list from module filenames instead of
asking modules what they answer to. That is key_learning #46 again — I wrote
that lesson about `_count` labels in a dashboard and did not notice my own CLI
doing it. Deriving a name is guessing; the module is the only authority.

*Bypasses* — seedgo flagged 4 as suppressing nothing. Reading all 74 by hand
found 11 more aimed at files that no longer exist, and one wildcard that
disabled `test_quality` across the entire branch on the grounds that flow had
"no test infrastructure" — while the branch ran 784 tests. Removing it changed
the score by nothing, which is the whole point: for months the audit reported
100% on a standard it was not checking, and the reason string explained the
gap away convincingly enough that nobody looked. 74 → 58, still 100%, and the
100% now means what it says.

*README* — 9 corrections: version 2.2.2 → 2.2.1; `mbank/process.py` 669 → 718
lines (and it is over the 700 limit, not "nearing" it); `close_ops.py` 647 →
614 and `close_helpers.py` 260 → 257; test counts replaced with collected
figures; source files 40 → 42; `json_templates/` was missing from the tree
entirely; `config/`, `events/`, `summary/` documented as holding logic when
all three are empty; the restore claim rewritten to describe actual behaviour;
the unregister/prune gap documented; three new Known Issues added.

*Left alone deliberately* — all four functional bugs. The mandate was audit,
not build, and each one needs red-first tests; `restore` additionally needs a
ruling on what it should mean. Logging beats a rushed fix on the branch every
other branch depends on.

**S52 (2026-08-13, evening):** Fix round — `help_flag_safety`, 37% → 100%.

*The damage class was real, not theoretical.* Proven live before touching
anything: `drone @flow close FPLAN-9999 --help` returned "not found in
registry" — it had attempted the close. Against a plan that exists, a help
question would have closed it. Given that @devpulse spent today restoring
*three* plans closed by mistake, that is not a hypothetical cost.

*seedgo named 5; the branch had 8.* The standard flags modules whose remaining
arguments reach a parser. `list_plans`, `registry_monitor` and
`post_close_runner` carried the identical `args[0]`-only gate and were not
flagged — but `registry scan --help` reached `scan_plan_files()`, which
**writes** the registry, and `post --help` reached the archive-and-vectorise
runner. Fixing only the named five would have left two mutating verbs open on
the grounds that a scanner did not mention them. Ran the whole-sequence grep
instead of trusting the list.

*One predicate, nine call sites.* @drone and @trigger both concluded today that
the copy-paste WAS the defect; replacing five copies with eight would have
reproduced the bug's own mechanism. `wants_help()` lives in
`handlers/cli/help_flags.py`, matching their shape so the three files stay
comparable.

*Placement matters more than the check.* The gate goes **after** each module's
ownership check. Top-of-function, the first module the router offers a command
to would answer every other module's `--help` — @trigger proved that live
today. Three tests pin it: each module returns False, untouched, for a foreign
command carrying `--help`.

*Free text is why bare `help` is position-0 only.* Flow's later slots hold plan
subjects. Matching the word anywhere would break
`create . "Fix the help system onboarding"` — verified live that it still
creates that plan, and that `create . "help"` keeps "help" as the subject.

*The bypass I added.* `help_flags.py` trips `json_structure` (no
`log_operation`). I added a rule rather than logging — but this morning I
deleted 16 rules including one whose reason was fiction, so the bar for adding
one is now mine to meet: the reason states a checkable fact (pure predicate,
called before every command in 5 modules, logging would write a line per
invocation and make the help gate depend on the JSON layer it runs ahead of),
and it names @drone, @trigger and @memory carrying the identical rule for the
identical file. Verifiable, not plausible.

## Listen (TTS-friendly summary)

Flow is marked yellow. The everyday work is healthy: creating plans, listing
them, and closing them all work correctly, the test suite passes with eight
hundred and twenty seven tests green and one skipped, and the standards audit
scores one hundred percent across forty five standards with no type errors.
Twenty four commands were run for real rather than checked in help screens,
and nothing crashed anywhere.

One serious bug was fixed this evening. A help flag typed after the first
argument was invisible to every module, so asking for help ran the command
instead. Closing a plan and asking for help at the same time closed the plan.
A new standard scored flow at thirty seven percent and named five modules;
checking the whole branch found three more with the same flaw, two of which
change data, including one that rewrites the plan registry. All eight are
fixed behind a single shared helper, with forty new tests written to fail
first, each one checking both that help was printed and that the dangerous
action never ran. That standard is now at one hundred percent.

It is yellow because four advertised behaviours do not match what the code
does. The most serious is restore. When a plan is closed, its file is moved
into the backup archive. If you then try to restore that plan, flow refuses
and tells you to move the file back by hand, even though the archived copy is
sitting right there and flow contains a working, tested function for
recovering it. That function is only ever called when a plan is missing from
the registry altogether, which never happens to a normally closed plan. So
every normally closed plan cannot be restored. This was proven twice with real
plans.

The second problem is the help screen. It tells you that every command can be
called by its short name or its full name, but seven of the eight modules only
answer to the short name. It also lists a command called template that no part
of the system accepts, while the command that actually works, templates, is
missing from the list. All three of these come from one cause: the help screen
guesses command names from filenames instead of asking each module what it
responds to.

Third, the registry status command reports the totals for only one plan type
while labelling them as system wide. It says three hundred and fifty four
plans with one open, when the real figures across all types are seven hundred
and five plans with twenty seven open. Fourth, creating a plan without giving
it a subject silently succeeds and produces an unnamed plan, when it should
refuse.

Two cleanups were completed. Sixteen bypass rules were removed and proven
dead, including one that had switched off test quality checking for the entire
branch on the false grounds that flow had no test infrastructure, while the
branch was running seven hundred and eighty four tests. The score did not
change when it was removed, which means the audit had been reporting full
marks on a standard it was not actually checking. Nine factual errors in the
readme were also corrected, including the long standing version mismatch.

What needs attention next: devpulse should rule on whether restore is meant to
recover from the archive, since that decision affects other branches archived
work. Everything else on the list belongs to flow and needs red first tests
rather than an audit day edit.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
