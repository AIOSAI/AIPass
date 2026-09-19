# Known issues

**Branch** memory · **Code** branch-wide
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

Standing defects and the measurement behind each one. An item stays here with its cure named rather
than being deleted, because a cured issue that says how it was cured is worth more than a gap.

---

## Open

- `search` requires `fastembed` in the venv `_get_memory_python()` resolves to — fails without it.
- **PreCompact cannot roll a todo pad as wired today** (measured 2026-09-15; @hooks' lane, FPLAN-0590
  row 7). @hooks' `handlers/lifecycle/rollover.py` runs `drone @memory rollover check` and `rollover run`
  with `cwd=<repo root>` and no `--branch`. Drone stamps its own working directory into
  `AIPASS_CALLER_CWD`, overriding an inherited one (`AIPASS_CALLER_CWD=<memory dir> drone @memory todo`
  run from the repo root prints the no-branch line), so that check resolves no branch and never says
  `ready for rollover` for a pad. Until the hook names the branch, a pad rolls on
  `rollover run --branch @name`, a `rollover run` from inside the branch, or the trinity push.
- **`.seedgo/bypass.json` holds 41 rules for 12 files that no longer exist** (parked 08-14 / 08-18, plus
  `templates/differ.py` and `templates/pusher.py` retired 08-27) plus one duplicate `(file, standard)`
  pair. Re-counted 2026-09-05 at 114 rules across 40 files. Re-counted again 2026-09-15: **115 rules
  across 41 files**, and the absent-file half is unchanged at 41 rules over 12 files. Inert, but the
  registry no longer describes the tree.
- **The receipt writer's `spawn birth` lane is still unwired.** `handlers/templates/receipt.py` now stamps
  for real from the trinity push (`stamped_by: "memory push"`, verified live on @canary), and a tab
  refresh bumps `config_rendered`. `spawn birth` adopts the writer separately — not built here.
- **22 branches carry stray files in `.trinity/`, 56 files in total** — File set group, and outside the
  push's mandate: it reports them per branch in the dry-run and never touches them. Needs a ruling.
  Re-measured 2026-09-05 by walking `registry_scope.fleet_branches()`, which now returns **28** branches
  (up from 22 as external roots joined): 22 of the 28 carry leftovers, almost all `*.pre_v2_backup` /
  `*.pre_v3_backup` migration files, plus devpulse's older `*.pre-aipl` pair. This supersedes the 08-27
  reading of 16 — the count rose with the fleet, not with new litter. The README half of this item stays
  closed.
- **Two `--help` pages contradict what the code actually does** (found 2026-09-05 during the README truth
  pass; recorded, not fixed — that pass was docs-only; all three still read as described on 2026-09-15).
  (1) `rollover --help` lists the execute verb as `rollover` in its COMMANDS block, but the verb is
  **`run`** — `drone @memory rollover run` is what works and what the bare-module introspection correctly
  advertises. (2) `lint --help` says bare `drone @memory lint` scans all branches; it does **not** — bare
  `lint` prints the introspection banner, as the item below records and as the introspection itself says.
  Both are help-text defects in this branch's own modules, so the fix is mine to make. (3) Lower stakes,
  same family: the `--json` example under `rollover --help` FLAGS shows `"branches": 17` where the live
  fleet is 22.
- **The parked symbolic test tier: three files archived 2026-09-07 on the owner's ruling.** An opus judging
  pass on 2026-09-05 (reported via @devpulse) marked every row of `tests/test_symbolic_module.py`,
  `tests/test_symbolic.py` and `tests/test_symbolic_cli.py` as delete-or-merge candidates on the grounds
  that the symbolic tier has been parked since 2026-08-14. The owner ruled 2026-09-07 01:16 ("old tests not
  needed now can all be archived"); the three files moved to `tests/.archive/deleted_2026-09-07_*.py`
  (FPLAN-0491, devpulse), and the three matching rows left `KNOWN_BARE_PACKAGE_STAND_INS` in
  `test_import_isolation.py` as that test's own failure message prescribes. Measured before the move: the
  judging pass described `test_symbolic_module.py` as 11 tests, but it held **54** `def test_` lines, and
  none of the three collected (module-level skip against the parked stub), so the suite lost 3 skips and
  no executing test. `test_symbolic_extras.py` and `test_vector.py` still skip at import and stay on disk.
  Revival steps remain in `tests/parked/symbolic_20260814/`.
- Bare `drone @memory lint` prints the introspection banner rather than scanning — `lint run` or
  `lint @branch` is the scan. Consistent with every other module's no-args convention; noted because the
  Quick Start used to read as if bare `lint` audited.

---

## Cleared

**Cleared 2026-08-27 (marker 7 — the template lane and the fleet definition):** (1) `rollover sync-lines`
is renamed **`rollover report-lines`** and is genuinely read-only — the fleet-wide `refresh_all_tabs()` it
ran on the tail is gone from `report_line_counts()`; the old name still routes, names the new verb, and
runs the reporter. (2) `push-templates` and `diff-templates` are **retired**: both refuse and name the
live lane, and `pusher.py` / `differ.py` plus their two test files are archived at
`tests/parked/dead_template_lane_20260827/`. `template-status` survives, repointed at the per-branch
`.trinity/.template_version.json` receipts. (3) The registry gap is closed —
`detector._read_registry()` reads the resident registries from `registry_scope.RESIDENT_REGISTRIES`, so
rollover, lint and health reach all 22 branches (measured: `_read_registry()` → 22 branches,
`report-lines` → 44 files).

**Cleared 2026-08-27 (the trinity push build):** (1) `drone @memory push` no longer aliases
`rollover push` — the bare word that fired an unprompted fleet-wide `per_branch` CONFIG reset on 18
branches now runs the trinity push, whose fleet lane refuses without `--confirm`; the config reset keeps
its explicit `rollover push` verb, and a source-scan test fails if the alias returns. (2) A rollover's tab
refresh is scoped to the branches it actually rolled (`refresh_all_tabs(branches=…)`), so no citizen's
PreCompact hook can propagate renderer changes fleet-wide again — the 23:37 write of 38 files that opened
this arc.

**Cleared 2026-08-25:** the entry-point `encapsulation` finding (66% on `apps/memory.py` for importing two
`monitor/` handlers) — `watch` is a module now and a contract test fails the suite if any handler import
returns to the entry point. Also cleared: `pool.py` / `lint.py` at 85% on `introspection`. Seedgo re-run
2026-08-25 reports **100% on all 45 rules**, both findings gone.

**Cleared 2026-08-13:** `rollover status` showing 0 branches did not reproduce (19 branches across two
working directories at the 08-25 re-run). `memory_threshold_exceeded` appears nowhere in this branch's
code — the previous note described @trigger's registry, not memory's.

---

## Related

- [quality_and_proof.md](quality_and_proof.md) — how the suite and the audit are measured
- [trinity_push.md](trinity_push.md) — the lane whose alias and receipt items are recorded above
- [todos_and_backlog.md](todos_and_backlog.md) — the pad the PreCompact item cannot reach
- [cli_surface.md](cli_surface.md) — the introspection convention bare `lint` follows
