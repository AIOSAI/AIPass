[← Back to Flow](../README.md)

# Known Issues

Two entries below were cured in the 2026-09-15 README diet, and are struck
through rather than deleted so the measurement that found them survives.

Defects found by measurement and left standing on purpose, each with what was measured and why it was not cured in that pass. Reported, not hidden.

---

- ~~`--version` prints `FLOW v2.2.1` while the README header says 2.6.0.~~
  **Cured 2026-09-15.** Found 2026-09-05 and left standing through two passes
  because the string was a literal inside the print call, so neither number
  could read the other and picking the true one was a decision rather than a
  typo fix. Now one name: `BRANCH_VERSION` in `apps/flow.py`, printed by
  `--version` and carried by the README header, both at 2.7.0.
- ~~`apps/handlers/json_templates/` has no readers left.~~ **Archived
  2026-09-07** to `apps/handlers/.archive/json_templates_archived_2026-09-07/`
  (moved, never deleted — @devpulse's ruling). Re-measured before moving: 23
  fleet-wide mentions of `json_templates`, every one of them a skip-list entry
  in another branch's scanner, and zero readers of flow's directory. The seed
  payloads it held were replaced by `_default_document()` inside `@prax`'s
  `json_service.py` — a default that lives in a file can go missing; one in code
  cannot.
- **309 of 827 closed plans have no archived copy and cannot be restored.**
  Fixed 2026-08-22: `restore` now falls back to `.backup/processed_plans/` when
  the file is **not at** the registered `file_path`. Note the correction — the
  row's `file_path` is *not* emptied by close; it is left pointing at where the
  file used to be. Re-measured 2026-09-05: all 827 closed rows carry a
  `file_path`, and **0 of 827** have a file there. Before that fix restore
  failed for every closed plan while the archive sat intact beside it.
  Coverage by close month: 2026-03 (198 rows) and 04 (97) are **0%**, 05 is
  89%, 06 is 100%, 07 is 99%, 08 is 98%, 09 is 100%. The 295 pre-May rows have no artifact
  to recover — that is a gap in the archive, not in restore, and it is not
  recoverable by code. A second, narrower refusal also applies: restore copies
  the archived file back to its *registered* directory, so a row whose original
  directory no longer exists is refused by name rather than re-homed.
- ~~`--help` advertises full module names that the dispatcher rejects.~~
  **Cured 2026-09-15.** It printed "Commands can be called by short name or
  full name" while only the short verb executes, and listed `template`, which
  no module accepts. The table now renders what the dispatcher answers to: a
  module owning several verbs declares them in `COMMAND_VERBS`, read by
  `module_verbs()` in `apps/flow.py`, so `template_manager` publishes
  `templates, register, unregister, scan` and the derived name is used only
  where it is true. `post` remains the one module accepting its full name too,
  verified at `apps/modules/post_close_runner.py:64`.
- **`registry status` counts only FPLAN.** It reports the default registry's
  totals under a system-wide label — re-measured 2026-09-05 it prints
  **439 total / 7 open**, which is `fplan_registry.json` exactly, where the true
  figures across every registry on disk are **855 / 28**. Cause:
  `get_status_impl` calls a bare `load_registry()`. Its quarantine list and
  `Ignored folders: 33` are branch-wide and correct; only the two totals are
  scoped to one type.
- **The cross-branch handler fence never arms.** `apps/__init__.py` is
  `from . import handlers`, so importing *anything* under `aipass.flow.apps`
  loads the handlers package first, and at that moment the nearest real-file
  frame is `apps/__init__.py` itself — which lives under `/flow/` and is
  therefore allowed. An external branch reaching for a flow handler passes the
  guard every time. Reported, deliberately NOT fixed: the owner's fleet ruling
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
- **`flow_json/PLAN_REGISTRY.json` is legacy and no longer read.** Re-measured
  2026-09-05: zero code readers fleet-wide — the only two `PLAN_REGISTRY` mentions
  left outside `.archive/` are docstrings (flow's own `plan/project_scope.py`,
  `@hooks`' `security/edit_gate.py`), and the file still holds 1 plan row against
  `next_number: 402`. @trigger
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
- `mbank/process.py` at 723 lines (over the 700 limit; 718 on 2026-08-31)
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
- `close_ops.py` was split into `close_ops.py` + `close_helpers.py` (263 lines),
  but `close_ops.py` has since grown back to **848 lines** — over the 700 limit,
  and still the longest file in the branch (`mbank/process.py` is 723). All three
  re-measured 2026-09-05
- `push_central.py` comprehensive rewrite (2026-06-02): now pushes all branches' plans, not just flow's — fixed dashboard refresh zeroing other branches' plan counts

---

*Last Updated: 2026-09-05*

---
[← Back to AIPass](../../../README.md)
